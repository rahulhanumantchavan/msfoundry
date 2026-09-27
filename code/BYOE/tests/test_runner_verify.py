import copy
import json
import sys
import types
from pathlib import Path

import pytest

from byoe.__main__ import main
from byoe.contracts import Suite
from byoe.runner import gate_result, run_suite
from byoe.verify import verify_suite


def write_inputs(tmp_path, spec, case, **suite_overrides):
    suite = tmp_path / "suite.json"
    data = tmp_path / "data.jsonl"
    suite.write_text(json.dumps({"evaluators": [spec.model_dump()], "allow_code": True,
                                 **suite_overrides}), encoding="utf-8")
    data.write_text(json.dumps(case.model_dump()) + "\n", encoding="utf-8")
    return suite, data


def result_for(case, spec, score=1, valid=1):
    values = {"score": score, "valid": valid,
              "passed": int(score >= spec.threshold) if valid else 0}
    return {"rows": [{"inputs.id": case.id,
                      **{f"outputs.{spec.id}.{key}": value for key, value in values.items()},
                      f"outputs.{spec.id}.error_code": "" if valid else "error"}],
            "metrics": {f"{spec.id}.{key}": value for key, value in values.items()}}


def test_mocked_sdk_mapping_and_saved_no_target(tmp_path, monkeypatch, spec, case):
    import azure.ai.evaluation

    suite, data = write_inputs(tmp_path, spec, case)
    called = []

    def evaluate(**kwargs):
        called.append(kwargs)
        assert "azure_ai_project" not in kwargs
        assert "target" not in kwargs
        assert kwargs["fail_on_evaluator_errors"] is True
        assert Path.cwd().name == "BYOE"
        mapping = kwargs["evaluator_config"]["contains"]["column_mapping"]
        assert mapping == {key: f"${{data.{key}}}" for key in
                           ("id", "query", "response", "context", "expected", "metadata")}
        output = kwargs["evaluators"]["contains"](**case.model_dump())
        assert output["valid"] == output["passed"] == 1
        return result_for(case, spec)

    monkeypatch.setattr(azure.ai.evaluation, "evaluate", evaluate)
    original_cwd = Path.cwd()
    path, passed = run_suite(suite, data, tmp_path / "results")
    assert passed and path.is_file() and Path.cwd() == original_cwd
    manifest = json.loads(path.with_name("manifest.json").read_text())
    assert len(manifest["suite_sha256"]) == 64
    assert manifest["case_count"] == manifest["result_count"] == 1
    assert manifest["evaluator_ids"] == ["contains"]
    assert called


def test_collect_strips_expected_and_response(tmp_path, monkeypatch, spec, case):
    import azure.ai.evaluation

    suite, data = write_inputs(tmp_path, spec, case,
                              target={"kind": "http", "endpoint_env": "TARGET_URL"})
    calls = []

    def collect_response(config, target_case, timeout):
        calls.append(target_case)
        assert target_case.expected == {} and target_case.response is None
        assert timeout == 120
        return "A real collected response"

    monkeypatch.setitem(sys.modules, "byoe.targets",
                        types.SimpleNamespace(collect_response=collect_response))
    monkeypatch.setattr(azure.ai.evaluation, "evaluate", lambda **_: result_for(case, spec))
    path, passed = run_suite(suite, data, tmp_path / "results", collect=True)
    assert calls and passed
    saved = json.loads(path.with_name("responses.jsonl").read_text())
    assert saved["response"] == "A real collected response" and saved["expected"] == case.expected


def test_entire_dataset_preflight_before_collection(tmp_path, monkeypatch, spec, case):
    suite, data = write_inputs(tmp_path, spec, case,
                              target={"kind": "http", "endpoint_env": "TARGET_URL"})
    with data.open("a") as stream:
        stream.write('{"id":"bad","query":4}\n')
    called = []
    monkeypatch.setitem(sys.modules, "byoe.targets", types.SimpleNamespace(
        collect_response=lambda *_args, **_kwargs: called.append(True)))
    with pytest.raises(ValueError):
        run_suite(suite, data, tmp_path / "results", collect=True)
    assert not called and not (tmp_path / "results").exists()


def test_collection_exception_never_falls_back(tmp_path, monkeypatch, spec, case):
    suite, data = write_inputs(tmp_path, spec, case,
                              target={"kind": "http", "endpoint_env": "TARGET_URL"})

    def failure(*_args, **_kwargs):
        raise RuntimeError("failed real collection")

    monkeypatch.setitem(sys.modules, "byoe.targets",
                        types.SimpleNamespace(collect_response=failure))
    with pytest.raises(RuntimeError):
        run_suite(suite, data, tmp_path / "results", collect=True)
    assert next((tmp_path / "results").glob("*/responses.jsonl")).read_text() == ""


@pytest.mark.parametrize("mutation", [
    "rows", "id", "metric", "nan", "bool", "invalid", "error", "inconsistent",
])
def test_gate_fail_closed(spec, case, mutation):
    result = result_for(case, spec)
    if mutation == "rows":
        result["rows"] = []
    elif mutation == "id":
        result["rows"][0]["inputs.id"] = "other"
    elif mutation == "metric":
        del result["metrics"]["contains.score"]
    elif mutation == "nan":
        result["metrics"]["contains.score"] = float("nan")
    elif mutation == "bool":
        result["metrics"]["contains.valid"] = True
    elif mutation == "invalid":
        result = result_for(case, spec, valid=0)
    elif mutation == "error":
        result["rows"][0]["outputs.contains.error_code"] = "error"
    else:
        result["rows"][0]["outputs.contains.score"] = 0
    assert not gate_result(result, Suite(evaluators=[spec]), [case.id])


