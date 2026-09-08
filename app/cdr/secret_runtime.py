from __future__ import annotations

import os
from pathlib import Path

_SECRET_ENV_FILE = Path(os.getenv("INFISICAL_ENV_FILE", "/run/secrets/infisical.env"))
_LOADED = False


def hydrate_infisical_identity() -> None:
    global _LOADED
    if _LOADED:
        return
    if not _SECRET_ENV_FILE.exists():
        _LOADED = True
        return
    for line in _SECRET_ENV_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in os.environ or not os.environ.get(key):
            os.environ[key] = value.strip()
    _LOADED = True
