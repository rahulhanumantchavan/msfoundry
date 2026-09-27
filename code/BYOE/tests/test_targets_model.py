"""Offline providers and real subprocess boundaries; never production fallbacks."""

import importlib
import json
import os
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from byoe import model, target_worker, targets
from byoe.contracts import Case, Suite, preflight

CHAT = {"kind": "openai_chat", "endpoint_env": "TEST_ENDPOINT", "model_env": "TEST_MODEL"}
FOUND = {**CHAT, "kind": "foundry_model"}
PYTHON = {"kind": "python", "entrypoint": "tests.test_targets_model:offline_complete"}
MESSAGES = [{"role": "user", "content": "Question"}]
SAFE = {"id": "one", "query": "Question", "context": {"policy": "public"}, "metadata": {}}


def offline_complete(messages, timeout):
    """Explicit test provider, also exercised inside the child interpreter."""
    print("diagnostics must never become response text")
    assert timeout > 0
    return json.dumps({"messages": messages, "cwd": str(Path.cwd())})


def offline_slow(messages, timeout):
    time.sleep(30)
    return "too late"


def offline_error(messages, timeout):
    raise RuntimeError("PRIVATE_TOKEN_AND_PROMPT")


@pytest.fixture
def remote_env(monkeypatch):
    monkeypatch.setenv("TEST_ENDPOINT", "https://example.invalid/v1/chat/completions")
    monkeypatch.setenv("TEST_MODEL", "actual-deployment")


def test_openai_body_auth_and_response(monkeypatch, remote_env):
    def post(config, body, timeout):
        assert config == {"endpoint_env": "TEST_ENDPOINT", "token_env": "TEST_TOKEN",
                          "azure_scope": None}
        assert body == {"model": "actual-deployment", "messages": MESSAGES}
        assert timeout == 5
        return {"choices": [{"message": {"content": " real output "}}]}

    monkeypatch.setattr(model, "post_json", post)
    assert model.complete({**CHAT, "token_env": "TEST_TOKEN"}, MESSAGES, 5) == " real output "


@pytest.mark.parametrize("value", [None, "", "   ", 1, [], {}])
def test_openai_rejects_invalid_text(monkeypatch, remote_env, value):
    monkeypatch.setattr(model, "post_json", lambda *a: {
        "choices": [{"message": {"content": value}}],
    })
    with pytest.raises(ValueError, match="Model completion failed"):
        model.complete(CHAT, MESSAGES, 1)


@pytest.mark.parametrize("config", [
    {**FOUND, "token_env": "TOKEN"}, {**FOUND, "azure_scope": "scope"},
    {**CHAT, "entrypoint": "somewhere:fn"}, {**PYTHON, "endpoint_env": "ENDPOINT"},
    {**CHAT, "unknown": "PRIVATE"}, {"kind": "foundry_agent"},
    {**CHAT, "token_env": "TOKEN", "azure_scope": "scope"},
])
def test_unsupported_model_settings_never_import(monkeypatch, config):
    monkeypatch.setattr(importlib, "import_module", lambda *a: pytest.fail("imported code"))
    with pytest.raises(ValueError, match="configuration"):
        model.complete(config, MESSAGES, 1)


@pytest.mark.parametrize("timeout", [0, -1, True, float("inf"), float("nan"), "3"])
def test_invalid_timeouts(timeout):
    with pytest.raises(ValueError, match="timeout"):
        model.complete(PYTHON, MESSAGES, timeout)
    with pytest.raises(ValueError, match="timeout"):
        targets.collect_response({"kind": "model", "model": PYTHON}, Case(**SAFE), timeout)


@pytest.mark.parametrize("endpoint", [
    "https://example.invalid/v1", "https://example.invalid/v1/chat/completions/",
    "http://example.invalid/chat/completions", "https://user:secret@example.invalid/chat/completions",
])
def test_bad_model_endpoint(monkeypatch, remote_env, endpoint):
    monkeypatch.setenv("TEST_ENDPOINT", endpoint)
    monkeypatch.setattr(model, "post_json", lambda *a: pytest.fail("request attempted"))
    with pytest.raises(ValueError):
        model.complete(CHAT, MESSAGES, 1)


def response_body(**updates):
    return {"status": "completed", "error": None, "output": [
        {"type": "reasoning", "summary": []},
        {"type": "message", "status": "completed", "content": [
            {"type": "output_text", "text": "Hello "},
            {"type": "output_text", "text": "world"},
        ]},
    ], **updates}


def test_responses_blocks_and_sdk_shortcut():
    assert model.responses_text(response_body(), require_status=True) == "Hello world"
    sdk = SimpleNamespace(output_text="SDK text", model_dump=lambda: response_body())
    assert model.responses_text(sdk) == "SDK text"
    assert model.responses_text({"type": "response.completed", "response": response_body()},
                                require_status=True) == "Hello world"


