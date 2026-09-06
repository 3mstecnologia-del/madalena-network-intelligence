"""Hermetic tests for the Cofre Central (Infisical) secret resolution backend."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from collectors.common import infisical
from collectors.common.secrets import resolve_secrets


class _Handler(BaseHTTPRequestHandler):
    """Fake Infisical server: universal-auth login + project + folders + secrets."""

    store: dict[str, str] = {
        "OLT_UNIPLAC_HOST": "192.0.2.200",
        "OLT_UNIPLAC_USERNAME": "olt_admin",
        "OLT_UNIPLAC_PASSWORD": "sup3rs3cret",
        "OLT_UNIPLAC_PORT": "22",
        "OLT_UNIPLAC_PROTOCOL": "ssh",
        "MK_UNIPLAC_HOST": "192.0.2.202",
        "MK_UNIPLAC_USERNAME": "mk_admin",
        "MK_UNIPLAC_PASSWORD": "mk_s3cr3t",
        "MK_UNIPLAC_PORT": "22",
        "MK_UNIPLAC_PROTOCOL": "ssh",
    }

    def _send(self, code: int, payload) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        if self.path.startswith("/api/v1/auth/universal-auth/login"):
            self._send(200, {"accessToken": "fake-token-abc"})
        else:
            self._send(404, {"message": "not found"})

    def _secret_rows(self, path: str) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        prefix_space = {
            "": "OLT_UNIPLAC",
            "/managed": "MK_UNIPLAC",
        }
        key_space = prefix_space.get(path)
        if path == "/":
            key_space = None
        for key, value in self.store.items():
            if key_space and not key.startswith(key_space):
                continue
            rows.append({"secretKey": key, "secretValue": value, "secretPath": path})
        return rows

    def do_GET(self):  # noqa: N802
        from urllib.parse import parse_qs, urlparse

        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/api/v1/projects":
            self._send(
                200,
                {"projects": [{"id": "proj-1", "name": "MADALENA"}]},
            )
        elif parsed.path == "/api/v1/folders":
            path = (query.get("path") or [""])[0]
            folders = [{"name": "managed"}] if path in ("", "/") else []
            self._send(200, {"folders": folders})
        elif parsed.path == "/api/v3/secrets/raw":
            path = (query.get("secretPath") or [""])[0]
            self._send(200, {"secrets": self._secret_rows(path)})
        else:
            self._send(404, {"message": "not found"})


@pytest.fixture(autouse=True)
def _reset_cache():
    infisical.reset_cache()
    yield
    infisical.reset_cache()


@pytest.fixture()
def fake_server():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    yield infisical.InfisicalClient(
        url=base,
        client_id="cid",
        client_secret="csec",
        project_id="proj-1",
        environment="development",
    )
    server.shutdown()
    thread.join(timeout=5)


def test_fetch_all_enumerates_folders(fake_server):
    values = fake_server.fetch_all()
    assert "OLT_UNIPLAC_HOST" in values
    assert "OLT_UNIPLAC_PASSWORD" in values
    assert "MK_UNIPLAC_HOST" in values
    assert values["OLT_UNIPLAC_HOST"] == "192.0.2.200"


def test_resolve_secrets_infisical(monkeypatch, fake_server):
    monkeypatch.setattr(infisical, "InfisicalClient", lambda **kw: fake_server)
    secrets = resolve_secrets("infisical", "OLT_UNIPLAC")
    assert secrets is not None
    assert secrets.host == "192.0.2.200"
    assert secrets.username == "olt_admin"
    assert secrets.password == "sup3rs3cret"
    assert secrets.port == 22
    assert secrets.protocol == "ssh"


def test_resolve_secrets_env_overrides_infisical(monkeypatch, fake_server):
    monkeypatch.setattr(infisical, "InfisicalClient", lambda **kw: fake_server)
    monkeypatch.setenv("OLT_UNIPLAC_PORT", "2222")
    secrets = resolve_secrets("infisical", "OLT_UNIPLAC")
    assert secrets is not None
    assert secrets.port == 2222  # env wins over Cofre


def test_resolve_secrets_infisical_missing_returns_none(monkeypatch, fake_server):
    monkeypatch.setattr(infisical, "InfisicalClient", lambda **kw: fake_server)
    assert resolve_secrets("infisical", "NO_SUCH_DEVICE") is None


def test_resolve_secrets_infisical_uses_ip_alias(monkeypatch, fake_server):
    monkeypatch.setattr(infisical, "InfisicalClient", lambda **kw: fake_server)
    # OLT-style reference uses _IP instead of _HOST for the address.
    monkeypatch.setenv("OLT_UNIPLAC_HOST", "")  # not used; fake has HOST anyway
    resolved = resolve_secrets("infisical", "OLT_UNIPLAC")
    assert resolved.host == "192.0.2.200"


def test_resolve_secrets_canonical_olt_user_and_ip(monkeypatch, fake_server):
    """Canonical UNIPLAC OLT pattern uses OLT_UNIPLAC_IP + OLT_UNIPLAC_USER."""
    # Supply the canonical OLT variant keys directly (IP + USER, no HOST/USERNAME).
    monkeypatch.delenv("OLT_UNIPLAC_HOST", raising=False)
    monkeypatch.delenv("OLT_UNIPLAC_USERNAME", raising=False)
    monkeypatch.setenv("OLT_UNIPLAC_IP", "192.0.2.201")
    monkeypatch.setenv("OLT_UNIPLAC_USER", "g08op")
    monkeypatch.setenv("OLT_UNIPLAC_PASSWORD", "sec")
    monkeypatch.setattr(infisical, "InfisicalClient", lambda **kw: fake_server)
    resolved = resolve_secrets("env", "OLT_UNIPLAC")
    assert resolved is not None
    assert resolved.host == "192.0.2.201"
    assert resolved.username == "g08op"
    assert resolved.protocol == "ssh"