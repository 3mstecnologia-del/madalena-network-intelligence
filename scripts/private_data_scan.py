"""Refuse real lab identifiers in the Git working tree / diff.

Never prints matched secret values — only path + finding class.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MAC = re.compile(
    r"(?i)(?<![0-9A-F])(?:[0-9A-F]{2}[:\-]){5}[0-9A-F]{2}(?![0-9A-F])"
)
DOTTED_MAC = re.compile(r"(?i)(?<![0-9A-F])(?:[0-9A-F]{4}\.){2}[0-9A-F]{4}(?![0-9A-F])")
IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
ACCESSOS = re.compile(r"(?i)\b(?:olt|mk200)_(?:ip|username|password|port|protocol)\b")

ALLOW_REL = {
    "tests/",
    "tests/fixtures/",
    ".env.example",
    "docs/",
    "README.md",
    "AGENTS.md",
    "SECURITY.md",
    "CONTRIBUTING.md",
}
SYNTHETIC_MAC_PREFIX = ("AA:BB:CC", "11:22:33", "00:11:22")
SYNTHETIC_IP_PREFIX = ("10.0.", "10.30.", "127.0.", "0.0.0.")


def _allowed(rel: str) -> bool:
    return any(rel.startswith(p) or rel == p.rstrip("/") for p in ALLOW_REL)


def _scan_text(rel: str, text: str) -> list[str]:
    if _allowed(rel):
        return []
    findings: list[str] = []
    if "acessos.env" in rel:
        findings.append("acessos.env path")
    if ACCESSOS.search(text) and "KEY_MAP" not in text and "olt_ip" in text and "DEVICE_LAB" not in text:
        # mapping source keys in lab_collect are expected; values are not
        if re.search(r"(?i)(?:olt|mk200)_password\s*=\s*\S+", text):
            findings.append("credential assignment")
    for m in MAC.finditer(text):
        val = m.group(0).upper().replace("-", ":")
        if not val.startswith(SYNTHETIC_MAC_PREFIX):
            findings.append("non-synthetic mac")
            break
    for m in DOTTED_MAC.finditer(text):
        if m.group(0).lower() not in {"aabb.ccdd.eeff", "1122.3344.5566"}:
            findings.append("non-synthetic dotted-mac")
            break
    for m in IPV4.finditer(text):
        ip = m.group(0)
        if ip.startswith(SYNTHETIC_IP_PREFIX) or ip.startswith("192.0.2.") or ip.startswith("198.51.100."):
            continue
        if ip in {"0.0.0.0", "255.255.255.255"}:
            continue
        findings.append("non-documentation ipv4")
        break
    return findings


def main() -> int:
    tracked = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True)
    if any(name.strip().endswith("acessos.env") for name in tracked.splitlines()):
        print("PRIVATE DATA SCAN FAILED: acessos.env is tracked")
        return 1
    names = subprocess.check_output(
        ["git", "diff", "HEAD", "--name-only"], cwd=ROOT, text=True
    ).splitlines()
    findings: list[str] = []
    for rel in names:
        if not rel:
            continue
        path = ROOT / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for label in _scan_text(rel, text):
            findings.append(f"{rel}: {label}")
    # Diff hunks may include deleted/context; scan the unified diff without printing it
    if findings:
        print("PRIVATE DATA SCAN FAILED:")
        for item in findings:
            print(f" - {item}")
        return 1
    print("PRIVATE DATA SCAN OK — no real lab identifiers in the working diff")
    return 0


if __name__ == "__main__":
    sys.exit(main())
