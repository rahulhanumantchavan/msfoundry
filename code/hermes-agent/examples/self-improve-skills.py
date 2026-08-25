#!/usr/bin/env python3
"""
Enable skills + allow the agent to create/improve skills via skill_manage.
Run from a hermes-agent checkout:  uv run python skills_example.py
"""

import os
from run_agent import AIAgent

if not any(os.getenv(k) for k in ("OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")):
    raise SystemExit("Set an API key first.")
    
model = os.getenv("HERMES_MODEL", "gpt-4.1")

agent = AIAgent(
    model=model,
    enabled_toolsets=[
        "skills",     # skills_list, skill_view, skill_manage, ...
        "terminal",
        "file",
        "web",
    ],
    quiet_mode=True,
    # Keep memory ON so the self-improvement loop can persist facts
    skip_memory=False,
    # Optional: load project AGENTS.md
    skip_context_files=False,
    max_iterations=60,
)

# 1) Use / discover skills
print("=== List skills ===")
print(agent.chat("What skills do you have available? List names and short descriptions."))

# 2) Ask it to capture a procedure as a new skill (self-improvement)
print("\n=== Create a skill from a workflow ===")
print(
    agent.chat(
        """
After you finish, use skill_manage to SAVE a reusable skill.

Task: Figure out a reliable way to run pytest only on failed tests from the last run
(or document the standard approach if the project has none). Work in the current directory.

Then create a skill named something like `pytest-failed-only` with:
- when to use it
- exact commands
- pitfalls
Do not skip skill_manage — that is the point of this run.
"""
    )
)

# 3) Reuse the skill later (new agent instance still sees disk skills)
agent2 = AIAgent(
    model=model,
    enabled_toolsets=["skills", "terminal", "file"],
    quiet_mode=True,
    skip_memory=False,
)
print("\n=== Reuse skill ===")
print(agent2.chat("Load the pytest-failed-only skill (if it exists) and summarize its procedure."))