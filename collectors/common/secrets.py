"""Resolve device credentials from an external secret provider reference.

Never logs secret values. Supports two providers:
- ``env``        : read ``{PREFIX}_*``` variables from os.environ (runtime sync).
- ``infisical``  : read ``{PREFIX}_*``` keys from the Cofre Central (Infisical)
                   at runtime, with os.environ as an override/fallback.

Device credentials are only ever held in memory of this process and injected
into the chosen transport; they are never persisted, logged, or returned by the
API/MCP. Host values are treated as secrets too (not committed to the repo).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Optional

from collectors.common import infisical
from collectors.common.infisical import InfisicalClientError


@dataclass
class DeviceSecrets:
    host: str = ""
    username: str = ""
    password: str = ""
    port: int = 22
    protocol: str = "ssh"
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    site: Optional[str] = None
    verify_tls: bool = True
    tls_ca_file: Optional[str] = None
    tls_server_name: Optional[str] = None


def _field(
    secret_prefix: str,
    suffix: str,
    secret_map: dict[str, str],
    provide_env: Callable[[str], Optional[str]],
) -> str:
    """Prefer env (explicit runtime sync), then Cofre map. Returns '' when absent."""
    value = (provide_env(f"{secret_prefix}_{suffix}") or "").strip()
    if value:
        return value
    return (secret_map.get(f"{secret_prefix}_{suffix}") or "").strip()


def _load_infisical_map() -> dict[str, str]:
    try:
        return infisical.fetch_all_cached(infisical.InfisicalClient())
    except InfisicalClientError:
        return {}


def resolve_secrets(secret_provider: str, secret_prefix: str) -> Optional[DeviceSecrets]:
    """Resolve DeviceSecrets by provider+prefix. Returns None when unusable.

    Expected env keys / Cofre keys (examples only — never commit real values):
      {prefix}_HOST       (alias {prefix}_IP for OLT-style references)
      {prefix}_USERNAME
      {prefix}_PASSWORD
      {prefix}_SSH_PORT   (or {prefix}_PORT)
      {prefix}_PROTOCOL   (ssh | telnet | https)
      {prefix}_BASE_URL   (UniFi Integration API root)
      {prefix}_API_KEY
      {prefix}_SITE       (optional UniFi site UUID)
      {prefix}_TLS_CA     (optional PEM CA/chain file for TLS verification)
      {prefix}_TLS_SERVER_NAME (DNS SAN used when BASE_URL is an IP)
      {prefix}_VERIFY_TLS (true|false, default true; UniFi-only lab exception)
    Global (Compose):
      NI_TLS_CA_FILE      (container path; used when per-prefix TLS_CA is unset)
      NI_SSH_KNOWN_HOSTS  (container path to SSH known_hosts)
    """
    if not secret_prefix:
        return None
    provider = (secret_provider or "env").strip().lower()
    secret_map: dict[str, str] = {}
    if provider == "infisical":
        secret_map = _load_infisical_map()

    def get(suffix: str) -> str:
        return _field(secret_prefix, suffix, secret_map, os.getenv)

    host = get("HOST") or get("IP")
    user = get("USERNAME")
    password = get("PASSWORD")
    port_raw = get("SSH_PORT") or get("PORT") or "22"
    protocol = (get("PROTOCOL") or "").strip().lower()
    api_key = get("API_KEY") or None
    base_url = (get("BASE_URL") or "").rstrip("/") or None
    site = get("SITE") or None
    verify_raw = (get("VERIFY_TLS") or "true").strip().lower()
    verify_tls = verify_raw not in {"0", "false", "no"}
    tls_ca = (
        (get("TLS_CA") or "").strip()
        or (get("CA_FILE") or "").strip()
        or (os.getenv("NI_TLS_CA_FILE") or "").strip()
        or None
    )
    tls_server_name = (get("TLS_SERVER_NAME") or "").strip() or None
    try:
        port = int(port_raw)
    except ValueError:
        return None

    if api_key and (base_url or host):
        url = base_url or (f"https://{host}" if host else None)
        if not url:
            return None
        return DeviceSecrets(
            host=host,
            username=user,
            password=password,
            port=port,
            protocol=protocol or "https",
            api_key=api_key,
            base_url=url,
            site=site,
            verify_tls=verify_tls,
            tls_ca_file=tls_ca,
            tls_server_name=tls_server_name,
        )

    if not host or not user or not password:
        return None
    return DeviceSecrets(
        host=host,
        username=user,
        password=password,
        port=port,
        protocol=protocol or "ssh",
        site=site,
        verify_tls=verify_tls,
        tls_ca_file=tls_ca,
        tls_server_name=tls_server_name,
    )