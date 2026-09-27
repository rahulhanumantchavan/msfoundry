"""Chat in the terminal or serve the Responses API for Agent Inspector."""

import argparse
import asyncio

from agent import support_agent
from local_server import create_local_adapter, local_hosting_environment


async def run(query: str | None, serve: bool) -> None:
    async with support_agent() as agent:
        if serve:
            import uvicorn

            with local_hosting_environment():
                adapter = create_local_adapter(agent)
                # The SDK convenience runner binds 0.0.0.0; use loopback instead.
                config = uvicorn.Config(adapter.app, host="127.0.0.1", port=8088)
                await uvicorn.Server(config).serve()
        else:
            response = await agent.run(query or "How do I return an unused item?")
            print(response.text)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query")
    parser.add_argument("--serve", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.query, args.serve))