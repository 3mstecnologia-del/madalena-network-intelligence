"""Read-only MikroTik RouterOS API transport (binary API, not SSH).

Used when the management TCP service speaks the RouterOS API (client-first).
Never logs credentials or replies. Callers must wrap with ReadOnlyTransport.
"""

from __future__ import annotations

import socket
from typing import Iterable

from collectors.common.secrets import DeviceSecrets
from collectors.common.transport import CommandResult, TransportError

_CLI_TO_API = (
    ("/ip dhcp-server lease print", "/ip/dhcp-server/lease/print"),
    ("/ip arp print", "/ip/arp/print"),
    ("/system identity print", "/system/identity/print"),
    ("/system resource print", "/system/resource/print"),
    ("/interface print", "/interface/print"),
    ("/interface bridge host print", "/interface/bridge/host/print"),
    ("/ip neighbor print", "/ip/neighbor/print"),
)


def encode_length(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    if n < 0x4000:
        n |= 0x8000
        return bytes([(n >> 8) & 0xFF, n & 0xFF])
    if n < 0x200000:
        n |= 0xC00000
        return bytes([(n >> 16) & 0xFF, (n >> 8) & 0xFF, n & 0xFF])
    if n < 0x10000000:
        n |= 0xE0000000
        return bytes(
            [(n >> 24) & 0xFF, (n >> 16) & 0xFF, (n >> 8) & 0xFF, n & 0xFF]
        )
    return b"\xF0" + n.to_bytes(4, "big")


def encode_word(word: str) -> bytes:
    data = word.encode("utf-8")
    return encode_length(len(data)) + data


def encode_sentence(words: Iterable[str]) -> bytes:
    body = b"".join(encode_word(w) for w in words)
    return body + b"\x00"


def decode_length(buf: bytes, offset: int) -> tuple[int, int]:
    if offset >= len(buf):
        raise TransportError("api truncated length")
    first = buf[offset]
    if first & 0x80 == 0:
        return first, offset + 1
    if first & 0xC0 == 0x80:
        if offset + 2 > len(buf):
            raise TransportError("api truncated length")
        n = ((first & ~0xC0) << 8) + buf[offset + 1]
        return n, offset + 2
    if first & 0xE0 == 0xC0:
        if offset + 3 > len(buf):
            raise TransportError("api truncated length")
        n = ((first & ~0xE0) << 16) + (buf[offset + 1] << 8) + buf[offset + 2]
        return n, offset + 3
    raise TransportError("api length encoding not supported")


def cli_command_to_api(command: str) -> str:
    compact = " ".join(command.split())
    for prefix, api_path in _CLI_TO_API:
        if compact == prefix or compact.startswith(prefix + " "):
            return api_path
    raise TransportError("no api mapping for command")


def sentences_to_print_text(sentences: list[list[str]]) -> str:
    lines: list[str] = []
    idx = 0
    for words in sentences:
        if not words or words[0] != "!re":
            continue
        parts = [w[1:] for w in words[1:] if w.startswith("=")]
        lines.append(f"{idx} " + " ".join(parts))
        idx += 1
    return "\n".join(lines) + ("\n" if lines else "")


class RouterOsApiTransport:
    """One TCP session per command: login, print, disconnect."""

    def __init__(self, secrets: DeviceSecrets, timeout_sec: int = 30):
        self._secrets = secrets
        self._timeout = timeout_sec

    def execute(self, command: str) -> CommandResult:
        api_path = cli_command_to_api(command)
        sock = socket.create_connection((self._secrets.host, self._secrets.port), self._timeout)
        sock.settimeout(self._timeout)
        try:
            self._talk(sock, ["/login", f"=name={self._secrets.username}", f"=password={self._secrets.password}"])
            replies = self._talk(sock, [api_path])
        except TransportError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise TransportError("api transport failed") from exc
        finally:
            sock.close()
        text = sentences_to_print_text(replies)
        return CommandResult(
            command=command,
            exit_status=0,
            stdout=text,
            stderr="",
            transport_ok=True,
        )

    def _talk(self, sock: socket.socket, words: list[str]) -> list[list[str]]:
        sock.sendall(encode_sentence(words))
        sentences: list[list[str]] = []
        while True:
            sentence = self._read_sentence(sock)
            if not sentence:
                continue
            sentences.append(sentence)
            tag = sentence[0]
            if tag == "!trap":
                raise TransportError("api command failed")
            if tag == "!fatal":
                raise TransportError("api session failed")
            if tag == "!done":
                return sentences

    def _read_sentence(self, sock: socket.socket) -> list[str]:
        words: list[str] = []
        while True:
            length = self._read_length(sock)
            if length == 0:
                return words
            data = self._recv_exact(sock, length)
            words.append(data.decode("utf-8", errors="replace"))

    def _read_length(self, sock: socket.socket) -> int:
        first = self._recv_exact(sock, 1)[0]
        if first & 0x80 == 0:
            return first
        if first & 0xC0 == 0x80:
            second = self._recv_exact(sock, 1)[0]
            return ((first & ~0xC0) << 8) + second
        if first & 0xE0 == 0xC0:
            extra = self._recv_exact(sock, 2)
            return ((first & ~0xE0) << 16) + (extra[0] << 8) + extra[1]
        raise TransportError("api length encoding not supported")

    def _recv_exact(self, sock: socket.socket, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise TransportError("api connection closed")
            buf += chunk
        return buf
