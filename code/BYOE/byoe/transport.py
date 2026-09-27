"""Bounded JSON HTTP transport; URLs and credentials are environment references."""

import ipaddress
import math
import os
from contextlib import ExitStack
from urllib.parse import urlsplit

import httpx

from byoe.contracts import HTTPConfig, strict_json_loads

MAX_RESPONSE_BYTES = 1024 * 1024


def endpoint_from_env(name: str) -> str:
    endpoint = os.environ.get(name, "")
    parsed = urlsplit(endpoint)
    if (not parsed.hostname or parsed.username is not None or parsed.password is not None
            or parsed.fragment or parsed.query or any(ord(c) <= 32 for c in endpoint)):
        raise ValueError("Invalid endpoint")
    # Deliberately reject DNS names, including localhost, for plaintext transport.
    loopback = False
    try:
        loopback = ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        pass
    if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
        raise ValueError("HTTPS or literal loopback HTTP required")
    return endpoint


def post_json(config: dict, body: dict, timeout: float):
    """Return parsed JSON; caller must impose a process-level total deadline."""
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Invalid timeout")
    settings = HTTPConfig.model_validate(config)
    endpoint = endpoint_from_env(settings.endpoint_env)
    headers = {"Accept": "application/json"}
    with ExitStack() as stack:
        if settings.token_env:
            token = os.environ.get(settings.token_env)
            if not token:
                raise ValueError("Missing token")
            headers["Authorization"] = "Bearer " + token
        elif settings.azure_scope:
            from azure.identity import DefaultAzureCredential

            credential = DefaultAzureCredential()
            stack.callback(credential.close)
            headers["Authorization"] = "Bearer " + credential.get_token(
                settings.azure_scope
            ).token
        client = stack.enter_context(httpx.Client(
            timeout=float(timeout), follow_redirects=False, trust_env=False
        ))
        with client.stream("POST", endpoint, json=body, headers=headers) as response:
            response.raise_for_status()  # Includes redirects: never forward credentials.
            content = bytearray()
            for chunk in response.iter_bytes(chunk_size=65536):
                content.extend(chunk)
                if len(content) > MAX_RESPONSE_BYTES:
                    raise ValueError("Response too large")
            return strict_json_loads(bytes(content))