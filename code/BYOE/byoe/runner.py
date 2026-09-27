"""SDK-backed evaluation. Public API: run_suite(...) -> tuple[Path, bool].

The tuple is (report_path, gate_passed). Configuration/runtime failures raise;
the CLI maps these to exit 2. Gate failures return False (CLI exit 1).
This synchronous runner temporarily changes cwd for SDK subprocess imports;
do not invoke it concurrently inside a multithreaded host.
"""

import hashlib
import importlib.metadata
import json
import math
import os
import platform
import sys
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from byoe import __version__
from byoe.contracts import Case, EvaluatorSpec, Suite, preflight, strict_json_loads
from byoe.execution import execute
from byoe.processes import ROOT


def load_suite(path: Path) -> Suite:
    suite = Suite.model_validate(strict_json_loads(path.read_bytes()))
    preflight(suite)
    return suite


def load_dataset(path: Path, *, require_response: bool = True) -> list[Case]:
    cases = [Case.model_validate(strict_json_loads(line))
             for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not cases:
        raise ValueError("Dataset cannot be empty")
    ids = [case.id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate case ID")
    if require_response and any(case.response is None for case in cases):
        raise ValueError("Saved mode requires every response")
    return cases


class SDKEvaluator:
    """Explicit signature and mappings preserve structured case fields in the SDK."""

    def __init__(self, spec: EvaluatorSpec, allow_code: bool):
        self.spec = spec
        self.allow_code = allow_code

    def __call__(self, *, id, query, response, context, expected, metadata, **kwargs):
        case = Case(id=id, query=query, response=response, context=context,
                    expected=expected, metadata=metadata)
        return execute(self.spec, case, self.allow_code)


@contextmanager
def sdk_working_directory():
    previous = Path.cwd()
    previous_path = sys.path[:]
    try:
        os.chdir(ROOT)
        sys.path.insert(0, str(ROOT))
        yield
    finally:
        os.chdir(previous)
        sys.path[:] = previous_path


def unit_number(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1


def gate_result(result: dict, suite: Suite, case_ids: list[str]) -> bool:
    """Check rows AND aggregates; missing rows, invalid metrics and errors fail."""
    if type(result) is not dict:
        return False
    rows, metrics = result.get("rows"), result.get("metrics")
    if type(rows) is not list or len(rows) != len(case_ids) or type(metrics) is not dict:
        return False
    if any(type(row) is not dict for row in rows):
        return False
    ids = [row.get("inputs.id") for row in rows]
    if any(type(value) is not str for value in ids) or sorted(ids) != sorted(case_ids):
        return False
    for spec in suite.evaluators:
        for metric in ("score", "passed", "valid"):
            aggregate = metrics.get(f"{spec.id}.{metric}")
            values = [row.get(f"outputs.{spec.id}.{metric}") for row in rows]
            if not unit_number(aggregate) or not all(unit_number(value) for value in values):
                return False
            if metric in {"passed", "valid"} and any(value not in (0, 1) for value in values):
                return False
            if not math.isclose(aggregate, sum(values) / len(values), abs_tol=1e-9):
                return False
            if metric == "valid" and (aggregate != 1 or any(value != 1 for value in values)):
                return False
            if metric == "passed" and spec.required and aggregate < suite.min_pass_rate:
                return False
        for row in rows:
            if row.get(f"outputs.{spec.id}.error_code") != "":
                return False
            score = row[f"outputs.{spec.id}.score"]
            if row[f"outputs.{spec.id}.passed"] != int(score >= spec.threshold):
                return False
    return True


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False),
                    encoding="utf-8")


def new_output_dir(root: Path) -> Path:
    directory = root.resolve() / uuid4().hex
    directory.mkdir(parents=True, exist_ok=False)
    return directory


def run_suite(suite_path: Path, data_path: Path, output_root: Path,
              collect: bool = False) -> tuple[Path, bool]:
    suite_path, data_path = suite_path.resolve(), data_path.resolve()
    # Complete dataset and configuration checks BEFORE importing/calling a target.
    suite = load_suite(suite_path)
    cases = load_dataset(data_path, require_response=not collect)
    if collect and suite.target.get("kind") == "saved":
        raise ValueError("Collection requires an explicit non-saved target")
    hashes = {"suite_sha256": hashlib.sha256(suite_path.read_bytes()).hexdigest(),
              "dataset_sha256": hashlib.sha256(data_path.read_bytes()).hexdigest()}
    directory = new_output_dir(output_root)
    responses = directory / "responses.jsonl"
    with responses.open("x", encoding="utf-8") as stream:
        for case in cases:
            if collect:
                from byoe.targets import collect_response

                # Expected answers and supplied responses never cross the target boundary.
                target_case = Case(id=case.id, query=case.query, context=case.context,
                                   metadata=case.metadata)
                response = collect_response(suite.target, target_case, timeout=120)
                if not isinstance(response, str):
                    raise ValueError("Target must return a real response string")
                case = case.model_copy(update={"response": response})
            stream.write(json.dumps(case.model_dump(), allow_nan=False) + "\n")
            stream.flush()
    fields = ("id", "query", "response", "context", "expected", "metadata")
    evaluators = {spec.id: SDKEvaluator(spec, suite.allow_code) for spec in suite.evaluators}
    mapping = {name: {"column_mapping": {field: f"${{data.{field}}}" for field in fields}}
               for name in evaluators}
    from azure.ai.evaluation import evaluate

    with sdk_working_directory():
        result = evaluate(
            data=str(responses), evaluators=evaluators, evaluator_config=mapping,
            evaluation_name=f"byoe-{directory.name}",
            output_path=str(directory / "evaluation.json"),
            fail_on_evaluator_errors=True,
        )
    passed = gate_result(result, suite, [case.id for case in cases])
    manifest = {**hashes, "schema_version": "1.0", "byoe_version": __version__,
                "python_version": platform.python_version(),
                "sdk_version": importlib.metadata.version("azure-ai-evaluation"),
                "evaluator_ids": list(evaluators), "target_kind": suite.target["kind"],
                "collected": collect, "case_count": len(cases),
                "result_count": len(result.get("rows", [])), "gate_passed": passed}
    write_json(directory / "manifest.json", manifest)
    report = directory / "report.json"
    write_json(report, {"schema_version": "1.0", "gate_passed": passed,
                        "case_count": len(cases), "evaluation_file": "evaluation.json",
                        "manifest_file": "manifest.json"})
    return report, passed