"""Basic Hermes Python library example.

Requirements:
- Run this from the hermes-agent checkout (editable dev env).
- Set an API key environment variable such as `OPENROUTER_API_KEY`,
  `OPENAI_API_KEY`, or `ANTHROPIC_API_KEY` before running.

Usage:
    python examples/python_library_example.py
"""

import os
from run_agent import AIAgent


def simple_chat():
    model = os.getenv("HERMES_MODEL", "gpt-4.1")
    agent = AIAgent(model=model, quiet_mode=True)
    response = agent.chat("What is the capital of France?")
    print("Simple chat ->", response)


def run_conversation_example():
    model = os.getenv("HERMES_MODEL", "gpt-4.1")
    agent = AIAgent(model=model, quiet_mode=True)
    result = agent.run_conversation(
        user_message="Explain quicksort",
        system_message="You are a computer science tutor. Use simple analogies.",
    )
    print("run_conversation final_response ->", result.get("final_response"))
    print(f"Messages exchanged: {len(result.get('messages', []))}")


def multi_turn_example():
    model = os.getenv("HERMES_MODEL", "gpt-4.1")
    agent = AIAgent(model=model, quiet_mode=True)
    # First turn
    r1 = agent.run_conversation(user_message="My name is Alice")
    history = r1.get("messages")
    # Second turn — pass previous messages as conversation_history
    r2 = agent.run_conversation(user_message="What's my name?", conversation_history=history)
    print("multi-turn reply ->", r2.get("final_response"))


def main():
    print("== Hermes Python library examples ==")
    simple_chat()
    run_conversation_example()
    multi_turn_example()


if __name__ == "__main__":
    main()
