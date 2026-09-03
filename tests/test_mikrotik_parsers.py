from pathlib import Path

from collectors.mikrotik.parsers import parse_arp, parse_bridge_fdb, parse_dhcp_leases

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


def test_parse_bridge_fdb():
    text = (FIX / "mikrotik_fdb.txt").read_text()
    rows = parse_bridge_fdb(text)
    assert len(rows) == 2
    assert rows[0].mac == "AA:BB:CC:DD:EE:FF"
    assert rows[0].interface == "sfp-sfpplus2"
    assert rows[0].vlan_id == 30
