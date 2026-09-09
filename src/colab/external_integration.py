"""Controlled, read-only external integration boundary.

The gateway deliberately has no write/execute capability. Connectors are explicit,
allow-listed, HTTPS-only, path-scoped and bounded by timeout/response size.
Secrets are resolved from environment variables and are never returned in records.
"""
from __future__ import annotations

import ipaddress
import json
import os
import socket
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen
from uuid import UUID, uuid4


class ExternalIntegrationError(RuntimeError):
    """Raised when a controlled external integration request is rejected or fails."""


@dataclass(frozen=True)
class ConnectorDefinition:
    name: str
    base_url: str
    allowed_paths: tuple[str, ...] = ("/",)
    secret_env: str | None = None
    timeout_seconds: float = 5.0
    max_response_bytes: int = 1_000_000
    description: str = ""

    def __post_init__(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("external connectors must use an HTTPS base URL")
        if not self.name or not self.name.replace("-", "").replace("_", "").isalnum():
            raise ValueError("connector name must be alphanumeric, '-' or '_'")
        if not self.allowed_paths or any(not path.startswith("/") or ".." in path.split("/") for path in self.allowed_paths):
            raise ValueError("allowed_paths must contain safe absolute paths")
        if not 0.1 <= self.timeout_seconds <= 30:
            raise ValueError("timeout_seconds must be between 0.1 and 30")
        if not 1_024 <= self.max_response_bytes <= 10_000_000:
            raise ValueError("max_response_bytes must be between 1024 and 10000000")


@dataclass(frozen=True)
class IntegrationAudit:
    request_id: UUID
    connector: str
    path: str
    status_code: int | None
    success: bool
    timestamp: datetime
    error: str | None = None


class ExternalIntegrationRegistry:
    """Allow-listed registry and execution boundary for read-only external data."""

    FORBIDDEN_NAMES = {"trade", "trading", "order", "orders", "execute", "execution", "withdraw", "transfer"}

    def __init__(self, transport: Callable[..., bytes] | None = None) -> None:
        self._connectors: dict[str, ConnectorDefinition] = {}
        self._audit: list[IntegrationAudit] = []
        self._transport = transport or self._https_get

    def register(self, definition: ConnectorDefinition) -> None:
        lowered = definition.name.lower()
        if any(token in lowered for token in self.FORBIDDEN_NAMES):
            raise ExternalIntegrationError("execution-capable connector names are prohibited")
        if definition.name in self._connectors:
            raise ExternalIntegrationError(f"connector already registered: {definition.name}")
        self._connectors[definition.name] = definition

    def list_connectors(self) -> tuple[ConnectorDefinition, ...]:
        return tuple(self._connectors.values())

    def get(self, name: str) -> ConnectorDefinition:
        try:
            return self._connectors[name]
        except KeyError as exc:
            raise ExternalIntegrationError(f"unknown connector: {name}") from exc

    def fetch_json(self, connector: str, path: str = "/", query: Mapping[str, str] | None = None) -> tuple[UUID, dict[str, object] | list[object]]:
        definition = self.get(connector)
        self._validate_path(definition, path)
        request_id = uuid4()
        target = urljoin(definition.base_url.rstrip("/") + "/", path.lstrip("/"))
        parsed = urlparse(target)
        if parsed.scheme != "https" or parsed.hostname != urlparse(definition.base_url).hostname:
            raise ExternalIntegrationError("request target is outside connector host allow-list")
        if query and any("=" in key or "&" in key for key in query):
            raise ExternalIntegrationError("invalid query parameter")
        try:
            payload = self._transport(definition, target, query or {})
            if len(payload) > definition.max_response_bytes:
                raise ExternalIntegrationError("external response exceeds configured size limit")
            data = json.loads(payload.decode("utf-8"))
            if not isinstance(data, (dict, list)):
                raise ExternalIntegrationError("external response must be a JSON object or array")
        except ExternalIntegrationError as exc:
            self._record(request_id, connector, path, None, False, str(exc))
            raise
        except (HTTPError, URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._record(request_id, connector, path, getattr(exc, "code", None), False, type(exc).__name__)
            raise ExternalIntegrationError(f"external request failed: {type(exc).__name__}") from exc
        self._record(request_id, connector, path, 200, True, None)
        return request_id, data

    def audit(self) -> tuple[IntegrationAudit, ...]:
        return tuple(self._audit)

    @staticmethod
    def _validate_path(definition: ConnectorDefinition, path: str) -> None:
        if not path.startswith("/") or ".." in path.split("/"):
            raise ExternalIntegrationError("unsafe external path")
        if not any(path == allowed or path.startswith(allowed.rstrip("/") + "/") for allowed in definition.allowed_paths):
            raise ExternalIntegrationError("path is not allow-listed for this connector")

    @staticmethod
    def _https_get(definition: ConnectorDefinition, target: str, query: Mapping[str, str]) -> bytes:
        parsed = urlparse(target)
        host = parsed.hostname
        if host is None:
            raise ExternalIntegrationError("connector has no hostname")
        try:
            addresses = {item[4][0] for item in socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)}
        except socket.gaierror as exc:
            raise ExternalIntegrationError("connector hostname could not be resolved") from exc
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
                raise ExternalIntegrationError("private or non-public connector address is prohibited")
        final_url = target + ("?" + urlencode(query) if query else "")
        headers = {"Accept": "application/json", "User-Agent": "Colab-Controlled-Integration/1.0"}
        secret = os.getenv(definition.secret_env) if definition.secret_env else None
        if secret:
            headers["Authorization"] = f"Bearer {secret}"
        request = Request(final_url, headers=headers, method="GET")
        with urlopen(request, timeout=definition.timeout_seconds) as response:
            return cast(bytes, response.read(definition.max_response_bytes + 1))

    def _record(self, request_id: UUID, connector: str, path: str, status_code: int | None, success: bool, error: str | None) -> None:
        self._audit.append(IntegrationAudit(request_id, connector, path, status_code, success, datetime.now(UTC), error))
