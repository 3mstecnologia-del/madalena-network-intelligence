from __future__ import annotations

import base64
import hmac
from dataclasses import dataclass

from fastapi import Request

from app.core.config import get_settings
from app.cdr.secret_runtime import hydrate_infisical_identity
from collectors.common.infisical import InfisicalClient, fetch_all_cached


@dataclass(slots=True)
class BasicIdentity:
    authenticated: bool
    username: str


def _constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def _portal_secret_map() -> dict[str, str]:
    hydrate_infisical_identity()
    try:
        return fetch_all_cached(InfisicalClient())
    except Exception:
        return {}


def _portal_value(*keys: str) -> str:
    values = _portal_secret_map()
    for key in keys:
        value = (values.get(key) or "").strip()
        if value:
            return value
    return ""


def get_basic_identity(request: Request) -> BasicIdentity:
    settings = get_settings()
    expected_username = _portal_value("CDR_PORTAL_USER", "CDR_PORTAL_USERNAME") or settings.cdr_portal_username
    expected_password = _portal_value("CDR_PORTAL_PASSWORD") or settings.cdr_portal_password
    header = request.headers.get("Authorization", "")
    if not header.startswith("Basic "):
        return BasicIdentity(False, "")
    try:
        decoded = base64.b64decode(header.split(" ", 1)[1]).decode("utf-8")
    except Exception:
        return BasicIdentity(False, "")
    if ":" not in decoded:
        return BasicIdentity(False, "")
    username, password = decoded.split(":", 1)
    if not expected_username or not expected_password:
        return BasicIdentity(False, "")
    if not _constant_time_equals(username, expected_username):
        return BasicIdentity(False, "")
    if not _constant_time_equals(password, expected_password):
        return BasicIdentity(False, "")
    return BasicIdentity(True, username)
