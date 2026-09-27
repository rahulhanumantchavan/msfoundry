"""Pure example evaluators. Keyword checks are not factual/safety assessments."""


def contains_expected(case: dict, options: dict) -> dict:
    expected = case["expected"].get("contains", [])
    if isinstance(expected, str):
        expected = [expected]
    if not isinstance(expected, list) or not expected or any(
        not isinstance(term, str) or not term for term in expected
    ):
        raise ValueError("expected.contains requires nonempty strings")
    response = case.get("response")
    if not isinstance(response, str):
        raise ValueError("Response required")
    if not options.get("case_sensitive", False):
        response = response.casefold()
        expected = [term.casefold() for term in expected]
    matched = all(term in response for term in expected)
    return {"score": int(matched), "reason": "All terms found." if matched else "Missing terms."}


def exact_match(case: dict, options: dict) -> dict:
    expected = case["expected"]["response"]
    if not isinstance(expected, str):
        raise ValueError("expected.response must be a string")
    matched = case.get("response") == expected
    return {"score": int(matched), "reason": "Exact match." if matched else "Not an exact match."}