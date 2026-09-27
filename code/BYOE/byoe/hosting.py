"""Foundry Responses hosting, not deployment or a remote-agent client.

MODEL_CONFIG_FILE defaults to configs/model.foundry.json and
BYOE_INSTRUCTIONS_FILE defaults to data/instructions.md (relative to BYOE).
Explicit relative paths resolve against the caller's working directory.
The evaluation target is independent and is never read by this module.

Only foundry_model and openai_chat can be hosted. Trusted python complete()
providers extend direct evaluation, not the streaming Agent Framework protocol.
No authentication is installed on the standalone server: use loopback locally;
an actual Azure deployment must supply platform authentication.
"""

import os
from contextlib import AsyncExitStack, asynccontextmanager, contextmanager
from pathlib import Path

from byoe.contracts import strict_json_loads
from byoe.model import model_endpoint, required_env, validate_model, validate_timeout

ROOT = Path(__file__).resolve().parents[1]
HOST_ENV_KEYS = (
    "AZURE_AI_PROJECT_ENDPOINT", "AZURE_AIPROJECT_ENDPOINT",
    "AGENT_PROJECT_RESOURCE_ID", "AGENT_PROJECT_NAME",
    "APPLICATIONINSIGHTS_CONNECTION_STRING", "APPINSIGHTS_INSTRUMENTATIONKEY",
    "OTEL_EXPORTER_ENDPOINT", "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT",
    "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", "AZURE_AI_WORKSPACE_ENDPOINT",
    "AZURE_AI_TOOLS_ENDPOINT", "AGENT_APP_INSIGHTS_ENABLED", "AGENT_DEBUG_ERRORS",
)


@contextmanager
def isolated_hosting_environment():
    """Startup-only process-global guard; never use concurrently with imports.

    Construct explicit inference clients BEFORE entering. Only adapter import and
    construction occur here; all environment values are restored before serving.
    This does not uninstall exporters already configured by the embedding app.
    """
    saved = {key: os.environ.pop(key) for key in HOST_ENV_KEYS if key in os.environ}
    os.environ["AGENT_APP_INSIGHTS_ENABLED"] = "false"
    os.environ["AGENT_DEBUG_ERRORS"] = "false"
    try:
        yield
    finally:
        for key in HOST_ENV_KEYS:
            os.environ.pop(key, None)
        os.environ.update(saved)


class _NoHostingCredential:
    """Hosting has no cloud tools/persistence; inference owns its own credential."""

    async def get_token(self, *scopes, **kwargs):
        raise RuntimeError("Hosting-side cloud access is disabled")

    async def close(self):
        pass


def create_adapter(agent):
    """Adapt an existing agent without discovery, exporters or cloud persistence."""
    with isolated_hosting_environment():
        from azure.ai.agentserver.agentframework import from_agent_framework
        from azure.ai.agentserver.agentframework.persistence import InMemoryAgentSessionRepository
        from opentelemetry import trace

        adapter = from_agent_framework(
            agent, credentials=_NoHostingCredential(),
            session_repository=InMemoryAgentSessionRepository(),
        )
        adapter.tracer = trace.get_tracer(__name__)
    return adapter


def load_hosting_config() -> tuple[dict, str]:
    """Read strict JSON and instructions; do not import or contact any provider."""
    try:
        config_path = Path(os.environ.get("MODEL_CONFIG_FILE", ROOT / "configs/model.foundry.json"))
        policy_path = Path(os.environ.get("BYOE_INSTRUCTIONS_FILE", ROOT / "data/instructions.md"))
        config = validate_model(strict_json_loads(config_path.read_bytes()))
        instructions = policy_path.read_text(encoding="utf-8")
        if not instructions.strip():
            raise ValueError
        return config.model_dump(), instructions
    except Exception:
        raise ValueError("Cannot load MODEL_CONFIG_FILE or BYOE_INSTRUCTIONS_FILE") from None


async def _no_api_key() -> str:
    # OpenAI 3.19 rejects a literal empty key during construction, but accepts a
    # provider returning an empty string with Authorization explicitly omitted.
    return ""


@asynccontextmanager
async def hosted_agent(config: dict, instructions: str, timeout: float = 120):
    """Own credential, HTTP client and agent lifetimes; no remote agent creation."""
    settings = validate_model(config)
    timeout = validate_timeout(timeout)
    if settings.kind == "python":
        raise ValueError(
            "Python model hosting is unsupported; use a direct model evaluation target"
        )
    endpoint = model_endpoint(settings)
    deployment = required_env(settings.model_env)
    if type(instructions) is not str or not instructions.strip():
        raise ValueError("Hosting instructions must be nonempty")

    from openai import AsyncOpenAI, DefaultAsyncHttpxClient, omit

    options = {"store": False}
    if settings.kind == "openai_chat" and not settings.token_env and not settings.azure_scope:
        # The pinned SDK requires per-request omission as well as an empty key.
        options["extra_headers"] = {"Authorization": omit}
    async with AsyncExitStack() as stack:
        transport = await stack.enter_async_context(DefaultAsyncHttpxClient(
            timeout=timeout, follow_redirects=False, trust_env=False,
        ))
        if settings.kind == "foundry_model":
            from agent_framework.azure import AzureOpenAIResponsesClient
            from azure.ai.projects.aio import AIProjectClient
            from azure.identity.aio import DefaultAzureCredential

            credential = await stack.enter_async_context(DefaultAzureCredential())
            project = await stack.enter_async_context(AIProjectClient(
                endpoint=endpoint, credential=credential,
            ))
            http_client = await stack.enter_async_context(project.get_openai_client(
                timeout=timeout, max_retries=0, http_client=transport,
            ))
            client = AzureOpenAIResponsesClient(
                async_client=http_client, deployment_name=deployment,
            )
        else:
            from agent_framework.openai import OpenAIChatClient

            # Explicit empty-key provider avoids ambient OPENAI_API_KEY authentication.
            # Public HTTPS services are allowed; auth is an operator policy choice.
            api_key = required_env(settings.token_env) if settings.token_env else _no_api_key
            if settings.azure_scope:
                from azure.identity.aio import DefaultAzureCredential, get_bearer_token_provider

                credential = await stack.enter_async_context(DefaultAzureCredential())
                api_key = get_bearer_token_provider(credential, settings.azure_scope)
            http_client = await stack.enter_async_context(AsyncOpenAI(
                api_key=api_key, base_url=endpoint.removesuffix("/chat/completions") + "/",
                organization="", project="", admin_api_key="",
                timeout=timeout, max_retries=0, http_client=transport,
            ))
            client = OpenAIChatClient(async_client=http_client, model_id=deployment)
        agent = await stack.enter_async_context(client.as_agent(
            name="byoe-hosted-agent", instructions=instructions, default_options=options,
        ))
        yield agent


async def serve(host: str = "127.0.0.1", port: int = 8090) -> None:
    """Serve adapter.app; deployers must explicitly select host='0.0.0.0'."""
    import uvicorn

    config, instructions = load_hosting_config()
    async with hosted_agent(config, instructions) as agent:
        adapter = create_adapter(agent)
        try:
            # Do not call the SDK .run() convenience method (auto tracing + public bind).
            await uvicorn.Server(uvicorn.Config(adapter.app, host=host, port=port)).serve()
        finally:
            await adapter.credentials.close()