"""Offline pinned-SDK integration including a real loopback Responses server."""

import asyncio
import json
import os
import socket
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from byoe import hosting

CHAT = {"kind": "openai_chat", "endpoint_env": "HOST_MODEL_URL", "model_env": "HOST_MODEL_ID"}


def test_environment_restored_on_error(monkeypatch):
    for key in hosting.HOST_ENV_KEYS:
        monkeypatch.setenv(key, "original")
    monkeypatch.setenv("INFERENCE_ONLY", "independent")
    with pytest.raises(RuntimeError), hosting.isolated_hosting_environment():
        assert os.environ["INFERENCE_ONLY"] == "independent"
        assert "AGENT_PROJECT_NAME" not in os.environ
        assert "AGENT_PROJECT_RESOURCE_ID" not in os.environ
        assert "AZURE_AI_PROJECT_ENDPOINT" not in os.environ
        assert "OTEL_EXPORTER_ENDPOINT" not in os.environ
        raise RuntimeError
    assert all(os.environ[key] == "original" for key in hosting.HOST_ENV_KEYS)


def test_load_config_env_paths(tmp_path, monkeypatch):
    config = tmp_path / "model.json"
    policy = tmp_path / "instructions.md"
    config.write_text(json.dumps(CHAT), encoding="utf-8")
    policy.write_text("Use the policy", encoding="utf-8")
    monkeypatch.setenv("MODEL_CONFIG_FILE", str(config))
    monkeypatch.setenv("BYOE_INSTRUCTIONS_FILE", str(policy))
    actual, instructions = hosting.load_hosting_config()
    assert actual["endpoint_env"] == "HOST_MODEL_URL"
    assert instructions == "Use the policy"
    config.write_text('{"kind":"python","kind":"openai_chat"}', encoding="utf-8")
    with pytest.raises(ValueError, match="MODEL_CONFIG_FILE"):
        hosting.load_hosting_config()


def test_default_config_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(hosting, "ROOT", tmp_path)
    monkeypatch.delenv("MODEL_CONFIG_FILE", raising=False)
    monkeypatch.delenv("BYOE_INSTRUCTIONS_FILE", raising=False)
    (tmp_path / "configs").mkdir()
    (tmp_path / "data").mkdir()
    (tmp_path / "configs/model.foundry.json").write_text(json.dumps(CHAT), encoding="utf-8")
    (tmp_path / "data/instructions.md").write_text("Policy", encoding="utf-8")
    assert hosting.load_hosting_config()[1] == "Policy"


def test_python_hosting_explicitly_unsupported():
    async def check():
        with pytest.raises(ValueError, match="Python model hosting is unsupported"):
            async with hosting.hosted_agent({"kind": "python", "entrypoint": "no_import:fn"}, "x"):
                pytest.fail("hosted python unexpectedly")

    asyncio.run(check())


