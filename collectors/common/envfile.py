"""Load KEY=VALUE runtime files without logging values."""

from __future__ import annotations

from pathlib import Path


def read_env_file_keys(path: Path) -> dict[str, str]:
    """Return key→value from a dotenv-style file. Caller must not print values."""
    out: dict[str, str] = {}
    text = path.read_text(encoding="utf-8")
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key:
            out[key] = value
    return out


def apply_mapped_env(values: dict[str, str], mapping: dict[str, str]) -> list[str]:
    """Copy selected keys into os.environ under new names. Returns dest names only."""
    import os

    applied: list[str] = []
    for src, dest in mapping.items():
        if src in values and values[src] != "":
            os.environ[dest] = values[src]
            applied.append(dest)
    return applied
