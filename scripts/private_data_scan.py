"""Refuse real lab identifiers in tracked repository or PR content.

Never prints matched secret values — only path + finding class.
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MAC = re.compile(
    r"(?i)(?<![0-9A-F])(?:[0-9A-F]{2}[:\-]){5}[0-9A-F]{2}(?![0-9A-F])"
)
DOTTED_MAC = re.compile(r"(?i)(?<![0-9A-F])(?:[0-9A-F]{4}\.){2}[0-9A-F]{4}(?![0-9A-F])")
IPV4 = re.compile(r"(?<![0-9.])(?:\d{1,3}\.){3}\d{1,3}(?![0-9.])")
ACCESSOS = re.compile(r"(?i)\b(?:olt|mk200)_(?:ip|username|password|port|protocol)\b")

ALLOW_REL = {".env.example"}
SYNTHETIC_MAC_PREFIX = ("AA:BB:CC", "AA:AA:AA", "DE:AD:BE", "11:22:33", "00:11:22")
SYNTHETIC_IP_PREFIX = ("10.0.", "10.30.", "10.40.", "10.99.", "127.0.", "0.0.0.")


def _allowed(rel: str) -> bool:
    return rel in ALLOW_REL


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
        try:
            ipaddress.IPv4Address(ip)
        except ipaddress.AddressValueError:
            continue
        if ip.startswith(SYNTHETIC_IP_PREFIX) or ip.startswith("192.0.2.") or ip.startswith("198.51.100."):
            continue
        if ip.startswith("203.0.113."):
            continue
        if ip in {"0.0.0.0", "255.255.255.255"}:
            continue
        findings.append("non-documentation ipv4")
        break
    return findings


def _tracked_names(root: Path, base_ref: str | None = None) -> list[str]:
    if base_ref:
        command = [
            "git",
            "diff",
            "--name-only",
            "--diff-filter=ACMR",
            "-z",
            f"{base_ref}...HEAD",
        ]
    else:
        command = ["git", "ls-files", "-z"]
    output = subprocess.check_output(command, cwd=root)
    return [name.decode("utf-8", errors="surrogateescape") for name in output.split(b"\0") if name]


def scan_repository(root: Path, base_ref: str | None = None) -> list[str]:
    names = _tracked_names(root, base_ref)
    findings: list[str] = []
    if any(name.endswith("acessos.env") for name in names):
        findings.append("acessos.env: tracked private access file")
    for rel in names:
        path = root / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for label in _scan_text(rel, text):
            findings.append(f"{rel}: {label}")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base-ref",
        default=os.environ.get("PRIVATE_DATA_BASE_REF"),
        help="scan added/modified content in base-ref...HEAD instead of every tracked file",
    )
    args = parser.parse_args()
    findings = scan_repository(ROOT, args.base_ref)
    if findings:
        print("PRIVATE DATA SCAN FAILED:")
        for item in findings:
            print(f" - {item}")
        return 1
    scope = f"PR content since {args.base_ref}" if args.base_ref else "all tracked repository content"
    print(f"PRIVATE DATA SCAN OK — no real lab identifiers in {scope}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
