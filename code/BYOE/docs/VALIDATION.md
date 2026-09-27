# POC validation — 2026-09-26

Validated on Windows with the workspace Python 3.13.5 virtual environment.

| Check | Result |
| --- | --- |
| BYOE offline tests | 176 passed |
| Original support POC regression tests | 33 passed |
| Ruff for BYOE | Passed |
| Installed dependency consistency | Passed |
| Eight configuration JSON files | Parsed successfully |
| Additive VS Code task/launch JSON | Valid |
| Four-adapter demo fixture verification | Passed: known positive/negative fixtures |
| Four-adapter SDK evaluation | Passed: 3 saved synthetic cases × 4 evaluators |
| Local Responses host tests | Readiness and response tested with an explicit fake agent |

The demo exercised real Python and CLI execution, real loopback HTTP transport,
and the real Azure evaluation SDK. Its OpenAI-compatible judge service was an
**explicit deterministic mock**. It did not assess a live LLM judge or a remote
Foundry agent. The Foundry/model client request behavior was tested with mocks.

Final demo reports (local and git-ignored):
- `results/82ba6b5ef7ec453bb4b251b7362b22bc/verification.json`
- `results/8644039d42764651bcc8a8f662677135/report.json`

No Azure resources were provisioned or deployed. No live model/judge calls were
made for this generic POC. Real Foundry deployment, auth/routing, model-provider
compatibility, real judge fixtures and Linux hosting remain deployment-stage checks.