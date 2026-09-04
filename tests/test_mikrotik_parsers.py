from pathlib import Path

from collectors.mikrotik.parsers import (
    parse_arp,
    parse_bridge_fdb,
    parse_dhcp_leases,
    parse_identity,
    parse_interfaces,
    parse_neighbors,
)

FIX = Path(__file__).parent / "fixtures"


def test_parse_dhcp_leases():
    text = (FIX / "mikrotik_dhcp.txt").read_text()
    leases = parse_dhcp_leases(text)
    assert len(leases) == 2
    assert leases[0].mac == "AA:BB:CC:DD:EE:FF"
    assert leases[0].ip_address == "10.30.1.50"
    assert leases[0].hostname == "notebook-exemplo"
    assert leases[0].server == "dhcp-corp"
    assert leases[0].status == "bound"


def test_parse_arp():
    text = (FIX / "mikrotik_arp.txt").read_text()
    rows = parse_arp(text)
    assert len(rows) == 2
    assert rows[0].mac == "AA:BB:CC:DD:EE:FF"
    assert rows[0].interface == "bridge-lan"
    assert rows[0].ip_address == "10.30.1.50"


def test_parse_bridge_fdb():
    text = (FIX / "mikrotik_fdb.txt").read_text()
    rows = parse_bridge_fdb(text)
    assert len(rows) == 2
    assert rows[0].mac == "AA:BB:CC:DD:EE:FF"
    assert rows[0].interface == "sfp-sfpplus2"
    assert rows[0].vlan_id == 30


def test_parse_identity():
    ident = parse_identity((FIX / "mikrotik_identity.txt").read_text())
    assert ident is not None
    assert ident.name == "LAB-ROUTER"


def test_parse_interfaces():
    rows = parse_interfaces((FIX / "mikrotik_interfaces.txt").read_text())
    assert len(rows) == 3
    assert rows[0].name == "bridge-lan"
    assert rows[0].mac == "AA:AA:AA:AA:AA:01"
    assert rows[0].if_type == "bridge"
    names = {r.name for r in rows}
    assert names == {"bridge-lan", "ether1", "ether2"}


def test_parse_neighbors():
    rows = parse_neighbors((FIX / "mikrotik_neighbors.txt").read_text())
    assert len(rows) == 2
    assert rows[0].mac == "DE:AD:BE:EF:00:01"
    assert rows[0].ip_address == "10.30.1.1"
    assert rows[0].identity == "SW-LAB-01"
    assert rows[0].interface == "ether1"


def test_parse_neighbors_protocols_and_remote_interface():
    rows = parse_neighbors((FIX / "mikrotik_neighbors_protocols.txt").read_text())
    assert len(rows) == 3
    assert {r.protocol for r in rows} == {"lldp", "mndp", "cdp"}
    lldp = next(r for r in rows if r.protocol == "lldp")
    assert lldp.remote_interface == "sfp2"
    assert lldp.version == "7.15"
    assert lldp.interface == "ether1"


def test_parse_neighbors_missing_fields_is_not_error():
    rows = parse_neighbors((FIX / "mikrotik_neighbors_sparse.txt").read_text())
    assert len(rows) == 2
    named = next(r for r in rows if r.identity == "SWITCH-01")
    assert named.mac is None
    assert named.ip_address is None
    mac_only = next(r for r in rows if r.mac == "AA:BB:CC:44:00:01")
    assert mac_only.identity is None
    assert mac_only.protocol is None


def test_parse_arp_skips_bad_mac():
    text = "0   address=10.30.1.9 mac-address=not-a-mac interface=ether1\n"
    assert parse_arp(text) == []


def test_parse_fdb_skips_bad_mac():
    text = "0   D mac-address=zz:zz:zz:zz:zz:zz on-interface=ether1 bridge=bridge-lan\n"
    assert parse_bridge_fdb(text) == []
