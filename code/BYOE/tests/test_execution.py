import json
import os
import time

import pytest

from byoe.adapters import minimal_environment
from byoe.contracts import EvaluatorSpec
from byoe.execution import execute


def plugin(name, *, options=None, timeout=10):
    return EvaluatorSpec(id="test", kind="python", timeout_seconds=timeout,
                         config={"entrypoint": f"tests.worker_plugins:{name}",
                                 "options": options or {}})


def test_real_python_and_code_opt_in(case, spec):
    assert execute(spec, case)["valid"] == 0
    result = execute(spec, case, True)
    assert result == {"score": 1, "passed": 1, "valid": 1,
                      "reason": "All terms found.", "error_code": ""}
    result = execute(spec, case.model_copy(update={"response": "no match"}), True)
    assert (result["valid"], result["passed"]) == (1, 0)


def test_real_cli(case):
    spec = EvaluatorSpec(id="cli", kind="cli", config={
        "command": ["{python}", "-m", "examples.cli_evaluator"], "env_allowlist": []})
    assert execute(spec, case, True)["passed"] == 1


@pytest.mark.parametrize("result", [
    {}, {"score": 1}, {"score": True, "reason": "bad"},
    {"score": 1.1, "reason": "bad"}, {"score": "1", "reason": "bad"},
    {"score": 1, "reason": "ok", "extra": 1}, {"score": 1, "reason": "x" * 2049},
])
def test_invalid_plugin_contracts(case, result):
    output = execute(plugin("malformed", options={"result": result}), case, True)
    assert (output["valid"], output["passed"], output["score"]) == (0, 0, 0)


@pytest.mark.parametrize("name", ["nonfinite", "throwing", "huge"])
def test_invalid_plugin_output(case, name):
    output = execute(plugin(name), case, True)
    assert output["valid"] == output["passed"] == 0
    assert "SECRET" not in json.dumps(output)


def test_hard_timeout(case):
    start = time.monotonic()
    output = execute(plugin("delayed", timeout=0.6), case, True)
    assert output["error_code"] == "timeout"
    assert time.monotonic() - start < 3


def test_noisy_stdout_is_bounded_and_separate(case):
    assert execute(plugin("noisy"), case, True)["passed"] == 1


def test_secret_redaction(case, monkeypatch):
    monkeypatch.setenv("BYOE_TEST_TOKEN", "unique-secret-value")
    result = execute(plugin("secret_reason"), case, True)
    assert result["reason"] == "[REDACTED]"
    assert "metadata" not in result


def test_cli_minimal_environment(monkeypatch, case):
    monkeypatch.setenv("BYOE_TEST_TOKEN", "never-inherited")
    env = minimal_environment([])
    assert "BYOE_TEST_TOKEN" not in env
    assert "PYTHONPATH" not in env
    assert minimal_environment(["BYOE_TEST_TOKEN"])["BYOE_TEST_TOKEN"] == "never-inherited"
    code = ("import sys,json,os; body=json.load(sys.stdin); "
            "print(json.dumps({'score':int('BYOE_TEST_TOKEN' not in os.environ "
            "and body['case']['query']=='A question'), 'reason':'checked'}))")
    spec = EvaluatorSpec(id="cli", kind="cli", config={"command": ["{python}", "-c", code]})
    assert execute(spec, case, True)["passed"] == 1


@pytest.mark.parametrize("text", ['NaN', '{}', '{"score":1,"reason":"x","score":0}', 'not json'])
def test_cli_bad_stdout(text, case):
    spec = EvaluatorSpec(id="cli", kind="cli", config={
        "command": ["{python}", "-c", f"print({text!r})"]})
    assert execute(spec, case, True)["valid"] == 0


def test_cli_inner_timeout(case):
    spec = EvaluatorSpec(id="cli", kind="cli", timeout_seconds=3, config={
        "command": ["{python}", "-c", "import time; time.sleep(20)"]})
    start = time.monotonic()
    result = execute(spec, case, True)
    assert result["valid"] == 0
    assert time.monotonic() - start < 5


def test_cwd_independence(tmp_path, monkeypatch, spec, case):
    monkeypatch.chdir(tmp_path)
    assert execute(spec, case, True)["passed"] == 1
    assert os.getcwd() == str(tmp_path)