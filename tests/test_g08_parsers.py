from pathlib import Path

from collectors.intelbras_g08.parsers import parse_ont_brief, parse_ont_mac_address_table

FIX = Path(__file__).parent / "fixtures"


def test_parse_ont_mac_table():
    text = (FIX / "g08_mac_table.txt").read_text()
    rows = parse_ont_mac_address_table(text)
    assert len(rows) == 2
    assert rows[0].mac == "AA:BB:CC:DD:EE:FF"
    assert rows[0].ont_id == "0/1/14"
    assert rows[0].pon == "0/1"
    assert rows[0].vlan_id == 30


def test_parse_ont_brief():
    text = (FIX / "g08_ont_brief.txt").read_text()
    rows = parse_ont_brief(text)
    assert len(rows) == 2
    assert rows[0].ont_id == "0/1/14"
    assert rows[0].serial == "ALCL12345678"
    assert rows[0].status == "online"
    assert rows[0].profile_name == "CORPORATIVO"
