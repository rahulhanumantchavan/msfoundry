# Hermes Python library examples

This folder contains a minimal example showing how to import and use
`AIAgent` from the hermes-agent checkout.

Prerequisites
- Clone the repo and create the editable development environment (see project README).
- Set an API key environment variable that Hermes supports, for example:

```powershell
setx OPENROUTER_API_KEY "your_api_key_here"
# or for current session:
$env:OPENROUTER_API_KEY = "your_api_key_here"
```

If you are using an Azure OpenAI / Foundry deployment, set the `HERMES_MODEL`
environment variable to the deployment/model name (for example `gpt-4.1`).

PowerShell example (Windows):

```powershell
$env:HERMES_MODEL = "gpt-4.1"
# Set your Azure OpenAI resource endpoint and key for the current session
$env:AZURE_OPENAI_ENDPOINT = "https://<your-resource>.openai.azure.com/openai/v1"
$env:AZURE_OPENAI_API_KEY = "your_azure_api_key_here"
# Ensure Python can import the repo when running from checkout
$env:PYTHONPATH = Convert-Path .
python .\examples\python_library_example.py
```

Command Prompt (cmd.exe) example:

```cmd
set HERMES_MODEL=gpt-4.1
set AZURE_OPENAI_ENDPOINT=https://<your-resource>.openai.azure.com/openai/v1
set AZURE_OPENAI_API_KEY=your_azure_api_key_here
set PYTHONPATH=%CD%
python .\examples\python_library_example.py
```

Running the example

From the repository root run:

```powershell
python .\examples\python_library_example.py
```

Notes
- Prefer `quiet_mode=True` when embedding Hermes to avoid CLI spinners.
- For stateless web endpoints, pass `skip_memory=True` and `skip_context_files=True`.
- Create one `AIAgent` instance per thread/task; do not share instances across threads.

See the official docs: https://hermes-agent.nousresearch.com/docs/guides/python-library
