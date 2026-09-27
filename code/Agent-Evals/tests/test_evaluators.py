import json
import math

import pytest

from evaluate_agent import passes_gate, read_dataset
from evaluators import RequiredKeywordsEvaluator, ResponseFormatEvaluator


def response(answer="Return within 30 days with proof of purchase.", **changes):
    return json.dumps({"answer": answer, "category": "returns", "escalate": False, **changes})


def test_keyword_coverage():
    result = RequiredKeywordsEvaluator()(
        response=response(), required_keywords=["30 DAYS", "proof of purchase"]
    )
    assert result["keyword_coverage"] == 1
    assert result["keyword_pass"] == 1


def test_partial_keywords():
    result = RequiredKeywordsEvaluator()(
        response=response(), required_keywords=["30 days", "portal"]
    )
    assert result["keyword_coverage"] == 0.5
    assert result["keyword_pass"] == 0


def test_unicode_hyphens_are_typographic_equivalents():
    result = RequiredKeywordsEvaluator()(
        response=response("Use the sign‑in page."), required_keywords=["sign-in"]
    )
    assert result["keyword_pass"] == 1


def test_keywords_do_not_match_substrings_or_other_fields():
    result = RequiredKeywordsEvaluator()(
        response=response("Return within 130 days."), required_keywords=["30 days", "returns"]
    )
    assert result["keyword_coverage"] == 0


@pytest.mark.parametrize("keywords", [[], "word", [""], [2]])
def test_invalid_keyword_config(keywords):
    with pytest.raises(ValueError):
        RequiredKeywordsEvaluator()(response=response(), required_keywords=keywords)


@pytest.mark.parametrize("text", ["not json", "[]", "null", '{"answer": 42}'])
def test_malformed_response_fails_keywords(text):
    assert RequiredKeywordsEvaluator()(response=text, required_keywords=["30 days"])[
        "keyword_pass"
    ] == 0


def test_format_and_routing():
    result = ResponseFormatEvaluator()(
        response=response(), expected_category="returns", expected_escalate=False
    )
    assert result["format_valid"] == result["routing_correct"] == 1


@pytest.mark.parametrize("text", [
    "not json", "[]", "null", "```json\n{}\n```", "{}",
    response(escalate="false"), response(category="invalid"), response(answer="   "),
    response(extra="unexpected"), '{"answer":NaN}', '{"answer":"a","answer":"b"}',
])
def test_invalid_format(text):
    result = ResponseFormatEvaluator()(
        response=text, expected_category="returns", expected_escalate=False
    )
    assert result["format_valid"] == result["routing_correct"] == 0


def test_wrong_routing():
    result = ResponseFormatEvaluator()(
        response=response(escalate=True), expected_category="returns", expected_escalate=False
    )
    assert result["format_valid"] == 1
    assert result["routing_correct"] == 0


@pytest.mark.parametrize("value", [0.9, None, math.nan, math.inf])
def test_gate_fails_closed(value):
    assert not passes_gate({
        "keywords.keyword_pass": value,
        "format.format_valid": 1,
        "format.routing_correct": 1,
    }, 1)


def test_gate_passes():
    assert passes_gate({
        "keywords.keyword_pass": 1,
        "format.format_valid": 1,
        "format.routing_correct": 1,
    }, 1)


def test_empty_dataset_rejected(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="at least one"):
        read_dataset(path)


def test_sample_dataset():
    from agent import ROOT
    assert len(read_dataset(ROOT / "dataset.jsonl")) == 8