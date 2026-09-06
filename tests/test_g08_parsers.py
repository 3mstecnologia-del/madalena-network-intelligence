from pathlib import Path

from collectors.intelbras_g08.parsers import parse_ont_brief, parse_ont_mac_address, parse_ont_mac_address_table

FIX = Path(__file__).parent / "fixtures"


def test_parse_ont_mac_table():
    text = (FIX / "g08_mac_table.txt").read_text()
    rows = parse_ont_mac_address_table(text)
    assert len(rows) == 2
    assert rows[0].mac == "AA:BB:CC:DD:EE:FF"
    assert rows[0].ont_id == "0/1/14"
    assert rows[0].pon == "0/1"
    assert rows[0].vlan_id == 30


def test_parse_ont_mac_address_dotted():
    text = (FIX / "g08_mac_address.txt").read_text()
    rows = parse_ont_mac_address(text, command="show ont mac-address")
    assert len(rows) == 2
    assert rows[0].mac == "AA:BB:CC:DD:EE:FF"
    assert rows[0].ont_id == "0/1/14"
    assert rows[0].pon == "0/1"
    assert rows[0].vlan_id == 30
    assert rows[0].source == "olt"
    assert rows[0].command == "show ont mac-address"


def test_parse_ont_mac_vid_table():
    from collectors.intelbras_g08.parsers import onus_from_macs

    text = (FIX / "g08_mac_vid_table.txt").read_text()
    rows = parse_ont_mac_address_table(text)
    assert len(rows) == 2
    assert rows[0].mac == "AA:BB:CC:DD:EE:FF"
    assert rows[0].ont_id == "0/1/14"
    assert rows[0].pon == "0/1"
    assert rows[0].vlan_id == 30
    assert rows[0].serial == "TEST-12345678"
    assert rows[0].gem == "1/128"
    onus = onus_from_macs(rows)
    assert {u.ont_id: u.serial for u in onus}["0/1/14"] == "TEST-12345678"


def test_parse_ont_mac_table_preserves_distinct_services_on_same_ont():
    text = """\
MAC-Address         VID  ONT-ID  SN            ID/GEM
AA-BB-CC-DD-EE-FF  30   0/1/14  TEST-12345678  1/128
AA-BB-CC-DD-EE-FF  40   0/1/14  TEST-12345678  2/129
Total entries: 2
"""

    rows = parse_ont_mac_address_table(text)

    assert [(row.vlan_id, row.gem) for row in rows] == [(30, "1/128"), (40, "2/129")]


def test_parse_ont_mac_table_deduplicates_serial_variant_of_same_service():
    text = """\
MAC-Address         VID  ONT-ID  SN            ID/GEM
AA-BB-CC-DD-EE-FF  30   0/1/14  TEST-12345678  1/128
AA-BB-CC-DD-EE-FF  30   0/1/14  TEST-87654321  1/128
Total entries: 2
"""

    rows = parse_ont_mac_address_table(text)

    assert len(rows) == 1


def test_parse_ont_brief():
    text = (FIX / "g08_ont_brief.txt").read_text()
    rows = parse_ont_brief(text)
    assert len(rows) == 3
    assert rows[0].ont_id == "0/1/14"
    assert rows[0].serial == "TEST-12345678"
    assert rows[0].status == "online"
    assert rows[0].profile_name == "CORPORATIVO"
    assert rows[1].status == "offline"
    assert rows[1].profile_name == "HOME"
    assert rows[2].profile_name == "R1v2"


def test_parse_ont_brief_real_g08_layout():
    rows = parse_ont_brief(
        "ONT     SN             Device-type  Up/Down-time  Status   W/S\n"
        "0/1/1   TEST-111111     140PoE       125d16h39m    online   working\n"
        "0/1/9   TEST-222222  -            109d22h27m    online   working\n"
        "0/1/12  TEST-333333      140PoE       142d18h4m     offline  working\n"
    )
    assert len(rows) == 3
    assert rows[0].ont_id == "0/1/1"
    assert rows[0].serial == "TEST-111111"
    assert rows[0].status == "online"
    assert rows[0].profile_name == "140PoE"
    assert rows[2].status == "offline"


def test_parse_ont_brief_avoids_overmatching_device_type_as_status():
    rows = parse_ont_brief(
        "0/2/3  TEST-444444  R1v2  165d20h19m  online  working\n"
        "0/1/8  TEST-555555  -     9d19h43m    offline  working\n"
    )
    assert rows[0].status == "online"
    assert rows[0].profile_name == "R1v2"
    assert rows[1].status == "offline"
    assert rows[1].profile_name is None
