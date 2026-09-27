"""Private answer-blind worker. Invoke through targets.collect_response only."""

import contextlib
import json
import os
import sys
import time

from byoe.contracts import Case, strict_json_loads
from byoe.model import complete, nonempty_text, responses_text, validate_timeout
from byoe.targets import validated_target
from byoe.transport import post_json


def invoke_target(config: dict, safe_case: dict, timeout: float) -> str:
    config = validated_target(config)
    if type(safe_case) is not dict or set(safe_case) != {"id", "query", "context", "metadata"}:
        raise ValueError("Invalid target input fields")
    case = Case.model_validate(safe_case)
    timeout = validate_timeout(timeout)
    if config["kind"] == "model":
        messages = []
        if config["instructions"]:
            messages.append({"role": "system", "content": config["instructions"]})
        messages.append({"role": "user", "content": json.dumps(
            {"query": case.query, "context": case.context, "metadata": case.metadata},
            ensure_ascii=False, allow_nan=False,
        )})
        return complete(config["model"], messages, timeout)

    transport_config = {key: config[key] for key in
                        ("endpoint_env", "token_env", "azure_scope", "options")}
    if config["kind"] == "http":
        result = post_json(transport_config, {"schema_version": "1.0", **safe_case}, timeout)
        if (type(result) is not dict or set(result) != {"schema_version", "response"}
                or result["schema_version"] != "1.0"):
            raise ValueError("Invalid canonical target response")
        return nonempty_text(result["response"])

    # endpoint_env must already hold the full discovered deployment Responses URL.
    # No URL synthesis, conversation creation, or remote agent management.
    text = case.query + "\n\nContext (JSON):\n" + json.dumps(
        case.context, ensure_ascii=False, allow_nan=False,
    )
    result = post_json(transport_config, {"input": text, "stream": False, "store": False}, timeout)
    return responses_text(result, require_status=True)


def main() -> int:
    try:
        payload = strict_json_loads(sys.stdin.buffer.read())
        with contextlib.redirect_stdout(sys.stderr):
            # run_process starts in the package root so -m resolves reliably;
            # restore the caller's directory for trusted plugin-relative paths.
            os.chdir(payload["cwd"])
            sys.path.insert(0, payload["cwd"])
            remaining = payload["deadline"] - time.monotonic()
            response = invoke_target(payload["config"], payload["case"], remaining)
        reply = {"ok": True, "response": response}
    except BaseException:
        reply = {"ok": False, "response": None}
    sys.stdout.write(json.dumps(reply, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())