"""One isolated worker per evaluator invocation, with fail-closed SDK outputs."""

import json
import os
import re
import subprocess
import sys
import time

from byoe.contracts import Case, EvalResult, EvaluatorSpec, strict_json_loads, validate_evaluator
from byoe.processes import OutputLimitError, run_process


def sanitized_reason(reason: str) -> str:
    # Mask credential-like environment values and common inline credential formats.
    for name, value in os.environ.items():
        if value and re.search(r"TOKEN|SECRET|PASSWORD|API_?KEY|CREDENTIAL", name, re.I):
            reason = reason.replace(value, "[REDACTED]")
    reason = re.sub(r"(?i)\bBearer\s+\S+", "Bearer [REDACTED]", reason)
    reason = re.sub(r"(?i)\b(api[_-]?key|token|password|secret)\s*[:=]\s*\S+",
                    r"\1=[REDACTED]", reason)
    return "".join(c for c in reason if c.isprintable() or c in "\n\t")[:2048]


def invalid_result(code: str) -> dict:
    return {"score": 0, "passed": 0, "valid": 0,
            "reason": "Evaluator did not return a valid result.", "error_code": code}


def execute(spec: EvaluatorSpec, case: Case, allow_code: bool = False) -> dict:
    try:
        validate_evaluator(spec, allow_code)
    except (ValueError, TypeError):
        return invalid_result("configuration_error")
    try:
        payload = json.dumps({"spec": spec.model_dump(), "case": case.model_dump(),
                              "allow_code": allow_code,
                              "deadline": time.monotonic() + float(spec.timeout_seconds)},
                             allow_nan=False).encode("utf-8")
        raw = run_process([sys.executable, "-m", "byoe.worker"], payload,
                          float(spec.timeout_seconds))
        reply = strict_json_loads(raw)
        if type(reply) is not dict or set(reply) != {"ok", "result"} or reply["ok"] is not True:
            return invalid_result("invalid_result")
        result = EvalResult.model_validate(reply["result"])
        return {"score": result.score, "passed": int(result.score >= spec.threshold),
                "valid": 1, "reason": sanitized_reason(result.reason), "error_code": ""}
    except subprocess.TimeoutExpired:
        return invalid_result("timeout")
    except OutputLimitError:
        return invalid_result("output_limit")
    except Exception:
        # Do not expose exception messages, URLs, headers, stderr or credentials.
        return invalid_result("execution_error")