@pytest.mark.parametrize("value", [
    {}, {"status": "in_progress", "output_text": "partial"},
    response_body(error={"message": "private"}), response_body(status="failed"),
    response_body(incomplete_details={"reason": "limit"}), response_body(output="bad"),
    response_body(output=[{"type": "message", "status": "in_progress", "content": []}]),
    response_body(output=[{"type": "message", "content": "bad"}]),
    response_body(output=[{"type": "message", "content": [{"type": "output_text", "text": 3}]}]),
    {"type": "response.error", "response": response_body()},
    {"response": response_body(error={"code": "failure"})},
    {"response": response_body(status="incomplete")}, {"response": "bad"},
])
def test_responses_fail_closed(value):
    with pytest.raises(ValueError):
        model.responses_text(value, require_status=True)


def test_foundry_sdk_model_not_agent(monkeypatch):
    import azure.ai.projects
    import azure.identity

    monkeypatch.setenv("TEST_ENDPOINT", "https://example.invalid/api/projects/inference")
    monkeypatch.setenv("TEST_MODEL", "deployment-not-an-agent")
    credential = MagicMock()
    credential.__enter__.return_value = credential
    project = MagicMock()
    project.__enter__.return_value = project
    client = MagicMock()
    client.__enter__.return_value = client
    project.get_openai_client.return_value = client
    client.with_options.return_value.responses.create.return_value = response_body()
    project_ctor = MagicMock(return_value=project)
    monkeypatch.setattr(azure.ai.projects, "AIProjectClient", project_ctor)
    monkeypatch.setattr(azure.identity, "DefaultAzureCredential", lambda: credential)
    assert model.complete(FOUND, MESSAGES, 7) == "Hello world"
    project_ctor.assert_called_once_with(
        endpoint="https://example.invalid/api/projects/inference", credential=credential,
    )
    client.with_options.assert_called_once_with(timeout=7.0, max_retries=0)
    client.with_options.return_value.responses.create.assert_called_once_with(
        model="deployment-not-an-agent", input=MESSAGES, store=False,
    )
    project.agents.create_version.assert_not_called()
    project.__exit__.assert_called_once()
    credential.__exit__.assert_called_once()
    client.__exit__.assert_called_once()


def test_python_lazy_and_redacted(monkeypatch):
    seen = []
    module = SimpleNamespace(complete=lambda messages, timeout: seen.append(messages) or "real")
    monkeypatch.setattr(importlib, "import_module", lambda name: module)
    config = {"kind": "python", "entrypoint": "trusted_provider:complete"}
    model.validate_model(config)
    assert not seen
    assert model.complete(config, MESSAGES, 2) == "real"
    assert seen == [MESSAGES]
    module.complete = lambda *a: (_ for _ in ()).throw(ValueError("PRIVATE"))
    with pytest.raises(ValueError) as error:
        model.complete(config, MESSAGES, 2)
    assert "PRIVATE" not in str(error.value)


def test_target_parent_payload_is_answer_blind(monkeypatch):
    def run(command, payload, timeout, *, env):
        raw = payload.decode()
        assert "PRIVATE_EXPECTED" not in raw and "PRIVATE_RESPONSE" not in raw
        value = json.loads(raw)
        assert set(value["case"]) == {"id", "query", "context", "metadata"}
        assert value["cwd"] == str(Path.cwd())
        assert 0 < timeout <= 10
        assert command[-1] == "byoe.target_worker"
        return b'{"ok":true,"response":"real"}'

    monkeypatch.setattr(targets, "run_process", run)
    case = Case(**SAFE, expected={"answer": "PRIVATE_EXPECTED"}, response="PRIVATE_RESPONSE")
    assert targets.collect_response({"kind": "model", "model": PYTHON}, case, 10) == "real"


def test_model_worker_safe_messages(monkeypatch):
    def complete(config, messages, timeout):
        assert messages[0] == {"role": "system", "content": "Policy"}
        assert json.loads(messages[1]["content"]) == {
            "query": SAFE["query"], "context": SAFE["context"], "metadata": {},
        }
        return "answer"

    monkeypatch.setattr(target_worker, "complete", complete)
    assert target_worker.invoke_target(
        {"kind": "model", "model": PYTHON, "instructions": "Policy"}, SAFE, 10,
    ) == "answer"
    with pytest.raises(ValueError, match="input fields"):
        target_worker.invoke_target({"kind": "model", "model": PYTHON},
                                    {**SAFE, "expected": {}}, 10)


@pytest.mark.parametrize("result", [
    {}, {"schema_version": "2.0", "response": "yes"},
    {"schema_version": "1.0", "response": ""},
    {"schema_version": "1.0", "response": "yes", "error": "bad"},
])
def test_canonical_http_rejects_malformed(monkeypatch, result):
    monkeypatch.setattr(target_worker, "post_json", lambda *a: result)
    with pytest.raises(ValueError):
        target_worker.invoke_target({"kind": "http", "endpoint_env": "ENDPOINT"}, SAFE, 2)


