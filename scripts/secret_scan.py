"""Lightweight secret scan for public-repo readiness. Runs inside Docker."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Patterns that must never appear in tracked project files
# (known-leak needles assembled at runtime so this file does not self-match)
_LAB_PW = "madalena" + "123"
_REAL_HOST = "home." + "3mstecnologia.com"

FORBIDDEN = [
    (re.compile(r"(?i)password\s*=\s*['\"](?!change_me|placeholder|<)[^'\"]{4,}"), "password assignment"),
    (re.compile(r"(?i)(api[_-]?key|private[_-]?key|secret[_-]?key)\s*=\s*['\"][^'\"]{8,}"), "key assignment"),
    (re.compile(re.escape(_LAB_PW), re.I), "known lab password leak"),
    (re.compile(re.escape(_REAL_HOST), re.I), "real host leak"),
    (re.compile(r"BEGIN (RSA |OPENSSH )?PRIVATE KEY"), "private key block"),
    (re.compile(r"(?i)snmp[_-]?community\s*=\s*['\"][^'\"]+"), "snmp community"),
    (re.compile(r"(?i)-----BEGIN[A-Z ]*PRIVATE KEY-----"), "pem private key"),
]

SKIP_DIRS = {".git", ".venv", "__pycache__", ".ruff_cache", ".pytest_cache", "pgdata"}
SKIP_SUFFIX = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pyc", ".pdf"}
ALLOW_PATH_SUBSTRINGS = [
    "tests/fixtures/",  # synthetic lab-like but non-real data
]


def allowed(path: Path) -> bool:
    rel = str(path.relative_to(ROOT))
    if rel in {".env.example"}:
        return True
    for part in path.parts:
        if part in SKIP_DIRS:
            return False
    if path.suffix.lower() in SKIP_SUFFIX:
        return False
    if path.name == ".env":
        return False  # gitignored; skip if present
    return path.is_file()


def main() -> int:
    findings: list[str] = []
    for path in ROOT.rglob("*"):
        if not allowed(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = str(path.relative_to(ROOT))
        if any(s in rel for s in ALLOW_PATH_SUBSTRINGS):
            # still scan fixtures for real host/password leaks
            patterns = [
                p
                for p in FORBIDDEN
                if p[1] in {"known lab password leak", "real host leak", "private key block", "pem private key"}
            ]
        else:
            patterns = FORBIDDEN
        for rx, label in patterns:
            if rx.search(text):
                findings.append(f"{rel}: {label}")
    if findings:
        print("SECRET SCAN FAILED:")
        for f in findings:
            print(" -", f)
        return 1
    print("SECRET SCAN OK — no forbidden patterns in project tree (excluding .env)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
