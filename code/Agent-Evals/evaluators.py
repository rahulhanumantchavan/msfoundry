"""Bring your own callable evaluators; no model or credentials are needed here."""

import json
import re
import unicodedata

from jsonschema import Draft202012Validator

RESPONSE_SCHEMA = {
    "type": "object",
    "required": ["answer", "category", "escalate"],
    "additionalProperties": False,
    "properties": {
        "answer": {"type": "string", "minLength": 1, "pattern": r"\S"},
        "category": {
            "enum": [
                "returns", "refunds", "shipping", "damage", "account",
                "cancellation", "billing", "other",
            ]
        },
        "escalate": {"type": "boolean"},
    },
}


def normalize_phrase(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    text = "".join("-" if unicodedata.category(char) == "Pd" else char for char in text)
    return " ".join(text.split())


def parse_response(response: str):
    """Reject nonstandard JSON constants and duplicate fields as malformed output."""
    def reject_constant(value):
        raise ValueError(f"Invalid JSON constant: {value}")

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate field: {key}")
            result[key] = value
        return result

    return json.loads(response, parse_constant=reject_constant, object_pairs_hook=unique_object)


class RequiredKeywordsEvaluator:
    """Score case-insensitive, whole-phrase coverage inside the answer field only."""

    def __init__(self):
        pass

    def __call__(self, *, response: str, required_keywords: list[str], **kwargs) -> dict:
        if not isinstance(required_keywords, list) or not required_keywords or any(
            not isinstance(word, str) or not word.strip() for word in required_keywords
        ):
            raise ValueError("required_keywords must be a nonempty list of nonblank strings")
        words = list(dict.fromkeys(normalize_phrase(word) for word in required_keywords))
        try:
            body = parse_response(response)
            answer = body.get("answer", "") if isinstance(body, dict) else ""
        except (TypeError, ValueError):
            answer = ""
        if not isinstance(answer, str):
            answer = ""
        answer = normalize_phrase(answer)
        missing = [
            word for word in words
            if not re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", answer)
        ]
        score = (len(words) - len(missing)) / len(words)
        return {
            "keyword_coverage": score,
            "keyword_pass": int(not missing),
            "keyword_reason": (
                "Missing: " + ", ".join(missing) if missing else "All phrases present"
            ),
        }


class ResponseFormatEvaluator:
    """Validate strict JSON schema plus expected category and escalation behavior."""

    def __init__(self):
        self.validator = Draft202012Validator(RESPONSE_SCHEMA)

    def __call__(
        self, *, response: str, expected_category: str, expected_escalate: bool, **kwargs
    ) -> dict:
        try:
            body = parse_response(response)
        except (TypeError, ValueError):
            return {"format_valid": 0, "routing_correct": 0, "format_reason": "Invalid JSON"}
        errors = list(self.validator.iter_errors(body))
        valid = not errors
        routing = valid and (
            body["category"] == expected_category and body["escalate"] is expected_escalate
        )
        return {
            "format_valid": int(valid),
            "routing_correct": int(routing),
            "format_reason": (
                "Schema validation failed" if errors else
                "Valid format and routing" if routing else "Unexpected category or escalation"
            ),
        }


def evaluator_registry() -> tuple[dict, dict]:
    """Add your evaluator and its input-column mapping here."""
    return (
        {"keywords": RequiredKeywordsEvaluator(), "format": ResponseFormatEvaluator()},
        {
            "keywords": {"column_mapping": {
                "response": "${data.response}",
                "required_keywords": "${data.required_keywords}",
            }},
            "format": {"column_mapping": {
                "response": "${data.response}",
                "expected_category": "${data.expected_category}",
                "expected_escalate": "${data.expected_escalate}",
            }},
        },
    )