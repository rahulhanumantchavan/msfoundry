import os
from run_agent import AIAgent


researcher = AIAgent(
    model="anthropic/claude-sonnet-4.6",
    enabled_toolsets=["web"],
    ephemeral_system_prompt="You are a research assistant. Be thorough and cite sources.",
    quiet_mode=True,
)

coder = AIAgent(
    model="anthropic/claude-sonnet-4.6",
    enabled_toolsets=["terminal", "file", "code_execution"],
    ephemeral_system_prompt="You are a senior Python engineer.",
    quiet_mode=True,
)

reviewer = AIAgent(
    model="anthropic/claude-sonnet-4.6",
    disabled_toolsets=["terminal", "browser"],
    ephemeral_system_prompt="You are a strict code reviewer.",
    quiet_mode=True,
)

research = researcher.chat("Latest features in Python 3.13")
code = coder.chat(f"Write example code based on this research:\n{research}")
review = reviewer.chat(f"Review this code:\n{code}")