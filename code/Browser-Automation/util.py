# ------------------------------------
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
# ------------------------------------
"""Local copy of the azure-ai-projects samples helper.

Provides ``create_version_with_endpoint`` (and the async variant), a context
manager that:

1. Creates a new agent version.
2. Points the agent endpoint at that version (100% traffic, responses protocol).
3. On exit, restores the original endpoint config and deletes the created version.
"""

from contextlib import asynccontextmanager, contextmanager
from typing import Any, AsyncIterator, Iterator, Optional

from azure.ai.projects import AIProjectClient
from azure.ai.projects.aio import AIProjectClient as AsyncAIProjectClient
from azure.ai.projects.models import (
    AgentBlueprintReference,
    AgentDefinition,
    AgentEndpointConfig,
    AgentVersionDetails,
    FixedRatioVersionSelectionRule,
    ProtocolConfiguration,
    ResponsesProtocolConfiguration,
    VersionSelector,
)

__all__ = ["create_version_with_endpoint", "create_version_with_endpoint_async"]


def _build_endpoint_config(agent_version: str) -> AgentEndpointConfig:
    return AgentEndpointConfig(
        version_selector=VersionSelector(
            version_selection_rules=[
                FixedRatioVersionSelectionRule(agent_version=agent_version, traffic_percentage=100),
            ]
        ),
        protocol_configuration=ProtocolConfiguration(responses=ResponsesProtocolConfiguration()),
    )


@contextmanager
def create_version_with_endpoint(
    project_client: AIProjectClient,
    agent_name: str,
    *,
    definition: AgentDefinition,
    metadata: Optional[dict[str, str]] = None,
    description: Optional[str] = None,
    blueprint_reference: Optional[AgentBlueprintReference] = None,
    draft: Optional[bool] = None,
    **kwargs: Any,
) -> Iterator[AgentVersionDetails]:
    """Create a version, point the agent endpoint to it, then restore and delete on exit."""
    created_version = None
    original_agent_endpoint = None

    try:
        created_version = project_client.agents.create_version(
            agent_name=agent_name,
            definition=definition,
            metadata=metadata,
            description=description,
            blueprint_reference=blueprint_reference,
            draft=draft,
            **kwargs,
        )
        print(
            f"Agent version created (id: {created_version.id}, name: {created_version.name}, "
            f"version: {created_version.version})"
        )

        original_agent_endpoint = project_client.agents.get(agent_name=agent_name).agent_endpoint
        project_client.agents.update_details(
            agent_name=agent_name,
            agent_endpoint=_build_endpoint_config(created_version.version),
        )
        print(f"Agent endpoint configured for version {created_version.version}")

        yield created_version
    finally:
        if original_agent_endpoint is not None:
            project_client.agents.update_details(agent_name=agent_name, agent_endpoint=original_agent_endpoint)
            print("Agent endpoint restored")

        if created_version is not None:
            project_client.agents.delete_version(
                agent_name=agent_name, agent_version=created_version.version, force=True
            )
            print(f"Agent version {created_version.version} deleted")


@asynccontextmanager
async def create_version_with_endpoint_async(
    project_client: AsyncAIProjectClient,
    agent_name: str,
    *,
    definition: AgentDefinition,
    metadata: Optional[dict[str, str]] = None,
    description: Optional[str] = None,
    blueprint_reference: Optional[AgentBlueprintReference] = None,
    draft: Optional[bool] = None,
    **kwargs: Any,
) -> AsyncIterator[AgentVersionDetails]:
    """Async variant of :func:`create_version_with_endpoint`."""
    created_version = None
    original_agent_endpoint = None

    try:
        created_version = await project_client.agents.create_version(
            agent_name=agent_name,
            definition=definition,
            metadata=metadata,
            description=description,
            blueprint_reference=blueprint_reference,
            draft=draft,
            **kwargs,
        )
        print(
            f"Agent version created (id: {created_version.id}, name: {created_version.name}, "
            f"version: {created_version.version})"
        )

        original_agent_endpoint = (await project_client.agents.get(agent_name=agent_name)).agent_endpoint
        await project_client.agents.update_details(
            agent_name=agent_name,
            agent_endpoint=_build_endpoint_config(created_version.version),
        )
        print(f"Agent endpoint configured for version {created_version.version}")

        yield created_version
    finally:
        if original_agent_endpoint is not None:
            await project_client.agents.update_details(agent_name=agent_name, agent_endpoint=original_agent_endpoint)
            print("Agent endpoint restored")

        if created_version is not None:
            await project_client.agents.delete_version(
                agent_name=agent_name, agent_version=created_version.version, force=True
            )
            print(f"Agent version {created_version.version} deleted")
