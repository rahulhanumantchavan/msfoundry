"""Known-answer contract fixtures, distinct from SDK dataset aggregation."""

from pathlib import Path

from byoe.contracts import Fixture, strict_json_loads
from byoe.execution import execute, invalid_result
from byoe.runner import load_suite, new_output_dir, unit_number, write_json


def verify_suite(suite_path: Path, fixtures_path: Path,
                 output_root: Path) -> tuple[Path, bool]:
    """Return (report_path, assertions_and_coverage_passed); bad inputs raise."""
    suite = load_suite(suite_path)
    fixtures = [Fixture.model_validate(strict_json_loads(line))
                for line in fixtures_path.read_text(encoding="utf-8").splitlines()
                if line.strip()]
    if not fixtures:
        raise ValueError("Fixtures cannot be empty")
    specs = {spec.id: spec for spec in suite.evaluators}
    if any(fixture.evaluator_id not in specs for fixture in fixtures):
        raise ValueError("Unknown evaluator ID in fixtures")
    results = []
    coverage = {key: set() for key in specs}
    for fixture in fixtures:
        result = execute(specs[fixture.evaluator_id], fixture.case, suite.allow_code)
        valid_shape = all(unit_number(result.get(key)) for key in ("score", "passed", "valid"))
        valid_shape = valid_shape and result["valid"] in (0, 1) and result["passed"] in (0, 1)
        matched = (valid_shape and result["valid"] == int(fixture.expect_valid)
                   and result["passed"] == int(fixture.expect_pass))
        if matched and fixture.expect_valid:
            matched = (result.get("error_code") == "" and result["passed"] == int(
                result["score"] >= specs[fixture.evaluator_id].threshold))
        if result.get("valid") == 0:
            matched = matched and result.get("score") == 0 and result.get("passed") == 0
        if matched and fixture.expect_valid:
            coverage[fixture.evaluator_id].add(fixture.expect_pass)
        if not valid_shape:
            # Preserve the failed assertion without writing non-JSON NaN/Infinity.
            result = invalid_result("invalid_execution_output")
        results.append({"evaluator_id": fixture.evaluator_id, "case_id": fixture.case.id,
                        "matched": matched, "result": result})
    missing = [key for key, values in coverage.items() if values != {True, False}]
    passed = not missing and all(item["matched"] for item in results)
    path = new_output_dir(output_root) / "verification.json"
    write_json(path, {"schema_version": "1.0", "gate_passed": passed,
                      "missing_pass_fail_coverage": missing, "fixtures": results})
    return path, passed