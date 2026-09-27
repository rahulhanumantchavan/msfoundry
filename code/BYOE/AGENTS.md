# Generic BYOE development

- Keep all application changes in this directory; preserve the original support POC.
- Python 3.13; run tests and Ruff offline with the workspace .venv.
- No provisioning, cloud deployment, or live model/judge calls without explicit scope.
- Preserve azure.ai.evaluation.evaluate and explicit column mappings.
- No mock fallback, silent provider substitution, or passing on invalid/missing metrics.
- Evaluators and models are independent adapters. Third-party code requires trust;
  process isolation is not a security sandbox.
- Keep secrets and result artifacts out of version control.
- If you are in VS Code, read the vscode-microsoft-foundry skill first.