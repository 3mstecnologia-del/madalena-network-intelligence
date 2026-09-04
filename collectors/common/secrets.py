"""Resolve device credentials from an external secret provider reference.

Never logs secret values. Phase 1 returns None unless env placeholders exist
for local dry-run without real lab access.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


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


def resolve_secrets(secret_provider: str, secret_prefix: str) -> Optional[DeviceSecrets]:
    """Map SECRET_PREFIX_* env keys conceptually used with Infisical sync.

    Expected env keys (examples only — never commit real values):
      {prefix}_HOST
      {prefix}_USERNAME
      {prefix}_PASSWORD
      {prefix}_SSH_PORT   (or {prefix}_PORT)
      {prefix}_PROTOCOL   (ssh | telnet | https)
      {prefix}_BASE_URL   (UniFi Integration API root)
      {prefix}_API_KEY
      {prefix}_SITE       (optional UniFi site UUID)
      {prefix}_TLS_CA     (optional PEM CA/chain file for TLS verification)
      {prefix}_TLS_SERVER_NAME (DNS SAN used for TLS hostname checks when BASE_URL is an IP)
      {prefix}_VERIFY_TLS (true|false, default true; UniFi-only lab exception when false)
    Global (Compose):
      NI_TLS_CA_FILE      (container path; used when per-prefix TLS_CA is unset)
      NI_SSH_KNOWN_HOSTS  (container path to SSH known_hosts; default /run/ssh/known_hosts)
    """
    if not secret_prefix:
        return None
    host = os.getenv(f"{secret_prefix}_HOST") or ""
    user = os.getenv(f"{secret_prefix}_USERNAME") or ""
    password = os.getenv(f"{secret_prefix}_PASSWORD") or ""
    port_raw = os.getenv(f"{secret_prefix}_SSH_PORT") or os.getenv(f"{secret_prefix}_PORT") or "22"
    protocol = (os.getenv(f"{secret_prefix}_PROTOCOL") or "").strip().lower()
    api_key = os.getenv(f"{secret_prefix}_API_KEY") or None
    base_url = os.getenv(f"{secret_prefix}_BASE_URL") or None
    site = os.getenv(f"{secret_prefix}_SITE") or None
    verify_raw = (os.getenv(f"{secret_prefix}_VERIFY_TLS") or "true").strip().lower()
    verify_tls = verify_raw not in {"0", "false", "no"}
    tls_ca = (
        os.getenv(f"{secret_prefix}_TLS_CA")
        or os.getenv(f"{secret_prefix}_CA_FILE")
        or os.getenv("NI_TLS_CA_FILE")
        or None
    )
    if tls_ca:
        tls_ca = tls_ca.strip() or None
    tls_server_name = (os.getenv(f"{secret_prefix}_TLS_SERVER_NAME") or "").strip() or None
    try:
        port = int(port_raw)
    except ValueError:
        return None

    if api_key and (base_url or host):
        url = (base_url or "").rstrip("/")
        if not url and host:
            url = f"https://{host}"
        return DeviceSecrets(
            host=host,
            username=user,
            password=password,
            port=port,
            protocol=protocol or "https",
            api_key=api_key,
            base_url=url or None,
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
