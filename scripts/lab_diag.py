"""Lab diagnostics: transport stages and counts. Never prints secrets or MACs."""

from __future__ import annotations

import logging
import re

from collectors.common.cli_interactive import InteractiveCliTransport
from collectors.common.secrets import resolve_secrets
from collectors.common.transport import ReadOnlyTransport, TransportError, sanitized_exception_message
from collectors.intelbras_g08.parsers import parse_ont_mac_address
from collectors.intelbras_g08.readonly import G08_MAC_TABLE_COMMAND, G08_READ_ALLOWLIST
from collectors.mikrotik.collector import MikroTikCollector
from collectors.mikrotik.transport_ssh import SshTransport, diag_summary
from scripts.lab_collect import MK_PREFIX, OLT_PREFIX, _load_runtime_secrets

_MACISH = re.compile(
    r"[0-9A-Fa-f]{2}([:\-.][0-9A-Fa-f]{2}){5}|"
    r"[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}"
)


def main() -> None:
    logging.getLogger("paramiko").setLevel(logging.CRITICAL)
    _load_runtime_secrets()
    olt = resolve_secrets("env", OLT_PREFIX)
    if olt is None:
        print("olt secrets missing")
        return
    print(f"olt configured_protocol={olt.protocol} configured_port={olt.port}")
    inner = InteractiveCliTransport(olt, timeout_sec=180)
    guarded = ReadOnlyTransport(inner, G08_READ_ALLOWLIST)
    try:
        result = guarded.execute(G08_MAC_TABLE_COMMAND)
        text = result.stdout or ""
        print(
            f"olt cmd_ok={result.ok} chars={len(text)} "
            f"macish_lines={sum(1 for ln in text.splitlines() if _MACISH.search(ln))} "
            f"parsed={len(parse_ont_mac_address(text))}"
        )
    except TransportError as exc:
        print(f"olt transport=FAIL stage={exc.stage} err={sanitized_exception_message(exc)}")

    mk = resolve_secrets("env", MK_PREFIX)
    if mk is None:
        print("mk secrets missing")
        return
    print(f"mk configured_protocol={mk.protocol} configured_port={mk.port}")
    transport = SshTransport(mk, timeout_sec=60)
    try:
        cmd = "/ip dhcp-server lease print detail without-paging"
        from collectors.mikrotik.readonly import MIKROTIK_READ_ALLOWLIST

        result = ReadOnlyTransport(transport, MIKROTIK_READ_ALLOWLIST).execute(cmd)
        diag = diag_summary(transport)
        print(
            f"mk tcp={diag.get('tcp')} banner={diag.get('banner')} "
            f"handshake={diag.get('handshake')} authentication={diag.get('authentication')} "
            f"command={diag.get('command')} exit={result.exit_status} chars={len(result.stdout or '')}"
        )
        collected = MikroTikCollector("env", MK_PREFIX, transport=transport).collect_via_transport(
            transport, dhcp_only=True
        )
        print(
            f"mk parse leases={len(collected.dhcp)} entries={collected.meta.get('dhcp_entries_seen')} "
            f"failures={collected.meta.get('parse_failures')} completeness={collected.meta.get('completeness')}"
        )
    except TransportError as exc:
        diag = diag_summary(transport)
        print(
            f"mk tcp={diag.get('tcp')} banner={diag.get('banner')} "
            f"handshake={diag.get('handshake')} authentication={diag.get('authentication')} "
            f"command={diag.get('command')} stage={exc.stage} err={sanitized_exception_message(exc)}"
        )


if __name__ == "__main__":
    main()
