# Generic Agent with BYOE — pattern and POC

**Status:** implemented and tested locally; **not deployed to Foundry**.
The original customer-support example remains separate and unchanged.

This pattern separates three choices:

1. **Agent host** — Foundry Responses endpoint, canonical HTTP endpoint on AKS/own
   infrastructure, or a directly invoked model-backed agent.
2. **Model provider** — Foundry project model, OpenAI-compatible model service hosted
   anywhere, or a trusted Python provider adapter for a different native protocol.
3. **Evaluator** — Python function/library wrapper, CLI tool, HTTP service, or an
   independently configured LLM judge.

“Generic” means a stable contract plus adapters. It does **not** mean every vendor's
native API works without a wrapper, or that passing a contract test proves an
evaluator's accuracy, safety, or resistance to manipulation.

## Start here: zero-cloud POC

In the current workspace, choose **Terminal → Run Task → BYOE Generic: offline demo**.
It starts explicitly mock loopback services, verifies known pass/fail fixtures for
all four evaluator kinds, evaluates saved synthetic responses, and stops the services.
No real model, judge, or Foundry agent is called. Reports identify the run as a mock
protocol demonstration. There is no mock fallback on real-provider failures.

Other tasks:

| Task | Purpose |
| --- | --- |
| BYOE Generic: tests | Offline unit and SDK integration tests |
| BYOE Generic: verify evaluators | Python/CLI known-answer compatibility fixtures |
| BYOE Generic: evaluate saved | Evaluate explicit synthetic saved responses |
| BYOE Generic: evaluate Foundry agent | Collect real responses from a configured deployed agent and evaluate locally |

The existing workspace `.venv` is Python 3.13. For a standalone checkout, create a
Python 3.13 virtual environment and install `requirements.txt`. The host adapter
uses preview SDKs with a tested compatibility set. Direct dependencies are pinned;
transitive versions are not a full lockfile. Linux/cloud execution remains unverified.

CLI entry points (run with `BYOE` as working directory):

```text
python demo.py
python -m byoe verify --suite configs/suite.offline.json --fixtures data/fixtures.offline.jsonl
python -m byoe evaluate --suite configs/suite.offline.json --data data/responses.jsonl
python -m byoe evaluate --suite configs/suite.foundry-agent.json --data data/queries.jsonl --collect
```

Exit codes: **0** passed, **1** gate or fixture assertion failed, **2** invalid
configuration/runtime failure. Exceptions are deliberately sanitized. Use debugger
breakpoints to diagnose unexpected failures; do not print secrets in logs.

## Foundry POC path

1. Read `docs/FOUNDRY_POC.md`. No cloud deployment is executed by any default task.
2. For local hosting, copy `.env.example` to `.env`, confirm the existing project and
   model deployment, and select **F5 → BYOE Generic: hosted agent**. VS Code loads
   this file and opens Agent Inspector on port **8090**.
   The command-line runner does not automatically load `.env`; export environment
   variables yourself when running outside the provided launch configuration.
3. After a separately approved deployment, set `BYOE_AGENT_RESPONSES_URL` to the
   **actual full protocol URL** returned by discovery. Export it into the environment
   before starting the evaluation task; the task does not read `.env` automatically.
4. Run **BYOE Generic: evaluate Foundry agent**. Model inference may be billable;
   evaluator execution and reports remain local. No cloud evaluator registration
   occurs. This POC is client-side BYOE, not Foundry-managed remote evaluation.

## Bring another evaluator

- Implement or wrap the contract in `docs/CONTRACTS.md`.
- Register its kind/configuration/threshold in a suite JSON file.
- Set `allow_code=true` only for reviewed Python/CLI code or Python model providers.
- Add at least one known valid pass and one known valid fail fixture for its ID.
- Run `verify`, then `evaluate` on representative response data.
- Add human-labeled calibration data separately before relying on evaluator quality.

For existing evaluation libraries, write a small wrapper that maps Case fields to
the library's parameters and its output to `score` and `reason`. Convert the original
scale explicitly to **0..1, higher-is-better**; do not rely on implicit conversion.

## Files

| Path | Responsibility |
| --- | --- |
| `byoe/contracts.py` | Versioned strict cases, evaluator outputs and suite configuration |
| `byoe/adapters.py`, `execution.py` | Evaluator adapters and process deadlines |
| `byoe/model.py`, `targets.py` | Independent model and agent-target adapters |
| `byoe/runner.py` | Azure SDK evaluation with explicit column mappings and gates |
| `byoe/verify.py` | Known-answer evaluator fixture verification |
| `byoe/hosting.py`, `hosted_main.py` | Portable model-backed Responses host |
| `configs/`, `data/` | Ready-to-edit configurations and synthetic test data |
| `docs/` | Architecture, contracts, security limits and deployment handoff |

## Reports

Every run gets a unique `results/<uuid>/` directory. Evaluation produces
`responses.jsonl`, SDK `evaluation.json`, `manifest.json`, and `report.json`.
Verification produces `verification.json` with fixture assertions and coverage.
Manifests identify input-file hashes, evaluator IDs, runtime/SDK versions and whether
responses were collected. They do not snapshot model weights, plugin source, rubric
versions outside the suite, or remote-service deployments. Record those separately
for production reproducibility. A collection failure may leave partial responses;
it cannot produce a passing evaluation report.

All evaluators must produce valid results. Required evaluators must meet the suite
minimum pass rate; optional evaluators may score low but cannot hide contract errors.
The gate also validates row count, case IDs, finite metrics and threshold consistency.

See `docs/SECURITY.md` before running third-party evaluators or sensitive datasets.