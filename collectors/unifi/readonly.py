"""Read-only UniFi Network Integration API allowlist.

Only documented GET paths. No adopt, actions, port control, or unadopt.
"""

from __future__ import annotations

import re

# Paths are relative to the Integration API base URL (runtime {PREFIX}_BASE_URL).
UNIFI_GET_ALLOWLIST: tuple[re.Pattern[str], ...] = (
    re.compile(r"^/v1/info$"),
    re.compile(r"^/v1/sites$"),
    re.compile(r"^/v1/sites/[0-9a-fA-F-]{36}/devices$"),
    re.compile(r"^/v1/sites/[0-9a-fA-F-]{36}/devices/[0-9a-fA-F-]{36}$"),
)

COLLECTOR_VERSION = "0.1.0"


def unifi_get_allowed(path: str) -> bool:
    clean = path.split("?", 1)[0]
    return any(pat.match(clean) for pat in UNIFI_GET_ALLOWLIST)
