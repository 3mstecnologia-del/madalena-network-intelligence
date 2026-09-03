"""Read-only Intelbras G08 command allowlist.

Only documented show/read commands. Never add/set/remove/enable/disable/move,
never configure terminal, never reboot/reset/backup/export.
"""

G08_READ_ALLOWLIST: tuple[str, ...] = (
    "show ont mac-address",
    "show ont mac-address-table",
)

# Lab collection: the authorized primary command.
G08_MAC_COMMANDS: tuple[tuple[str, str], ...] = (
    ("mac_table", "show ont mac-address"),
)

# Skill-documented form — used only if the primary command is incomplete.
G08_MAC_COMMAND_FALLBACK = "show ont mac-address-table interface gpon all"

COLLECTOR_VERSION = "0.2.0"
