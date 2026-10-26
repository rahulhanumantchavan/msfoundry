import os
import json
from dotenv import load_dotenv
from util import create_version_with_endpoint
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    PromptAgentDefinition,
    BrowserAutomationTool,
    BrowserAutomationToolParameters,
    BrowserAutomationToolConnectionParameters,
)

load_dotenv()

endpoint = ""
agent_name = "BrowserAgent"
FOUNDRY_MODEL_NAME = "gpt-6-astra"
project_connection_id = ""
# endpoint = os.environ["FOUNDRY_PROJECT_ENDPOINT"]
# agent_name = os.environ.get("FOUNDRY_AGENT_NAME") or "MyAgent"


tool = BrowserAutomationTool(
    browser_automation=BrowserAutomationToolParameters(
        connection=BrowserAutomationToolConnectionParameters(
            project_connection_id=project_connection_id or os.environ["BROWSER_AUTOMATION_PROJECT_CONNECTION_ID"],
        )
    )
)

with (
    DefaultAzureCredential() as credential,
    AIProjectClient(endpoint=endpoint, credential=credential) as project_client,
    create_version_with_endpoint(
        project_client=project_client,
        agent_name=agent_name,
        definition=PromptAgentDefinition(
            model=FOUNDRY_MODEL_NAME,
            instructions="""You are an Agent helping with browser automation tasks.
        You can answer questions, provide information, and assist with various tasks
        related to web browsing using the Browser Automation tool available to you.""",
            tools=[tool],
        ),
    ),
    project_client.get_openai_client(agent_name=agent_name) as openai_client,
):
    stream_response = openai_client.responses.create(
        stream=True,
        input="""
        Use the Browser Automation tool to visit https://example.com.
        Read the page and report its title and the visible description paragraph.
        Base your answer on the browser results, not on prior knowledge.""",
    )

    for event in stream_response:
        if event.type == "response.created":
            print(f"Response created with ID: {event.response.id}")
        elif event.type == "response.output_item.done":
            item = event.item
            # Each browser action (navigate, click, type, ...) is surfaced as a "remote_function_call" item.
            if item.type == "remote_function_call":
                arguments = json.loads(getattr(item, "arguments", None) or "{}")
                arguments.pop("browserSessionId", None)
                print(f"Browser action: {item.name} (call ID: {item.call_id}), arguments: {arguments}")
        elif event.type == "response.output_text.done":
            # Includes the live view URL message as well as the final answer.
            print(f"\nAgent message: {event.text}")
        elif event.type == "response.completed":
            print("\nResponse completed!")