def test_hosted_chat_actual_sdk_no_auth_and_endpoint(monkeypatch):
    import httpx2
    import openai

    observed = []
    transports = []

    def respond(request):
        observed.append(request)
        return httpx2.Response(200, json={
            "id": "chatcmpl_test", "object": "chat.completion", "created": 0,
            "model": "independent-model", "choices": [{"index": 0,
                "message": {"role": "assistant", "content": "offline SDK output"},
                "finish_reason": "stop"}],
        })

    def transport(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        client = httpx2.AsyncClient(transport=httpx2.MockTransport(respond), **kwargs)
        transports.append(client)
        return client

    monkeypatch.setattr(openai, "DefaultAsyncHttpxClient", transport)
    monkeypatch.setenv("HOST_MODEL_URL", "https://public.example.invalid/custom/v1/chat/completions")
    monkeypatch.setenv("HOST_MODEL_ID", "independent-model")
    monkeypatch.setenv("OPENAI_API_KEY", "DO_NOT_USE_AMBIENT_KEY")
    monkeypatch.setenv("AZURE_AI_PROJECT_ENDPOINT", "https://hosting.example.invalid")

    async def check():
        async with hosting.hosted_agent(CHAT, "Policy", timeout=4) as agent:
            response = await agent.run("A question")
            assert response.text == "offline SDK output"

    asyncio.run(check())
    assert str(observed[0].url) == "https://public.example.invalid/custom/v1/chat/completions"
    assert "authorization" not in observed[0].headers
    body = json.loads(observed[0].content)
    assert body["model"] == "independent-model" and body["store"] is False
    assert any(m["content"] == "Policy" for m in body["messages"])
    assert all(t.is_closed for t in transports)


def test_hosted_chat_token_auth_and_no_redirects(monkeypatch):
    import httpx2
    import openai

    observed = []

    def respond(request):
        observed.append(request)
        return httpx2.Response(302, headers={"Location": "https://other.invalid"})

    monkeypatch.setattr(openai, "DefaultAsyncHttpxClient", lambda **kwargs: httpx2.AsyncClient(
        transport=httpx2.MockTransport(respond), **kwargs,
    ))
    monkeypatch.setenv("HOST_MODEL_URL", "http://127.0.0.1:9999/v1/chat/completions")
    monkeypatch.setenv("HOST_MODEL_ID", "local-model")
    monkeypatch.setenv("HOST_MODEL_TOKEN", "explicit-test-token")

    async def check():
        config = {**CHAT, "token_env": "HOST_MODEL_TOKEN"}
        async with hosting.hosted_agent(config, "Policy") as agent:
            with pytest.raises(Exception):
                await agent.run("question")

    asyncio.run(check())
    assert len(observed) == 1
    assert observed[0].headers["authorization"] == "Bearer explicit-test-token"


def test_foundry_hosted_actual_sdk_and_credential_cleanup(monkeypatch):
    import azure.ai.projects.aio
    import azure.identity.aio
    import httpx2
    import openai

    requests = []
    credential = MagicMock(spec=["__aenter__", "__aexit__", "get_token"])
    credential.__aenter__ = AsyncMock(return_value=credential)
    credential.__aexit__ = AsyncMock()
    credential.get_token = AsyncMock(return_value=SimpleNamespace(
        token="offline-token", expires_on=9999999999,
    ))
    monkeypatch.setattr(azure.identity.aio, "DefaultAzureCredential", lambda: credential)

    def respond(request):
        requests.append(request)
        return httpx2.Response(200, json={
            "id": "resp_test", "object": "response", "created_at": 0,
            "status": "completed", "error": None, "incomplete_details": None,
            "model": "actual-deployment", "output": [{"type": "message", "id": "msg_test",
                "status": "completed", "role": "assistant",
                "content": [{"type": "output_text", "text": "Foundry model output",
                             "annotations": []}]}],
        })

    monkeypatch.setattr(openai, "DefaultAsyncHttpxClient", lambda **kwargs: httpx2.AsyncClient(
        transport=httpx2.MockTransport(respond), **kwargs,
    ))
    monkeypatch.setenv("HOST_MODEL_URL", "https://inference.invalid/api/projects/models")
    monkeypatch.setenv("HOST_MODEL_ID", "actual-deployment")
    monkeypatch.setenv("AZURE_AI_PROJECT_ENDPOINT", "https://host-only.invalid/api/projects/host")

    async def check():
        async with hosting.hosted_agent({**CHAT, "kind": "foundry_model"}, "Policy") as agent:
            assert (await agent.run("question")).text == "Foundry model output"

    asyncio.run(check())
    assert len(requests) == 1
    assert str(requests[0].url) == "https://inference.invalid/api/projects/models/openai/v1/responses"
    body = json.loads(requests[0].content)
    assert body["model"] == "actual-deployment" and body["store"] is False
    assert "conversation" not in body
    credential.get_token.assert_awaited()
    credential.__aexit__.assert_awaited_once()


def test_real_adapter_loopback_readiness_and_responses(monkeypatch):
    import httpx
    import uvicorn
    from agent_framework import Agent, ChatResponse, Message

    class OfflineClient:
        async def get_response(self, messages, **kwargs):
            return ChatResponse(messages=[Message("assistant", text="offline hosted response")])

    # Poison every cloud discovery setting. Any accidental request must fail.
    monkeypatch.setenv("AZURE_AI_PROJECT_ENDPOINT", "https://never-contact.invalid/api/projects/host")
    monkeypatch.setenv("AGENT_PROJECT_NAME", "account@project")
    monkeypatch.setenv("AGENT_PROJECT_RESOURCE_ID", "account@project")
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "invalid-test-only")
    import azure.ai.projects

    monkeypatch.setattr(azure.ai.projects, "AIProjectClient",
                        lambda *a, **k: pytest.fail("cloud discovery"))

    async def check():
        agent = Agent(OfflineClient(), name="offline-test", instructions="Test only")
        adapter = hosting.create_adapter(agent)
        assert adapter.project_endpoint is None and adapter._project_endpoint is None
        assert adapter._session_repository.__class__.__name__ == "InMemoryAgentSessionRepository"
        assert adapter.tracer is not None
        # Pre-bound ephemeral socket eliminates hard-coded ports and readiness polling.
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        ready = asyncio.Event()
        original_lifespan = adapter.app.router.lifespan_context

        @asynccontextmanager
        async def lifespan(app):
            async with original_lifespan(app):
                ready.set()
                yield

        adapter.app.router.lifespan_context = lifespan
        server = uvicorn.Server(uvicorn.Config(
            adapter.app, host="127.0.0.1", port=port, log_level="error",
        ))
        task = asyncio.create_task(server.serve(sockets=[sock]))
        try:
            await asyncio.wait_for(ready.wait(), 10)
            async with httpx.AsyncClient(
                base_url=f"http://127.0.0.1:{port}", trust_env=False,
            ) as client:
                response = await client.get("/readiness")
                assert response.status_code == 200
                response = await client.post("/responses", json={
                    "input": "Question", "stream": False, "store": False,
                })
                assert response.status_code == 200
                body = response.json()
                assert body["status"] == "completed"
                assert body["output"][0]["content"][0]["text"] == "offline hosted response"
        finally:
            server.should_exit = True
            await asyncio.wait_for(task, 10)
            await adapter.credentials.close()
            sock.close()

    asyncio.run(check())
    assert os.environ["AGENT_PROJECT_NAME"] == "account@project"


def test_cli_defaults_and_explicit_external_host(monkeypatch):
    import hosted_main

    calls = []

    async def serve(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(hosted_main, "serve", serve)
    assert hosted_main.main([]) == 0
    assert hosted_main.main(["--host", "0.0.0.0", "--port", "9000"]) == 0
    assert calls == [{"host": "127.0.0.1", "port": 8090}, {"host": "0.0.0.0", "port": 9000}]


def test_cli_redacts_provider_errors(monkeypatch, capsys):
    import hosted_main

    async def fail(**kwargs):
        raise ValueError("PRIVATE_PROVIDER_TOKEN")

    monkeypatch.setattr(hosted_main, "serve", fail)
    assert hosted_main.main([]) == 2
    assert "PRIVATE" not in capsys.readouterr().err