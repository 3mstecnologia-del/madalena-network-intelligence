"""Read-only RouterOS command allowlist.

Collectors must never issue add/set/remove/enable/disable/move.
Parser failures must not trigger a fallback mutable command.
"""

# Exact commands accepted by ReadOnlyTransport (RouterOS 7 print/get style).
# Modifiers such as without-paging must be listed; suffixes are not implied.
MIKROTIK_READ_ALLOWLIST: tuple[str, ...] = (
    "/system identity print",
    "/system resource print",
    "/interface print",
    "/interface print detail",
    "/ip arp print",
    "/ip arp print detail",
    "/ip dhcp-server lease print",
    "/ip dhcp-server lease print detail",
    "/ip dhcp-server lease print detail without-paging",
    "/interface bridge host print",
    "/interface bridge host print detail",
    "/ip neighbor print",
    "/ip neighbor print detail",
)

MIKROTIK_DHCP_COMMANDS: tuple[tuple[str, str], ...] = (
    ("dhcp", "/ip dhcp-server lease print detail without-paging"),
)

MIKROTIK_LIGHT_COMMANDS: tuple[tuple[str, str], ...] = (
    ("identity", "/system identity print"),
    ("interfaces", "/interface print detail"),
    ("arp", "/ip arp print detail"),
    ("dhcp", "/ip dhcp-server lease print detail"),
    ("fdb", "/interface bridge host print detail"),
    ("neighbors", "/ip neighbor print detail"),
)

MIKROTIK_FULL_COMMANDS: tuple[tuple[str, str], ...] = MIKROTIK_LIGHT_COMMANDS + (
    ("resource", "/system resource print"),
)

# Map command step key → collector name used in device.collectors_enabled
MIKROTIK_STEP_COLLECTOR: dict[str, str] = {
    "identity": "identity",
    "resource": "identity",
    "dhcp": "dhcp",
    "arp": "arp",
    "fdb": "fdb",
    "interfaces": "interfaces",
    "neighbors": "neighbors",
}

COLLECTOR_VERSION = "0.4.0"
