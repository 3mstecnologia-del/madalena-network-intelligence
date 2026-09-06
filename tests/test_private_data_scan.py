from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.private_data_scan import _scan_text, scan_repository


def test_oid_is_not_reported_as_ipv4():
    assert _scan_text("template.yaml", "oid=1.3.6.1.4.1.13464") == []


@pytest.mark.parametrize(
    "identifier",
    ["AA:AA:AA:AA:AA:01", "DE:AD:BE:EF:00:01", "10.99.1.10", "10.40.1.8"],
)
def test_known_synthetic_fixture_identifiers_are_allowed(identifier: str):
    assert _scan_text("tests/fixture.txt", identifier) == []


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def test_clean_worktree_scans_committed_repository_content(tmp_path: Path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "safe.txt").write_text("safe\n")
    _git(tmp_path, "add", "safe.txt")
    _git(tmp_path, "commit", "-qm", "safe")

    private_ip = "192.168." + "77.22"
    (tmp_path / "inventory.txt").write_text(f"peer={private_ip}\n")
    _git(tmp_path, "add", "inventory.txt")
    _git(tmp_path, "commit", "-qm", "private identifier")

    assert not subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=tmp_path, text=True
    )
    assert scan_repository(tmp_path) == ["inventory.txt: non-documentation ipv4"]
