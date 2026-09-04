"""Host-side validate-deployment.sh must not assume default published ports."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate-deployment.sh"


def _print_urls(env: dict[str, str]) -> str:
    merged = os.environ.copy()
    merged.update(env)
    return subprocess.check_output(["sh", str(SCRIPT), "--print-urls"], env=merged, text=True)


def test_validate_urls_honor_override():
    out = _print_urls(
        {
            "VALIDATE_API_URL": "http://127.0.0.1:18000",
            "VALIDATE_MCP_URL": "http://127.0.0.1:18081/",
        }
    )
    assert "API_URL=http://127.0.0.1:18000" in out
    assert "MCP_URL=http://127.0.0.1:18081" in out
    assert "API_URL=http://127.0.0.1:8000" not in out


def test_validate_urls_default_when_compose_port_unavailable():
    out = _print_urls(
        {
            "VALIDATE_API_URL": "",
            "VALIDATE_MCP_URL": "",
            "PATH": "/usr/bin:/bin",
        }
    )
    assert "API_URL=http://127.0.0.1:8000" in out
    assert "MCP_URL=http://127.0.0.1:8081" in out
