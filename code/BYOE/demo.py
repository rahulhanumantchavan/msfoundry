"""Explicit offline protocol demo using synthetic saved responses and a mock judge.

Run with the root .venv Python from any working directory. No model is invoked.
The real-provider example configurations are deliberately never used here.
"""

import os
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from byoe.runner import run_suite
from byoe.verify import verify_suite
from examples.mock_services import MockHandler

ROOT = Path(__file__).resolve().parent
BANNER = "EXPLICIT OFFLINE PROTOCOL DEMO—not real model/Foundry responses"


@contextmanager
def offline_environment(port: int):
    """Temporarily override endpoints and disable SDK telemetry before SDK import."""
    overrides = {
        "BYOE_EVALUATOR_URL": f"http://127.0.0.1:{port}/evaluate",
        "BYOE_JUDGE_URL": f"http://127.0.0.1:{port}/chat/completions",
        "BYOE_JUDGE_MODEL": "explicit-offline-mock",
        "PF_DISABLE_TELEMETRY": "true",
        "AZURE_AI_EVALUATION_DISABLE_TELEMETRY": "true",
        "OTEL_SDK_DISABLED": "true",
        "AZURE_TRACING_ENABLED": "false",
        "APPLICATIONINSIGHTS_CONNECTION_STRING": None,
        "APPINSIGHTS_INSTRUMENTATIONKEY": None,
        "AZURE_AI_PROJECT_ENDPOINT": None,
        "AZURE_AI_EVALUATION_PROJECT": None,
    }
    previous = {key: os.environ.get(key) for key in overrides}
    try:
        for key, value in overrides.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def main() -> int:
    print(BANNER, flush=True)
    print("Synthetic fixtures + deterministic contains mock; not real judge validation.",
          flush=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), MockHandler)
    server.daemon_threads = True
    thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
    started = False
    try:
        thread.start()
        started = True
        with offline_environment(server.server_port):
            suite = ROOT / "configs" / "suite.all-adapters.json"
            output = ROOT / "results"
            verification, verified = verify_suite(
                suite, ROOT / "data" / "fixtures.all-adapters.jsonl", output,
            )
            print(f"Fixture verification: {'PASS' if verified else 'FAIL'} — {verification}",
                  flush=True)
            report, passed = run_suite(suite, ROOT / "data" / "responses.jsonl", output)
            print(f"All-adapter evaluation: {'PASS' if passed else 'FAIL'} — {report}", flush=True)
            return 0 if verified and passed else 1
    except Exception:
        # Do not expose SDK exception text, endpoint values, or environment secrets.
        print("Offline protocol demo failed; no real-provider fallback was attempted.", flush=True)
        return 1
    finally:
        if started:
            server.shutdown()
        server.server_close()
        if started:
            thread.join(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())