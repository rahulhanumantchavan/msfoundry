# Development guidance

- This is a local Python 3.13 agent with custom BYOE evaluators, not an Azure deployment.
- Keep inference configuration in environment variables; do not commit secrets or results.
- Preserve evaluation via `azure.ai.evaluation.evaluate` and explicit column mappings.
- Run offline pytest tests and Ruff before considering a change complete.
- Do not treat keyword/format metrics as proof of factual correctness or safety.
- If you are in VS Code, read the vscode-microsoft-foundry skill first.