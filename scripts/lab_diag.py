"""Lab diagnostics: counts and login flags only. Never prints secrets or MACs."""

from __future__ import annotations

import logging
import re

from collectors.common.cli_interactive import InteractiveCliTransport
from collectors.common.secrets import resolve_secrets
from collectors.common.transport import ReadOnlyTransport, TransportError
from collectors.intelbras_g08.parsers import parse_ont_mac_address
from collectors.intelbras_g08.readonly import G08_READ_ALLOWLIST
from collectors.mikrotik.collector import MikroTikCollector
from scripts.lab_collect import MK_PREFIX, OLT_PREFIX, _load_runtime_secrets

_MACISH = re.compile(
    r"[0-9A-Fa-f]{2}([:\-.][0-9A-Fa-f]{2}){5}|"
    r"[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}|"
    r"[0-9A-Fa-f]{12}"
)


def _headers(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if _MACISH.search(s):
            continue
        if re.search(r"(?i)password|username|login|token|secret", s):
            continue
        out.append(s[:80])
        if len(out) >= 12:
            break
    return out


def _print_login(label: str, transport: InteractiveCliTransport) -> None:
    st = transport.last_login
    print(
        f"{label} login reached_prompt={st.reached_prompt} "
        f"saw_user_prompt={st.saw_username_prompt} "
        f"saw_pass_prompt={st.saw_password_prompt} "
        f"auth_error={st.auth_error} chars={st.chars}"
    )


def main() -> None:
    logging.getLogger("paramiko").setLevel(logging.WARNING)
    _load_runtime_secrets()
    secrets = resolve_secrets("env", OLT_PREFIX)
    if secrets is None:
        print("olt secrets missing")
        return
    print(f"olt protocol set={bool(secrets.protocol)} port_set={bool(secrets.port)}")
    inner = InteractiveCliTransport(secrets, timeout_sec=90)
    guarded = ReadOnlyTransport(inner, G08_READ_ALLOWLIST)
    try:
        result = guarded.execute("show ont mac-address")
        text = result.stdout or ""
        _print_login("olt", inner)
        print(
            f"olt cmd_ok={result.ok} exit={result.exit_status} "
            f"chars={len(text)} lines={text.count(chr(10)) + 1}"
        )
        print(f"olt macish_lines={sum(1 for ln in text.splitlines() if _MACISH.search(ln))}")
        print(f"olt parsed={len(parse_ont_mac_address(text))}")
        for h in _headers(text):
            print(f"olt header: {h}")
        low = text.lower()
        if "incomplete" in low or "ambiguous" in low or "unknown" in low:
            print("olt body_looks_like_cli_error=yes")
            inner2 = InteractiveCliTransport(secrets, timeout_sec=180)
            guarded2 = ReadOnlyTransport(inner2, G08_READ_ALLOWLIST)
            fb = guarded2.execute("show ont mac-address-table interface gpon all")
            fb_text = fb.stdout or ""
            _print_login("olt_fallback", inner2)
            print(
                f"olt_fallback cmd_ok={fb.ok} chars={len(fb_text)} "
                f"lines={fb_text.count(chr(10)) + 1} "
                f"macish_lines={sum(1 for ln in fb_text.splitlines() if _MACISH.search(ln))} "
                f"parsed={len(parse_ont_mac_address(fb_text))}"
            )
            for h in _headers(fb_text):
                print(f"olt_fallback header: {h}")
    except TransportError:
        _print_login("olt", inner)
        print("olt cmd_ok=False transport=FAIL")

    mk = resolve_secrets("env", MK_PREFIX)
    if mk is None:
        print("mk secrets missing")
        return
    print(f"mk protocol_set={bool(mk.protocol)} port_set={bool(mk.port)}")
    import socket

    sock_cls = "unknown"
    try:
        sock = socket.create_connection((mk.host, mk.port), 5)
        sock.settimeout(3)
        data = sock.recv(64)
        sock.close()
        if data.startswith(b"SSH-"):
            sock_cls = "ssh"
        elif b"Login" in data or b"Username" in data or b"user" in data.lower():
            sock_cls = "cli_login"
        elif not data:
            sock_cls = "empty"
        else:
            sock_cls = f"other_len={len(data)}"
    except OSError:
        sock_cls = "tcp_fail"
    print(f"mk tcp_banner_class={sock_cls}")
    collected = MikroTikCollector("env", MK_PREFIX).collect_live(dhcp_only=True)
    print(
        f"mk status={collected.meta.get('status')} "
        f"dhcp={len(collected.dhcp)} "
        f"completeness={collected.meta.get('completeness')} "
        f"reason={collected.meta.get('reason') or '-'} "
        f"error={collected.meta.get('error_summary') or '-'}"
    )


if __name__ == "__main__":
    main()
