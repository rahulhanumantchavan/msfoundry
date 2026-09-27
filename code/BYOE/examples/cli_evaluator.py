"""Example JSON stdin/stdout evaluator; run with the explicitly trusted CLI adapter."""

import json
import sys

from byoe.contracts import Case, EvalResult, strict_json_loads
from examples.plugins import contains_expected


def main() -> int:
    envelope = strict_json_loads(sys.stdin.buffer.read())
    if type(envelope) is not dict or set(envelope) != {"case", "options"}:
        raise ValueError("Invalid envelope")
    case = Case.model_validate(envelope["case"])
    if type(envelope["options"]) is not dict:
        raise ValueError("Invalid options")
    result = EvalResult.model_validate(contains_expected(case.model_dump(), envelope["options"]))
    print(json.dumps(result.model_dump(), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())