"""Local-only adapter configuration, isolated from cloud persistence and telemetry."""

import os
from contextlib import contextmanager


@contextmanager
def local_hosting_environment():
    # The inference client is already constructed with its explicit endpoint.
    # Hide cloud-hosting settings before importing the adapter: its logger otherwise
    # auto-discovers Application Insights and its session store defaults to Foundry.
    keys = (
        "AZURE_AI_PROJECT_ENDPOINT", "AGENT_PROJECT_RESOURCE_ID",
        "APPLICATIONINSIGHTS_CONNECTION_STRING", "APPINSIGHTS_INSTRUMENTATIONKEY",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
    )
    saved = {key: os.environ.pop(key) for key in keys if key in os.environ}
    try:
        yield
    finally:
        os.environ.update(saved)


def create_local_adapter(agent):
    """Call only inside local_hosting_environment()."""
    from azure.ai.agentserver.agentframework import from_agent_framework
    from azure.ai.agentserver.agentframework.persistence import InMemoryAgentSessionRepository
    from opentelemetry import trace

    adapter = from_agent_framework(agent, session_repository=InMemoryAgentSessionRepository())
    # A no-export tracer satisfies the adapter without auto-enabling cloud telemetry.
    adapter.tracer = trace.get_tracer(__name__)
    return adapter