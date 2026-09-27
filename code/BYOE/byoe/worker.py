"""Private worker protocol. Plugin stdout is diagnostic-only and never a result."""

import contextlib
import json
import sys
import time

from byoe.contracts import Case, EvaluatorSpec, strict_json_loads, validate_evaluator


def main() -> int:
    try:
        payload = strict_json_loads(sys.stdin.buffer.read())
        spec = EvaluatorSpec.model_validate(payload["spec"])
        case = Case.model_validate(payload["case"])
        validate_evaluator(spec, payload.get("allow_code") is True)
        with contextlib.redirect_stdout(sys.stderr):
            from byoe.adapters import invoke_evaluator

            remaining = payload["deadline"] - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Worker deadline elapsed")
            # CLI's inner timeout is based on the remaining budget, not the original
            # budget, leaving time to kill and reap its immediate subprocess.
            spec = spec.model_copy(update={"timeout_seconds": remaining})
            result = invoke_evaluator(spec, case)
        reply = {"ok": True, "result": result.model_dump()}
    except BaseException:
        reply = {"ok": False, "result": None}
    sys.stdout.write(json.dumps(reply, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())