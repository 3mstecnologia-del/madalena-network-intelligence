"""Read-only RouterOS command allowlist.

Collectors must never issue add/set/remove/enable/disable/move.
Parser failures must not trigger a fallback mutable command.
"""

# Exact prefixes accepted by ReadOnlyTransport (RouterOS 7 print/get style).
MIKROTIK_READ_ALLOWLIST: tuple[str, ...] = (
    "/system identity print",
    "/system resource print",
    "/interface print",
    "/interface print detail",
    "/ip arp print",
    "/ip arp print detail",
    "/ip dhcp-server lease print",
    "/ip dhcp-server lease print detail",
    "/interface bridge host print",
    "/interface bridge host print detail",
    "/ip neighbor print",
    "/ip neighbor print detail",
)

# Logical collection steps: (result_key, command)
MIKROTIK_LIGHT_COMMANDS: tuple[tuple[str, str], ...] = (
    ("identity", "/system identity print"),
    ("arp", "/ip arp print detail"),
    ("dhcp", "/ip dhcp-server lease print detail"),
    ("fdb", "/interface bridge host print detail"),
)

MIKROTIK_FULL_COMMANDS: tuple[tuple[str, str], ...] = MIKROTIK_LIGHT_COMMANDS + (
    ("resource", "/system resource print"),
    ("interfaces", "/interface print detail"),
    ("neighbors", "/ip neighbor print detail"),
)

COLLECTOR_VERSION = "0.2.0"
