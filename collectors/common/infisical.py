"""Cofre Central (Infisical) secret client for device credentials.

Read-only runtime resolution of device secrets referenced by `secret_prefix`.
Never logs secret values, host IPs, or usernames.

Layout this client understands:
- Universal Auth machine identity:
    INFISICAL_URL (https://cofre.madalena.3mstecnologia.com)
    INFISICAL_CLIENT_ID / INFISICAL_CLIENT_SECRET
- Project: INFISICAL_PROJECT_ID (optional). If unset, the first project is
  used as fallback; for Madalena set it explicitly.
- Environment: INFISICAL_ENV (default "production").
- Device credentials may live under ANY folder (root, /managed, /owner-only, ...).
  This client enumerates folders recursively and builds a key→value map so a
  `secret_prefix` like ``OLT_UNIPLAC`` maps to ``OLT_UNIPLAC_HOST`` wherever it lives.

Secret values are never returned in logs, errors, or HTTP debug output.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache
from typing import Optional

_DEFAULT_URL = "https://cofre.madalena.3mstecnologia.com"
_DEFAULT_ENV = "production"


class InfisicalClientError(Exception):
    """Infisical connection/authentication failure. Message is safe to log."""


class InfisicalClient:
    """Minimal read-only client for a self-hosted Infisical instance."""

    def __init__(
        self,
        *,
        url: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        project_id: Optional[str] = None,
        environment: Optional[str] = None,
        connect_timeout: int = 15,
    ) -> None:
        self.url = (url or os.getenv("INFISICAL_URL") or _DEFAULT_URL).rstrip("/")
        self.client_id = client_id or os.getenv("INFISICAL_CLIENT_ID") or ""
        self.client_secret = client_secret or os.getenv("INFISICAL_CLIENT_SECRET") or ""
        self.project_id = project_id or os.getenv("INFISICAL_PROJECT_ID") or ""
        self.environment = environment or os.getenv("INFISICAL_ENV") or _DEFAULT_ENV
        self._timeout = connect_timeout

    # ---- auth ----
    def _login(self) -> str:
        if not self.client_id or not self.client_secret:
            raise InfisicalClientError("infisical identity not configured")
        body = json.dumps(
            {"clientId": self.client_id, "clientSecret": self.client_secret}
        ).encode("utf-8")
        req = urllib.request.Request(
            self.url + "/api/v1/auth/universal-auth/login",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise InfisicalClientError("infisical auth http error") from exc
        except urllib.error.URLError as exc:
            raise InfisicalClientError("infisical auth unreachable") from exc
        token = (data.get("accessToken") or "").strip()
        if not token:
            raise InfisicalClientError("infisical auth returned no token")
        return token

    def _resolve_project_id(self, token: str) -> str:
        if self.project_id:
            return self.project_id
        req = urllib.request.Request(
            self.url + "/api/v1/projects",
            headers={"Authorization": f"Bearer {token}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            raise InfisicalClientError("infisical project lookup failed") from exc
        projects = data.get("projects") or []
        if not projects:
            raise InfisicalClientError("infisical project not found")
        return str(projects[0]["id"])

    def _get(self, token: str, path: str, query: dict[str, str]):
        q = urllib.parse.urlencode(query)
        req = urllib.request.Request(
            self.url + path + "?" + q,
            headers={"Authorization": f"Bearer {token}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise InfisicalClientError(f"infisical {path} http error") from exc
        except urllib.error.URLError as exc:
            raise InfisicalClientError("infisical unreachable") from exc

    def _list_folders(self, token: str, pid: str, folder_path: str) -> list[str]:
        data = self._get(
            token,
            "/api/v1/folders",
            {"workspaceId": pid, "environment": self.environment, "path": folder_path},
        )
        return [str(f.get("name", "")) for f in (data.get("folders") or []) if f.get("name")]

    def _secrets_in_folder(self, token: str, pid: str, folder_path: str) -> dict[str, str]:
        data = self._get(
            token,
            "/api/v3/secrets/raw",
            {
                "workspaceId": pid,
                "environment": self.environment,
                "secretPath": folder_path,
                "includeImports": "true",
            },
        )
        out: dict[str, str] = {}
        for secret in data.get("secrets") or []:
            key = secret.get("secretKey") or secret.get("key")
            value = secret.get("secretValue")
            if key and isinstance(value, str) and value:
                out[str(key)] = value
        return out

    def fetch_all(self) -> dict[str, str]:
        """Return {SECRET_KEY: value} for the whole environment. Values are internal."""
        token = self._login()
        pid = self._resolve_project_id(token)
        values: dict[str, str] = {}
        stack = ["/"]
        for folder in stack:
            for key, value in self._secrets_in_folder(token, pid, folder).items():
                values[key] = value
            for name in self._list_folders(token, pid, folder):
                stack.append(f"{folder.rstrip('/')}/{name}")
        if not values:
            raise InfisicalClientError("infisical returned no secrets")
        return values

    def fetch_key(self, key: str, folder_hint: str = "") -> Optional[str]:
        values = fetch_all_cached(self)
        return values.get(key)


_all_values: Optional[dict[str, str]] = None
_all_errors: Optional[str] = None


def fetch_all_cached(client: InfisicalClient) -> dict[str, str]:
    """Module-level cache of a full environment fetch (one HTTP auth per process)."""
    global _all_values, _all_errors
    if _all_values is None:
        try:
            _all_values = client.fetch_all()
        except InfisicalClientError as exc:
            _all_errors = str(exc)
            _all_values = {}
    return _all_values


def reset_cache() -> None:
    global _all_values, _all_errors
    _all_values = None
    _all_errors = None


@lru_cache(maxsize=1)
def _client_from_env() -> InfisicalClient:
    return InfisicalClient()


def last_error() -> Optional[str]:
    return _all_errors