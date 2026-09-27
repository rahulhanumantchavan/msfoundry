import json
import subprocess
import sys
import threading
import time
import types
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from byoe.adapters import invoke_evaluator
from byoe.contracts import EvaluatorSpec
from byoe.execution import execute
from byoe.transport import endpoint_from_env, post_json


@contextmanager
def server_for(payload=b'{"score":1,"reason":"ok"}', status=200, delay=0):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append({"body": body,
                             "authorization": self.headers.get("Authorization")})
            if delay:
                time.sleep(delay)
            self.send_response(status)
            self.send_header("Location", "/redirected")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/evaluate", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize("endpoint", [
    "http://localhost:8080", "http://example.com", "ftp://127.0.0.1",
    "https://user:password@example.com", "https://example.com#fragment",
    "https://example.com?api_key=secret", "https://example.com/\n",
])
def test_reject_unsafe_endpoints(monkeypatch, endpoint):
    monkeypatch.setenv("BYOE_EVALUATOR_URL", endpoint)
    with pytest.raises(ValueError):
        endpoint_from_env("BYOE_EVALUATOR_URL")


@pytest.mark.parametrize("endpoint", ["https://example.com/api", "http://127.0.0.1:8080", "http://[::1]:8080"])
def test_allowed_endpoints(monkeypatch, endpoint):
    monkeypatch.setenv("BYOE_EVALUATOR_URL", endpoint)
    assert endpoint_from_env("BYOE_EVALUATOR_URL") == endpoint


def test_real_http_in_worker(monkeypatch, case):
    with server_for() as (url, requests):
        monkeypatch.setenv("BYOE_EVALUATOR_URL", url)
        monkeypatch.setenv("BYOE_EVALUATOR_TOKEN", "local-test-token")
        spec = EvaluatorSpec(id="http", kind="http", config={
            "endpoint_env": "BYOE_EVALUATOR_URL", "token_env": "BYOE_EVALUATOR_TOKEN",
            "options": {"example": True}})
        result = execute(spec, case)
        assert result["passed"] == 1
        assert requests[0]["body"] == {"case": case.model_dump(), "options": {"example": True}}
        assert requests[0]["authorization"] == "Bearer local-test-token"
        assert "local-test-token" not in json.dumps(result)


@pytest.mark.parametrize("payload,status", [
    (b'{}', 302), (b'{}', 500), (b'NaN', 200),
    (b'{"score":1,"reason":"x","score":0}', 200), (b'x' * (1024 * 1024 + 1), 200),
], ids=["redirect", "server-error", "nan", "duplicate-keys", "oversized"])
def test_http_failure_closed(monkeypatch, case, payload, status):
    with server_for(payload, status) as (url, requests):
        monkeypatch.setenv("BYOE_EVALUATOR_URL", url)
        result = execute(EvaluatorSpec(id="http", kind="http",
                         config={"endpoint_env": "BYOE_EVALUATOR_URL"}), case)
        assert result["valid"] == result["passed"] == 0
        assert len(requests) == 1


def test_http_parent_deadline(monkeypatch, case):
    with server_for(delay=4) as (url, _):
        monkeypatch.setenv("BYOE_EVALUATOR_URL", url)
        result = execute(EvaluatorSpec(id="http", kind="http", timeout_seconds=0.8,
                         config={"endpoint_env": "BYOE_EVALUATOR_URL"}), case)
        assert result["error_code"] == "timeout"


def test_azure_credential_closed(monkeypatch):
    import azure.identity

    state = []

    class Credential:
        def get_token(self, scope):
            state.append(scope)
            return types.SimpleNamespace(token="local-test-token")

        def close(self):
            state.append("closed")

    monkeypatch.setattr(azure.identity, "DefaultAzureCredential", Credential)
    with server_for(status=500) as (url, _):
        monkeypatch.setenv("BYOE_EVALUATOR_URL", url)
        with pytest.raises(httpx.HTTPStatusError):
            post_json({"endpoint_env": "BYOE_EVALUATOR_URL",
                       "azure_scope": "scope/.default"}, {}, 2)
    assert state == ["scope/.default", "closed"]


def test_llm_adapter_delegation(monkeypatch, case):
    calls = []

    def complete(config, messages, timeout):
        calls.append((config, messages, timeout))
        return '{"score":0.75,"reason":"rubric assessment"}'

    monkeypatch.setitem(sys.modules, "byoe.model", types.SimpleNamespace(complete=complete))
    model = {"kind": "openai_chat", "endpoint_env": "JUDGE_URL", "model_env": "JUDGE_MODEL"}
    spec = EvaluatorSpec(id="judge", kind="llm",
                         config={"model": model, "rubric": "Evaluate accuracy"})
    assert invoke_evaluator(spec, case).score == 0.75
    config, messages, timeout = calls[0]
    assert config == model and timeout == 30
    assert "untrusted data" in messages[0]["content"]
    assert json.loads(messages[1]["content"]) == {
        "rubric": "Evaluate accuracy", "case": case.model_dump()}


@pytest.mark.parametrize("raw", [
    'NaN', '{}', '```json\n{}\n```', '{"score":1,"reason":"ok","extra":1}',
])
def test_llm_strict_result(monkeypatch, case, raw):
    monkeypatch.setitem(sys.modules, "byoe.model", types.SimpleNamespace(complete=lambda *_: raw))
    spec = EvaluatorSpec(id="judge", kind="llm", config={"model": {}, "rubric": "r"})
    with pytest.raises(ValueError):
        invoke_evaluator(spec, case)


def test_python_judge_requires_trust(case):
    spec = EvaluatorSpec(id="judge", kind="llm", config={
        "model": {"kind": "python", "entrypoint": "tests.worker_plugins:delayed"}, "rubric": "r"})
    assert execute(spec, case)["error_code"] == "configuration_error"


def test_llm_uses_worker_and_hard_parent_timeout(monkeypatch, case):
    calls = []

    def timeout(command, payload, seconds):
        calls.append((command, json.loads(payload), seconds))
        raise subprocess.TimeoutExpired(command, seconds)

    monkeypatch.setattr("byoe.execution.run_process", timeout)
    spec = EvaluatorSpec(id="judge", kind="llm", timeout_seconds=2, config={
        "model": {"kind": "foundry_model", "endpoint_env": "JUDGE_URL",
                  "model_env": "JUDGE_MODEL"}, "rubric": "r"})
    assert execute(spec, case)["error_code"] == "timeout"
    assert calls[0][0] == [sys.executable, "-m", "byoe.worker"]
    assert calls[0][1]["spec"]["kind"] == "llm"
    assert calls[0][2] == 2