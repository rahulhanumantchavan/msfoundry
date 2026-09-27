"""Explicit model inference; no agent creation, fallback, or import-time I/O.

Python entrypoints are trusted code, imported only by complete(). Callers needing
a hard total deadline must use the evaluator/target subprocess boundary.
"""

import importlib
import math
import os
from contextlib import ExitStack

from byoe.contracts import ModelConfig
from byoe.transport import endpoint_from_env, post_json


def validate_timeout(timeout: float) -> float:
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Invalid timeout")
    return float(timeout)


def validate_model(config: dict) -> ModelConfig:
    """Reject irrelevant provider settings rather than silently ignoring them."""
    try:
        settings = ModelConfig.model_validate(config)
        fields = ("endpoint_env", "model_env", "token_env", "azure_scope")
        if settings.kind == "python":
            if any(getattr(settings, field) is not None for field in fields):
                raise ValueError
        elif settings.entrypoint is not None:
            raise ValueError
        if settings.kind == "foundry_model" and (
            settings.token_env is not None or settings.azure_scope is not None
        ):
            raise ValueError
        return settings
    except Exception:
        raise ValueError("Invalid or unsupported model configuration") from None


def required_env(name: str | None) -> str:
    value = os.environ.get(name, "") if name else ""
    if not value.strip():
        raise ValueError("Required model environment variable is missing or blank")
    return value


def model_endpoint(settings: ModelConfig) -> str:
    endpoint = endpoint_from_env(settings.endpoint_env)
    if settings.kind == "openai_chat" and not endpoint.endswith("/chat/completions"):
        raise ValueError("openai_chat endpoint must end exactly with /chat/completions")
    if settings.kind == "foundry_model" and not endpoint.startswith("https://"):
        raise ValueError("foundry_model requires an HTTPS project endpoint")
    return endpoint


def nonempty_text(value) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError("Provider returned no nonempty response text")
    return value


def responses_text(response, *, require_status: bool = False) -> str:
    """Parse SDK or wire Responses output, rejecting errors and partial results."""
    shortcut = getattr(response, "output_text", None)
    if not isinstance(response, dict) and hasattr(response, "model_dump"):
        response = response.model_dump()
    if type(response) is not dict:
        raise ValueError("Malformed Responses result")

    def check(value, required=False):
        if value.get("error") is not None or value.get("type") == "response.error":
            raise ValueError("Responses request failed")
        if (required or "status" in value) and value.get("status") != "completed":
            raise ValueError("Responses request did not complete")
        if value.get("incomplete_details") is not None:
            raise ValueError("Responses request is incomplete")

    check(response)
    if "response" in response:
        if response.get("type") not in (None, "response.completed"):
            raise ValueError("Unexpected Responses event")
        response = response["response"]
        if type(response) is not dict:
            raise ValueError("Malformed nested Responses result")
        shortcut = None
    check(response, require_status)
    output = response.get("output")
    parts = []
    if output is not None:
        if type(output) is not list:
            raise ValueError("Malformed Responses output")
        for item in output:
            if type(item) is not dict:
                raise ValueError("Malformed Responses output item")
            check(item)
            if item.get("type") != "message":
                continue  # Reasoning/tool items are not answer text.
            content = item.get("content")
            if type(content) is not list:
                raise ValueError("Malformed message content")
            for block in content:
                if type(block) is not dict:
                    raise ValueError("Malformed message content block")
                if block.get("type") == "output_text":
                    parts.append(nonempty_text(block.get("text")))
    text = response.get("output_text", shortcut)
    if text is not None:
        return nonempty_text(text)
    return nonempty_text("".join(parts))


def complete(config: dict, messages: list[dict], timeout: float) -> str:
    """Infer using the configured model. Python providers MUST be trusted code.

    openai_chat accepts no auth (including explicitly public HTTPS services),
    token_env bearer auth, or azure_scope identity auth. foundry_model uses only
    SDK-managed Azure identity. Exception details are deliberately not exposed.
    """
    settings = validate_model(config)
    timeout = validate_timeout(timeout)
    if type(messages) is not list or not messages or any(type(m) is not dict for m in messages):
        raise ValueError("messages must be a nonempty list of objects")
    try:
        if settings.kind == "python":
            module, name = settings.entrypoint.split(":")
            function = getattr(importlib.import_module(module), name)
            return nonempty_text(function(messages, timeout))
        endpoint = model_endpoint(settings)
        deployment = required_env(settings.model_env)
        if settings.kind == "openai_chat":
            result = post_json(
                {"endpoint_env": settings.endpoint_env, "token_env": settings.token_env,
                 "azure_scope": settings.azure_scope},
                {"model": deployment, "messages": messages}, timeout,
            )
            if type(result) is not dict or result.get("error") is not None:
                raise ValueError("Model request failed")
            return nonempty_text(result["choices"][0]["message"]["content"])

        from azure.ai.projects import AIProjectClient
        from azure.identity import DefaultAzureCredential
        from openai import DefaultHttpxClient

        with ExitStack() as stack:
            credential = stack.enter_context(DefaultAzureCredential())
            project = stack.enter_context(AIProjectClient(endpoint=endpoint, credential=credential))
            transport = stack.enter_context(DefaultHttpxClient(
                timeout=timeout, follow_redirects=False, trust_env=False,
            ))
            client = stack.enter_context(project.get_openai_client(http_client=transport))
            result = client.with_options(timeout=timeout, max_retries=0).responses.create(
                model=deployment, input=messages, store=False,
            )
            return responses_text(result)
    except Exception:
        raise ValueError("Model completion failed") from None