from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any
import uuid

app = FastAPI(title="Hello World A2A Agent")

# ==================== AGENT CARD ====================
AGENT_CARD = {
    "name": "Hello World Agent",
    "description": "A simple A2A agent that always responds with 'hello world'",
    "version": "1.0.0",
    "protocolVersion": "0.3",
    "url": "https://helloworld-a2a-agent.azurewebsites.net",
    "supportedInterfaces": [
        {
            "url": "https://helloworld-a2a-agent.azurewebsites.net/a2a",
            "protocolBinding": "JSONRPC"
        },
        {
            "url": "https://helloworld-a2a-agent.azurewebsites.net",
            "protocolBinding": "JSONRPC"
        }
    ],
    "preferredTransport": "JSONRPC",
    "capabilities": {
        "streaming": False,
        "extendedAgentCard": True,
        "pushNotifications": False
    },
    "defaultInputModes": ["text/plain", "text"],
    "defaultOutputModes": ["text/plain", "text"],
    "supportsAuthenticatedExtendedCard": True,
    "skills": [
        {
            "id": "hello",
            "name": "Hello World",
            "description": "Returns a static hello world message.",
            "tags": ["a2a", "example"],
            "examples": ["hello", "hi", "say hello"],
            "inputModes": ["text/plain"],
            "outputModes": ["text/plain"]
        }
    ]
}
# ===================================================

@app.get("/.well-known/agent.json")
@app.get("/.well-known/agent-card.json")
async def get_agent_card():
    return AGENT_CARD


@app.post("/a2a")
@app.post("/")
async def handle_a2a(request: Request):
    try:
        body = await request.json()
        request_id = body.get("id") or str(uuid.uuid4())
        
        message_id = str(uuid.uuid4())
        task_id = str(uuid.uuid4())
        context_id = str(uuid.uuid4())

        # Proper A2A response with 'kind' discriminator
        result = {
            "kind": "message",           # ← This was missing (critical for Microsoft)
            "messageId": message_id,
            "role": "agent",
            "parts": [
                {
                    "kind": "text",
                    "text": "hello world from A2A agent!"
                }
            ]
        }

        # Some implementations also wrap it under task
        # Uncomment the block below if the above still fails
        """
        result = {
            "kind": "task",
            "task": {
                "id": task_id,
                "contextId": context_id,
                "status": "completed",
                "message": {
                    "messageId": message_id,
                    "role": "agent",
                    "parts": [
                        {"kind": "text", "text": "hello world from A2A agent!"}
                    ]
                }
            }
        }
        """

        response = {
            "jsonrpc": "2.0",
            "result": result,
            "id": request_id
        }
        
        return JSONResponse(content=response)

    except Exception as e:
        error_response = {
            "jsonrpc": "2.0",
            "error": {
                "code": -32603,
                "message": f"Internal error: {str(e)}"
            },
            "id": body.get("id") if 'body' in locals() else None
        }
        return JSONResponse(content=error_response, status_code=500)


@app.get("/")
async def root_get():
    return {"status": "A2A Hello World Agent is running"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)