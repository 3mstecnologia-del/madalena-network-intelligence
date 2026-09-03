"""CLI prompt classifiers — no live devices, no secrets."""

from collectors.common.cli_interactive import (
    AUTH_FAIL,
    PASSWORD_PROMPT,
    USERNAME_PROMPT,
    looks_like_device_prompt,
    pager_continuation,
)


def test_g08_username_prompt():
    assert USERNAME_PROMPT.search("Username(1-64 chars):")
    assert USERNAME_PROMPT.search("\nUsername(1-64 chars):")
    assert not USERNAME_PROMPT.search("Username or password error")


def test_g08_password_prompt():
    assert PASSWORD_PROMPT.search("Password(1-96 chars):")
    assert PASSWORD_PROMPT.search("Password:")
    assert not PASSWORD_PROMPT.search("Username or password error")


def test_g08_device_prompt():
    assert looks_like_device_prompt("G8>")
    assert looks_like_device_prompt("banner\nG8#")
    assert looks_like_device_prompt("[admin@LAB] >")
    assert not looks_like_device_prompt("Username(1-64 chars):")


def test_g08_auth_fail():
    assert AUTH_FAIL.search("Username or password error")


def test_g08_pager_sends_enter():
    key = pager_continuation("rows...\npress ENTER to next line, CTRL+C to stop")
    assert key == "\r\n"
