import pytest

from app.core.mac import macs_equal, normalize_mac


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("AA:BB:CC:DD:EE:FF", "AA:BB:CC:DD:EE:FF"),
        ("aa-bb-cc-dd-ee-ff", "AA:BB:CC:DD:EE:FF"),
        ("AABB.CCDD.EEFF", "AA:BB:CC:DD:EE:FF"),
        ("aabbccddeeff", "AA:BB:CC:DD:EE:FF"),
        (" aa:bb:cc:dd:ee:ff ", "AA:BB:CC:DD:EE:FF"),
    ],
)
def test_normalize_mac(raw, expected):
    assert normalize_mac(raw) == expected


def test_macs_equal():
    assert macs_equal("aa-bb-cc-dd-ee-ff", "AABBCCDDEEFF")


@pytest.mark.parametrize("bad", ["", "AA:BB", "GG:HH:II:JJ:KK:LL", None])
def test_normalize_mac_invalid(bad):
    with pytest.raises((ValueError, TypeError)):
        normalize_mac(bad)  # type: ignore[arg-type]
