import asyncio
import json
import logging
from typing import Any

from agent_framework import Agent, Message, ToolContext
from agent_framework.foundry import FoundryChatClient
from azure.identity import DefaultAzureCredential

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    client = FoundryChatClient(credential=DefaultAzureCredential())

    mcp_tool = client.get_mcp_tool(
        name="MyMCPTool",
        url="https://your-mcp-server.azurewebsites.net/mcp",  # Your MCP endpoint
        approval_mode={"never_require_approval": ["*"]},     # Adjust for production
    )

    async with Agent(
        client=client,
        name="MCPLoggingAgent",
        instructions="You are a helpful assistant. Use MCP tools when needed.",
        tools=[mcp_tool],
    ) as agent:

        # === AUTOMATIC MCP CALL LOGGER ===
        @agent.tool_wrapper
        async def log_mcp_calls(tool_name: str, arguments: dict, context: ToolContext = None):
            """Wrapper that logs every MCP tool call with token info."""
            
            logger.info("=== MCP TOOL CALL DETECTED ===")
            logger.info(f"Tool Name: {tool_name}")
            logger.info(f"Arguments: {json.dumps(arguments, indent=2, default=str)}")

            # Extract and log token safely
            token_info = "No token found"
            if context and hasattr(context, 'request'):
                headers = getattr(context.request, 'headers', {}) or {}
                auth = headers.get("authorization") or headers.get("Authorization")
                
                if auth and auth.startswith("Bearer "):
                    token = auth.replace("Bearer ", "").strip()
                    partial_token = token[:40] + "..." + token[-20:] if len(token) > 60 else token
                    
                    logger.info(f"Authorization Header (partial): {partial_token}")
                    
                    # Decode JWT claims for debugging (without verifying signature)
                    try:
                        import jwt
                        decoded = jwt.decode(token, options={"verify_signature": False})
                        claims_to_log = {
                            "sub": decoded.get("sub"),
                            "oid": decoded.get("oid"),
                            "name": decoded.get("name"),
                            "aud": decoded.get("aud"),
                            "scp": decoded.get("scp"),
                            "exp": decoded.get("exp"),
                        }
                        logger.info(f"Token Claims: {json.dumps(claims_to_log, indent=2)}")
                    except Exception as e:
                        logger.warning(f"Failed to decode token: {e}")
                else:
                    logger.warning("No valid Authorization header found")
            else:
                logger.warning("No context.request available")

            logger.info("=== END MCP TOOL CALL LOG ===\n")

            # Return control to the original tool
            # (The wrapper should call the original handler)

        # Register the wrapper (if your framework supports it)
        # Note: Some versions use middleware or event hooks.
        # Alternatively, wrap each tool manually as shown below.

        # Example: Create a wrapper tool that logs before calling real MCP
        @agent.tool_plain
        async def debug_mcp_wrapper(query: str):
            """Use this to trigger MCP tools while ensuring logging."""
            logger.info(f"User Query: {query}")
            # Let the agent decide which MCP tool to call
            return "Logging enabled. Proceeding with MCP call..."

        # Run the agent
        result = await agent.run("Use the MCP tool to get my user data or perform a test action.")

        # Handle approvals if any
        while result.user_input_requests:
            new_inputs = []
            for req in result.user_input_requests:
                logger.info(f"Approval requested for {req.function_call.name}")
                approve = True  # Auto-approve for testing (change in production!)
                new_inputs.append(
                    Message(role="user", contents=[req.to_function_approval_response(approve)])
                )
            result = await agent.run(new_inputs)

        print("Final Agent Response:", result)

if __name__ == "__main__":
    asyncio.run(main())
