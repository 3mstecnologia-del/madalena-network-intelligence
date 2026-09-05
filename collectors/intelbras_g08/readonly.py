"""Read-only Intelbras G08 command allowlist.

Live G08 evidence: `show ont mac-address` is incomplete on this family.
The collector contract is the skill-documented table command.
"""

G08_FAMILY = "intelbras-g08"
G08_MAC_TABLE_COMMAND = "show ont mac-address-table interface gpon all"
G08_ONT_BRIEF_COMMAND = "show ont brief interface gpon all"

G08_READ_ALLOWLIST: tuple[str, ...] = (
    G08_MAC_TABLE_COMMAND,
    G08_ONT_BRIEF_COMMAND,
)

G08_MAC_COMMANDS: tuple[tuple[str, str], ...] = (
    ("mac_table", G08_MAC_TABLE_COMMAND),
)

COLLECTOR_VERSION = "0.4.0"
