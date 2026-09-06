import pytest

from app.core.ip import normalize_ip, normalize_ipv4


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("10.30.1.50", "10.30.1.50"),
        (" 10.0.0.1 ", "10.0.0.1"),
    ],
)
def test_normalize_ipv4(raw, expected):
    assert normalize_ipv4(raw) == expected
    assert normalize_ip(raw) == expected


def test_normalize_ipv6_canonical():
    assert normalize_ip("2001:0db8:0000:0000:0000:0000:0000:0001") == "2001:db8::1"


def test_normalize_ipv4_rejects_ipv6():
    with pytest.raises(ValueError):
        normalize_ipv4("2001:db8::1")


@pytest.mark.parametrize("bad", ["", "10.30.1", "999.1.1.1", "not-an-ip"])
def test_normalize_ip_invalid(bad):
    with pytest.raises(ValueError):
        normalize_ip(bad)
