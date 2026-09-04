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


def test_validate_postgres_readiness_uses_container_database_identity(tmp_path):
    capture = tmp_path / "docker-args.txt"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$*" >> "$CAPTURE"\n'
        "exit 0\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    curl = fake_bin / "curl"
    curl.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    curl.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:/usr/bin:/bin",
            "CAPTURE": str(capture),
            "VALIDATE_API_URL": "http://127.0.0.1:18080",
            "VALIDATE_MCP_URL": "http://127.0.0.1:18082",
        }
    )
    result = subprocess.run(["sh", str(SCRIPT)], env=env, text=True, capture_output=True)

    assert result.returncode == 0, result.stderr
    calls = capture.read_text(encoding="utf-8")
    assert "compose exec -T db sh -c" in calls
    assert 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' in calls


def test_docker_build_context_excludes_private_runtime_files():
    dockerignore = ROOT / ".dockerignore"

    assert dockerignore.is_file()
    patterns = {
        line.strip()
        for line in dockerignore.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert ".env" in patterns
    assert ".env.*" in patterns
    assert "!.env.example" in patterns
    assert ".git" in patterns
