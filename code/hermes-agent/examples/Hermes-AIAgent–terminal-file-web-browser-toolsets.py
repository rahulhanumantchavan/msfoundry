#!/usr/bin/env python3
"""
Hermes AIAgent – terminal, file, web, browser toolsets
Run from a hermes-agent checkout:
  uv run python coding_agent_example.py
"""

import os
from run_agent import AIAgent

# API key required (any one of these)
if not any(
    os.getenv(k)
    for k in ("OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")
):
    raise SystemExit(
        "Set OPENROUTER_API_KEY (or OPENAI_API_KEY / ANTHROPIC_API_KEY) first."
    )

model = os.getenv("HERMES_MODEL", "gpt-4.1")

agent = AIAgent(
    model=model,
    enabled_toolsets=[
        "terminal",  # shell / commands
        "file",      # read / write / patch files
        "web",       # web_search, web_extract
        "browser",   # browser_navigate, snapshot, click, etc.
    ],
    quiet_mode=True,           # no CLI spinners in library mode
    skip_memory=True,          # stateless run (optional)
    skip_context_files=False,  # load AGENTS.md from cwd if present
    max_iterations=80,
)

prompt = """
Do the following in order:

1. WEB: Search for "Python 3.13 release notes" and summarize 3 important changes.
2. BROWSER: Open https://docs.python.org/3.13/whatsnew/3.13.html and extract
   the top-level section titles from the page.
3. FILE: Write a short markdown report to ./python_313_notes.md with both summaries.
4. TERMINAL: Run `wc -l python_313_notes.md` and `ls -la python_313_notes.md`
   and include those outputs in your final reply.

Report what you did and the command outputs.
"""

print("Agent working...\n")
response = agent.chat(prompt)
print("=" * 60)
print(response)
print("=" * 60)