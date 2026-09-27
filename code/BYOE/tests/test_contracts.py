import pytest
from pydantic import ValidationError

from byoe.contracts import Case, EvalResult, EvaluatorSpec, Suite, preflight, strict_json_loads
from byoe.runner import load_dataset


@pytest.mark.parametrize("raw", [
    '{"x":1,"x":2}', '{"a":{"x":1,"x":2}}', '{"score":NaN}',
    '{"score":Infinity}', '{"score":-Infinity}', '{"score":1e999}',
])
def test_strict_json(raw):
    with pytest.raises(ValueError):
        strict_json_loads(raw)


@pytest.mark.parametrize("score", [True, False, "1", None, float("nan"), float("inf"), -0.1, 1.1])
def test_reject_scores(score):
    with pytest.raises(ValidationError):
        EvalResult(score=score, reason="bad")


@pytest.mark.parametrize("patch", [
    {"id": " "}, {"query": "\n"}, {"query": 1}, {"response": 3},
    {"metadata": []}, {"expected": None}, {"unknown": 1}, {"schema_version": "2.0"},
])
def test_case_strict(patch):
    with pytest.raises(ValidationError):
        Case.model_validate({"id": "one", "query": "question", **patch})


@pytest.mark.parametrize("patch", [
    {"threshold": True}, {"threshold": "1"}, {"timeout_seconds": False},
    {"timeout_seconds": 0}, {"timeout_seconds": 301}, {"timeout_seconds": float("inf")},
    {"required": 1}, {"id": "Bad-ID"}, {"unknown": 1}, {"kind": "unknown"},
])
def test_spec_strict(spec, patch):
    with pytest.raises(ValidationError):
        EvaluatorSpec.model_validate({**spec.model_dump(), **patch})


def test_result_missing_extra_and_long_reason():
    for data in ({"score": 1}, {"reason": "missing"},
                 {"score": 1, "reason": "a" * 2049},
                 {"score": 1, "reason": "ok", "unknown": 1}):
        with pytest.raises(ValidationError):
            EvalResult.model_validate(data)


def test_suite_uniqueness_and_required(spec):
    for values in ([], [spec, spec], [spec.model_copy(update={"required": False})]):
        with pytest.raises(ValidationError):
            Suite(evaluators=values)
    for patch in ({"min_pass_rate": True}, {"min_pass_rate": float("nan")},
                  {"allow_code": 1}, {"extra": 1}):
        with pytest.raises(ValidationError):
            Suite.model_validate({"evaluators": [spec.model_dump()], **patch})


def test_preflight_never_imports_plugins(spec):
    spec.config["entrypoint"] = "does_not_exist:plugin"
    preflight(Suite(evaluators=[spec], allow_code=True))
    with pytest.raises(ValueError):
        preflight(Suite(evaluators=[spec]))
    spec.config["secret"] = "inline-not-allowed"
    with pytest.raises(ValueError):
        preflight(Suite(evaluators=[spec], allow_code=True))


def test_mutable_defaults_are_independent():
    first = Case(id="a", query="a")
    first.context["x"] = 1
    assert Case(id="b", query="b").context == {}


@pytest.mark.parametrize("text", ["", "\n", '{"id":"a","query":"q"}\n',
    '{"id":"a","query":"q","response":""}\n' * 2])
def test_invalid_dataset(tmp_path, text):
    path = tmp_path / "data.jsonl"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        load_dataset(path)