def test_optional_low_score_allowed_but_invalid_blocks(spec, case):
    optional = spec.model_copy(update={"id": "optional", "required": False})
    suite = Suite(evaluators=[spec, optional])
    result = result_for(case, spec)
    extra = result_for(case, optional, score=0)
    result["rows"][0].update(extra["rows"][0])
    result["metrics"].update(extra["metrics"])
    assert gate_result(result, suite, [case.id])
    result["rows"][0]["outputs.optional.valid"] = 0
    result["metrics"]["optional.valid"] = 0
    assert not gate_result(result, suite, [case.id])


def fixture_file(tmp_path, case, fail=True):
    fixtures = [{"evaluator_id": "contains", "case": case.model_dump(),
                 "expect_valid": True, "expect_pass": True}]
    if fail:
        other = copy.deepcopy(fixtures[0])
        other["case"]["id"] = "fail"
        other["case"]["response"] = "not found"
        other["expect_pass"] = False
        fixtures.append(other)
    path = tmp_path / "fixtures.jsonl"
    path.write_text("\n".join(json.dumps(item) for item in fixtures), encoding="utf-8")
    return path


def test_verification_pass_fail_coverage(tmp_path, spec, case):
    suite, _ = write_inputs(tmp_path, spec, case)
    fixtures = fixture_file(tmp_path, case)
    path, passed = verify_suite(suite, fixtures, tmp_path / "results")
    assert passed and path.is_file()
    assert main(["verify", "--suite", str(suite), "--fixtures", str(fixtures),
                 "--output", str(tmp_path / "results")]) == 0


def test_verification_missing_coverage(tmp_path, spec, case):
    suite, _ = write_inputs(tmp_path, spec, case)
    fixtures = fixture_file(tmp_path, case, fail=False)
    _, passed = verify_suite(suite, fixtures, tmp_path / "results")
    assert not passed
    assert main(["verify", "--suite", str(suite), "--fixtures", str(fixtures),
                 "--output", str(tmp_path / "results")]) == 1


def test_verification_unknown_id_preflight(tmp_path, monkeypatch, spec, case):
    suite, _ = write_inputs(tmp_path, spec, case)
    path = fixture_file(tmp_path, case)
    path.write_text(path.read_text().replace('"contains", "case"', '"unknown", "case"'))
    calls = []
    monkeypatch.setattr("byoe.verify.execute", lambda *_: calls.append(1))
    with pytest.raises(ValueError):
        verify_suite(suite, path, tmp_path / "results")
    assert not calls


def test_expected_invalid_fixture_is_extra_not_coverage(tmp_path, spec, case):
    suite, _ = write_inputs(tmp_path, spec, case)
    path = fixture_file(tmp_path, case)
    invalid_case = case.model_dump()
    invalid_case["expected"] = {}
    with path.open("a") as stream:
        stream.write("\n" + json.dumps({"evaluator_id": "contains", "case": invalid_case,
                                         "expect_valid": False, "expect_pass": False}))
    assert verify_suite(suite, path, tmp_path / "results")[1]


def test_cli_runtime_errors_are_redacted(tmp_path, capsys):
    assert main(["evaluate", "--suite", str(tmp_path / "secret-key.json"),
                 "--data", str(tmp_path / "missing.jsonl")]) == 2
    assert "secret-key" not in capsys.readouterr().err


@pytest.mark.parametrize("patch", [
    {"score": float("nan")}, {"valid": True}, {"error_code": "error"},
    {"score": 0, "passed": 1},
])
def test_verification_rejects_inconsistent_outputs(tmp_path, monkeypatch, spec, case, patch):
    suite, _ = write_inputs(tmp_path, spec, case)
    fixtures = fixture_file(tmp_path, case)

    def fake_execute(_spec, fixture_case, _allow_code):
        passed = int(fixture_case.id == "one")
        result = {"score": passed, "valid": 1, "passed": passed,
                  "reason": "test", "error_code": ""}
        if passed:
            result.update(patch)
        return result

    monkeypatch.setattr("byoe.verify.execute", fake_execute)
    assert not verify_suite(suite, fixtures, tmp_path / "results")[1]


def test_verification_wrong_known_answer(tmp_path, spec, case):
    suite, _ = write_inputs(tmp_path, spec, case)
    fixtures = fixture_file(tmp_path, case)
    fixtures.write_text(fixtures.read_text().replace('"expect_pass": false',
                                                    '"expect_pass": true'))
    assert not verify_suite(suite, fixtures, tmp_path / "results")[1]


def test_actual_small_sdk_integration(tmp_path, spec, case):
    """Real azure.ai.evaluation.evaluate with a real isolated Python plugin, offline."""
    pytest.importorskip("azure.ai.evaluation")
    suite, data = write_inputs(tmp_path, spec, case)
    path, passed = run_suite(suite, data, tmp_path / "results")
    assert passed, path.with_name("evaluation.json").read_text()
    assert path.with_name("evaluation.json").is_file()