def test_target_http_and_foundry_request(monkeypatch):
    def post(config, body, timeout):
        assert config["endpoint_env"] == "INDEPENDENT_TARGET_ENDPOINT"
        assert config["azure_scope"] == "https://ai.azure.com/.default"
        assert body == {"schema_version": "1.0", **SAFE}
        return {"schema_version": "1.0", "response": "canonical"}

    config = {"kind": "http", "endpoint_env": "INDEPENDENT_TARGET_ENDPOINT",
              "azure_scope": "https://ai.azure.com/.default"}
    monkeypatch.setattr(target_worker, "post_json", post)
    assert target_worker.invoke_target(config, SAFE, 3) == "canonical"

    def foundry_post(config, body, timeout):
        assert set(body) == {"input", "store", "stream"}
        assert body["store"] is False and body["stream"] is False
        assert SAFE["query"] in body["input"] and '"policy": "public"' in body["input"]
        return response_body()

    monkeypatch.setattr(target_worker, "post_json", foundry_post)
    assert target_worker.invoke_target(
        {**config, "kind": "foundry_agent"}, SAFE, 3,
    ) == "Hello world"


def test_preflight_python_trust():
    suite = Suite.model_validate({"evaluators": [{"id": "http", "kind": "http",
                                                  "config": {"endpoint_env": "EVAL"}}],
                                 "target": {"kind": "model", "model": PYTHON}})
    with pytest.raises(ValueError, match="allow_code"):
        preflight(suite)


def test_real_python_worker_preserves_cwd_and_separates_stdout(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.chdir(root)
    response = targets.collect_response({"kind": "model", "model": PYTHON}, Case(**SAFE), 10)
    parsed = json.loads(response)
    assert parsed["cwd"] == str(root)
    assert "diagnostics" not in response


def test_real_worker_plugin_relative_paths(tmp_path, monkeypatch):
    (tmp_path / "relative.txt").write_text("relative output", encoding="utf-8")
    (tmp_path / "local_provider.py").write_text(
        "from pathlib import Path\ndef complete(messages, timeout):\n"
        "    return Path('relative.txt').read_text(encoding='utf-8')\n", encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    config = {"kind": "model", "model": {"kind": "python", "entrypoint": "local_provider:complete"}}
    assert targets.collect_response(config, Case(**SAFE), 10) == "relative output"


def test_real_worker_deadline_and_redaction(monkeypatch):
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    slow = {**PYTHON, "entrypoint": "tests.test_targets_model:offline_slow"}
    start = time.monotonic()
    with pytest.raises(TimeoutError, match="deadline"):
        targets.collect_response({"kind": "model", "model": slow}, Case(**SAFE), 1)
    assert time.monotonic() - start < 5
    fail = {**PYTHON, "entrypoint": "tests.test_targets_model:offline_error"}
    with pytest.raises(ValueError) as error:
        targets.collect_response({"kind": "model", "model": fail}, Case(**SAFE), 10)
    assert "PRIVATE" not in str(error.value)


@contextmanager
def local_endpoint(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)


def test_real_http_worker_and_redirect_rejection(monkeypatch):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/canonical")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"schema_version":"1.0","response":"local real HTTP"}')

        def log_message(self, *args):
            pass

    with local_endpoint(Handler) as url:
        monkeypatch.setenv("TEST_ENDPOINT", url + "/canonical")
        config = {"kind": "http", "endpoint_env": "TEST_ENDPOINT"}
        assert targets.collect_response(config, Case(**SAFE), 10) == "local real HTTP"
        assert requests == [{"schema_version": "1.0", **SAFE}]
        monkeypatch.setenv("TEST_ENDPOINT", url + "/redirect")
        with pytest.raises(ValueError, match="Target collection failed"):
            targets.collect_response(config, Case(**SAFE), 10)
        assert len(requests) == 2


def test_collection_rejects_unknown_options_and_saved():
    for config in ({"kind": "saved"}, {"kind": "http", "endpoint_env": "URL", "options": {"x": 1}}):
        with pytest.raises(ValueError, match="configuration"):
            targets.collect_response(config, Case(**SAFE))


def test_auth_scope_forwarded(monkeypatch, remote_env):
    def post(config, body, timeout):
        assert config["azure_scope"] == "custom-scope"
        return {"choices": [{"message": {"content": "authenticated"}}]}

    monkeypatch.setattr(model, "post_json", post)
    assert model.complete({**CHAT, "azure_scope": "custom-scope"}, MESSAGES, 1) == "authenticated"
    monkeypatch.delenv("TEST_MODEL")
    with pytest.raises(ValueError):
        model.complete(CHAT, MESSAGES, 1)


def test_target_does_not_mutate_environment(monkeypatch):
    monkeypatch.setattr(targets, "run_process", lambda *a, **k: b'{"ok":true,"response":"yes"}')
    original = dict(os.environ)
    assert targets.collect_response({"kind": "model", "model": PYTHON}, Case(**SAFE)) == "yes"
    assert dict(os.environ) == original