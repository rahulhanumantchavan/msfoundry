#!/usr/bin/env python3
"""
Hermes Agent – Subagent (delegate_task) example
Run from a hermes-agent checkout with:  uv run python subagent_example.py
"""

import os
import time

from run_agent import AIAgent

# ---------------------------------------------------------------------------
# 1. Prerequisites
# ---------------------------------------------------------------------------
# Make sure you have at least one API key set, e.g.:
#   export OPENROUTER_API_KEY="sk-or-..."
#   # or OPENAI_API_KEY / ANTHROPIC_API_KEY

if not any(os.getenv(k) for k in ("OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")):
    raise SystemExit(
        "Set OPENROUTER_API_KEY (or OPENAI_API_KEY / ANTHROPIC_API_KEY) before running."
    )

# ---------------------------------------------------------------------------
# 2. Create the parent agent
# ---------------------------------------------------------------------------
# The parent MUST have the "delegation" toolset enabled so it can call
# delegate_task.  Also give it the tools the children will need
# (children inherit a subset of the parent's toolsets).
model = os.getenv("HERMES_MODEL", "gpt-4.1")

parent = AIAgent(
    model=model,
    enabled_toolsets=["web", "delegation"],
    quiet_mode=True,
    skip_memory=True,
    skip_context_files=True,
)

# First turn – parent will dispatch background subagents
result = parent.run_conversation(
    "Research these three topics in parallel with subagents, then write a "
    "max-400-word comparative briefing:\n"
    "1. WebAssembly outside the browser\n"
    "2. RISC-V server chip adoption\n"
    "3. Practical quantum computing applications (2025-2026)\n"
    "Focus on key players, milestones, and real-world use."
)

print("Initial reply:\n", result["final_response"])
history = result["messages"]

# Poll / continue until the parent produces the real synthesis
for attempt in range(12):          # ~2 minutes max
    time.sleep(10)
    result = parent.run_conversation(
        "Have the subagents finished? If yes, give me the final 400-word "
        "comparative briefing now. If still running, just say 'still working'.",
        conversation_history=history,
    )
    history = result["messages"]
    reply = result["final_response"]
    print(f"\n--- attempt {attempt+1} ---\n{reply}")

    if "still working" not in reply.lower() and len(reply) > 300:
        print("\n===== FINAL BRIEFING =====")
        print(reply)
        break
else:
    print("Timed out waiting for subagents.")