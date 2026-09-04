"""HTTP GET transport for UniFi Network Integration API.

Never logs API keys. Only GET. Paths must match the read-only allowlist.
"""

from __future__ import annotations

from typing import Any, Optional, Protocol

import httpx

from collectors.common.secrets import DeviceSecrets
from collectors.common.transport import ReadOnlyViolation, TransportError, sanitize_error
from collectors.unifi.readonly import unifi_get_allowed


class UnifiJsonClient(Protocol):
    def get_json(self, path: str, params: Optional[dict[str, Any]] = None) -> Any:
        ...


class MemoryUnifiClient:
    """Fixture-backed client for tests. Keys are path strings without query."""

    def __init__(self, responses: dict[str, Any], failures: Optional[set[str]] = None):
        self.responses = responses
        self.failures = failures or set()
        self.calls: list[str] = []

    def get_json(self, path: str, params: Optional[dict[str, Any]] = None) -> Any:
        if not unifi_get_allowed(path):
            raise ReadOnlyViolation(f"unifi path not allowlisted: {path}")
        self.calls.append(path)
        if path in self.failures:
            raise TransportError("unifi GET failed")
        if path not in self.responses:
            raise TransportError("unifi GET not found")
        return self.responses[path]


class UnifiHttpClient:
    def __init__(self, secrets: DeviceSecrets, *, timeout_sec: float = 30.0):
        self._base = (secrets.base_url or "").rstrip("/")
        self._api_key = secrets.api_key or ""
        self._timeout = timeout_sec
        verify = True
        if secrets.verify_tls is False:
            verify = False
        self._verify = verify

    def get_json(self, path: str, params: Optional[dict[str, Any]] = None) -> Any:
        if not unifi_get_allowed(path):
            raise ReadOnlyViolation(f"unifi path not allowlisted: {path}")
        if not self._base or not self._api_key:
            raise TransportError("unifi secrets unavailable")
        url = f"{self._base}{path}"
        try:
            with httpx.Client(timeout=self._timeout, verify=self._verify) as client:
                response = client.get(
                    url,
                    params=params,
                    headers={"X-API-Key": self._api_key, "Accept": "application/json"},
                )
        except httpx.HTTPError as exc:
            raise TransportError(sanitize_error(f"unifi transport: {exc}")) from None
        if response.status_code >= 400:
            raise TransportError(f"unifi HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError as exc:
            raise TransportError("unifi response was not JSON") from exc
