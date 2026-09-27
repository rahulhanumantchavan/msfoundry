"""Collect real agent responses, then run local BYOE through Azure's evaluate API."""

import argparse
import asyncio
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from jsonschema import ValidationError, validate

from agent import ROOT, support_agent
from evaluators import RESPONSE_SCHEMA, evaluator_registry

CASE_SCHEMA = {
    "type": "object",
    "required": ["id", "query", "required_keywords", "expected_category", "expected_escalate"],
    "properties": {
        "id": {"type": "string", "pattern": r"\S"},
        "query": {"type": "string", "pattern": r"\S"},
        "required_keywords": {
            "type": "array", "minItems": 1,
            "items": {"type": "string", "pattern": r"\S"},
        },
        "expected_category": RESPONSE_SCHEMA["properties"]["category"],
        "expected_escalate": {"type": "boolean"},
    },
}


def read_dataset(path: Path, *, require_response: bool = False) -> list[dict]:
    rows = []
    seen = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            validate(row, CASE_SCHEMA)
            if row["id"] in seen:
                raise ValueError("Duplicate case ID")
            if require_response and (
                not isinstance(row.get("response"), str) or not row["response"].strip()
            ):
                raise ValueError("Missing or empty response")
        except (ValueError, KeyError, TypeError, ValidationError) as exc:
            raise ValueError(f"Invalid dataset row {number} in {path}") from exc
        seen.add(row["id"])
        rows.append(row)
    if not rows:
        raise ValueError("Dataset must contain at least one case")
    return rows


async def collect(rows: list[dict], destination: Path) -> None:
    # Each run gets a new output directory; never overwrite previous responses.
    async with support_agent() as agent:
        with destination.open("x", encoding="utf-8") as output:
            for row in rows:
                # No session is reused, so test cases cannot contaminate one another.
                response = await asyncio.wait_for(agent.run(row["query"]), timeout=120)
                if not response.text:
                    raise RuntimeError(f"Empty agent response for {row['id']}")
                record = json.dumps({**row, "response": response.text}, ensure_ascii=False)
                output.write(record + "\n")
                output.flush()
                print(f"Collected {row['id']}")


def passes_gate(metrics: dict, minimum: float) -> bool:
    required = ["keywords.keyword_pass", "format.format_valid", "format.routing_correct"]
    return all(
        isinstance(metrics.get(key), (int, float))
        and math.isfinite(metrics[key])
        and metrics[key] >= minimum
        for key in required
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "dataset.jsonl")
    parser.add_argument(
        "--responses", type=Path, help="Evaluate saved responses without model calls"
    )
    parser.add_argument("--min-pass-rate", type=float, default=1.0)
    args = parser.parse_args()
    if not 0 <= args.min_pass_rate <= 1:
        parser.error("--min-pass-rate must be between 0 and 1")
    data = args.responses or args.data
    rows = read_dataset(data, require_response=bool(args.responses))
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    output_dir = ROOT / "results" / run_id
    output_dir.mkdir(parents=True)
    if not args.responses:
        data = output_dir / "responses.jsonl"
        asyncio.run(collect(rows, data))

    from azure.ai.evaluation import evaluate

    evaluators, configuration = evaluator_registry()
    result = evaluate(
        data=str(data.resolve()),
        evaluators=evaluators,
        evaluator_config=configuration,
        evaluation_name=f"support-byoe-{run_id}",
        output_path=str(output_dir / "evaluation.json"),
        fail_on_evaluator_errors=True,
        # Deliberately omit azure_ai_project: evaluation results stay local.
    )
    print(json.dumps(result["metrics"], indent=2))
    print(f"Results: {output_dir}")
    passed = passes_gate(result["metrics"], args.min_pass_rate)
    print("Quality gate: " + ("PASS" if passed else "FAIL"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())