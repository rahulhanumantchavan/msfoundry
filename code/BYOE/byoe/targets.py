"""Response collection with a hard subprocess deadline and answer-blind input.

Direct Python model targets execute TRUSTED CODE ONLY. The suite runner enforces
allow_code in preflight; direct callers of collect_response assume that duty.
This process boundary is not a sandbox and inherits inference credentials.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from byoe.contracts import Case, HTTPTarget, ModelTarget, strict_json_loads, validate_target
from byoe.model import nonempty_text, validate_model, validate_timeout
from byoe.processes import run_process


def validated_target(config: dict) -> dict:
    try:
        validate_target(config, allow_code=True)
        if config["kind"] == "model":
            target = ModelTarget.model_validate(config)
            validate_model(target.model.model_dump())
        elif config["kind"] in ("http", "foundry_agent"):
            target = HTTPTarget.model_validate(config)
            if target.options:
                raise ValueError("Target options are unsupported")
        else:
            raise ValueError("Saved targets cannot collect responses")
        return target.model_dump()
    except Exception:
        raise ValueError("Invalid or unsupported collection target configuration") from None


def collect_response(config, case: Case, timeout=120) -> str:
    """Collect real output; Python entrypoints require caller-established trust."""
    deadline = time.monotonic() + validate_timeout(timeout)
    config = validated_target(config)
    try:
        case = Case.model_validate(case)
        # Never model_dump the Case: even its empty expected/response fields must
        # not cross this boundary. Context/metadata must themselves be answer-free.
        payload = {"config": config, "case": {
            "id": case.id, "query": case.query, "context": case.context,
            "metadata": case.metadata,
        }, "deadline": deadline, "cwd": str(Path.cwd())}
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        environment = dict(os.environ, PYTHONIOENCODING="utf-8")
        output = run_process(
            [sys.executable, "-m", "byoe.target_worker"], encoded, remaining,
            env=environment,
        )
        if time.monotonic() >= deadline:
            raise TimeoutError
        reply = strict_json_loads(output)
        if (type(reply) is not dict or set(reply) != {"ok", "response"}
                or reply["ok"] is not True):
            raise ValueError
        return nonempty_text(reply["response"])
    except (subprocess.TimeoutExpired, TimeoutError):
        raise TimeoutError("Target collection deadline exceeded") from None
    except Exception:
        raise ValueError("Target collection failed") from None