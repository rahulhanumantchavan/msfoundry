# Customer-support agent with BYOE

A local Python / Microsoft Agent Framework agent using the existing Foundry
`msazfoundry1-proj-default` project and `gpt-5-mini` deployment. No cloud agent,
infrastructure, or remote evaluation is created.

## Run in VS Code

- **F5 → Support Agent: Inspector** starts the loopback-only Responses API on port
  8088 and opens Foundry Toolkit Agent Inspector. Requires the Python Debugger and
  Foundry Toolkit extensions. Stopping this configuration terminates running VS Code tasks.
- **Support Agent: single query** runs one question in the terminal debugger.
- **Terminal → Run Task → BYOE: collect and evaluate** collects eight fresh responses
  and runs the custom evaluators locally. Model inference is billable.
- **Terminal → Run Task → Tests: offline** runs tests without Azure or model calls.

The local `.venv` uses Python 3.13. To recreate it, create a Python 3.13 virtual
environment and install `requirements.txt`. Some SDKs are previews
because the Inspector adapter pins a preview Agent Framework version.
Copy `.env.example` to `.env` when setting up a fresh checkout. Set the project
endpoint and actual deployment name there. Authentication uses your Azure CLI
sign-in through `DefaultAzureCredential`; sign in manually if required. Your identity
needs inference access to the existing resource. No API keys are stored.

## Bring your own evaluations

`evaluators.py` contains two independent callable classes:

| Evaluator | Metrics | Meaning |
| --- | --- | --- |
| RequiredKeywordsEvaluator | keyword_coverage, keyword_pass | Whole-phrase, case-insensitive coverage in the JSON answer field |
| ResponseFormatEvaluator | format_valid, routing_correct | Strict JSON/schema validity and expected category/escalation |

Keyword matching normalizes Unicode presentation forms, dash variants, and whitespace
before comparison, so typographic nonbreaking hyphens do not cause false failures.

To add a custom evaluator, implement `__call__` with keyword-only dataset arguments
and return a dictionary of numeric scores and optional explanations. Register it in
`evaluator_registry()` with its `${data.column}` mappings. Add its metric to
`passes_gate()` if it should block a run. No additional model is needed for the two
included code-based evaluators.

Edit `dataset.jsonl` to bring your own queries, required phrases, expected category,
and expected escalation. Cases run independently, without shared conversation state.
Edit `support_policy.md` to replace the fictional policy with approved content.

`evaluate_agent.py` uses the Azure AI Evaluation SDK's `evaluate()` API for execution
and aggregation. Each run creates a unique `results/<run-id>/` folder containing
`responses.jsonl` (when collecting) and `evaluation.json` with row-level scores and
aggregate metrics. A collection failure stops the run; partial responses remain
available for diagnosis and are never silently treated as a complete evaluation.

For an offline re-score, run `evaluate_agent.py` with `--responses` set to a saved
responses JSONL file. It does not call the agent. `--min-pass-rate` sets the minimum
aggregate pass rate (default 1.0). Exit code 0 means the quality gate passed; 1 means
it failed. Missing or non-finite required metrics fail closed. Other runtime errors
also produce a nonzero exit status.

## Limitations and data handling

- Keyword checks are brittle proxies, not evidence of factual correctness, safety,
  or overall quality. A wrong answer can contain all expected phrases; a correct
  paraphrase can fail. Format and routing checks do not establish answer correctness.
- The eight synthetic cases are a starter, not a production benchmark. Add reviewed
  domain-specific examples, negative cases, and semantic/human evaluation before use.
- The agent has no order lookup or action tools and cannot issue refunds or cancel orders.
- Evaluation results are local and git-ignored. Queries/policy are sent to Foundry for
  inference; Responses API storage is disabled. Do not put customer secrets in test data.
- The development server has no application authentication and binds only to
  `127.0.0.1`. It uses in-memory sessions, with no cloud session persistence or
  automatic Application Insights export. Do not expose it publicly.
- Deployment is not configured. Deployment to Foundry is a separate, opt-in step.

## Verified locally

- 33 offline tests pass, Ruff passes, and installed dependencies are compatible.
- Eight actual `gpt-5-mini` responses were collected. The first run caught a Unicode
  hyphen mismatch; after normalization and a regression test, re-scoring the same
  responses passed all four metrics at 1.0, without reducing the quality threshold.
- The local `/readiness` endpoint returns 200, and `/responses` produces real output.
- These results validate the starter's execution, not production readiness. Live
  responses can add details not in the sample policy, which the current proxy
  evaluators do not detect. Add groundedness evaluation and human review for that risk.