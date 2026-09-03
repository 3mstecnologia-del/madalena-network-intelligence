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
    host: str
    username: str
    password: str
    port: int = 22
    protocol: str = "ssh"


def resolve_secrets(secret_provider: str, secret_prefix: str) -> Optional[DeviceSecrets]:
    """Map SECRET_PREFIX_* env keys conceptually used with Infisical sync.

    Expected env keys (examples only — never commit real values):
      {prefix}_HOST
      {prefix}_USERNAME
      {prefix}_PASSWORD
      {prefix}_SSH_PORT   (or {prefix}_PORT)
      {prefix}_PROTOCOL   (ssh | telnet)
    """
    if not secret_prefix:
        return None
    host = os.getenv(f"{secret_prefix}_HOST")
    user = os.getenv(f"{secret_prefix}_USERNAME")
    password = os.getenv(f"{secret_prefix}_PASSWORD")
    port_raw = os.getenv(f"{secret_prefix}_SSH_PORT") or os.getenv(f"{secret_prefix}_PORT") or "22"
    protocol = (os.getenv(f"{secret_prefix}_PROTOCOL") or "ssh").strip().lower()
    if not host or not user or not password:
        return None
    try:
        port = int(port_raw)
    except ValueError:
        return None
    return DeviceSecrets(
        host=host, username=user, password=password, port=port, protocol=protocol
    )
