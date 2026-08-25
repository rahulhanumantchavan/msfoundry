import concurrent.futures
from run_agent import AIAgent

def process(prompt):
    agent = AIAgent(          # new instance every time
        model="anthropic/claude-sonnet-4.6",
        quiet_mode=True,
        skip_memory=True,
    )
    return agent.chat(prompt)

prompts = ["Explain recursion", "What is a hash table?", "How does GC work?"]

with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
    results = list(executor.map(process, prompts))