"""Tests for the Bluetooth serial shim and its URL handler."""

import socket
from typing import cast

import pytest
import serial

from riden.bt.bt_serial import BtSerial, parse_mac
from riden.bt.protocol_bt import parse_bt_url


class FakeSocket:
    """Minimal socket stand-in for the BtSerial read/write paths."""

    def __init__(self, chunks: list[bytes] | None = None) -> None:
        self.chunks = [] if chunks is None else list(chunks)
        self.sent = bytearray()
        self.closed = False
        self.timeout: float | None = None

    def sendall(self, data: bytes) -> None:
        self.sent.extend(data)

    def recv(self, size: int, flags: int = 0) -> bytes:
        if not self.chunks:
            return b""
        chunk = self.chunks.pop(0)
        return chunk[:size]

    def settimeout(self, timeout: float | None) -> None:
        self.timeout = timeout

    def close(self) -> None:
        self.closed = True


def open_serial(
    chunks: list[bytes] | None = None,
    timeout: float | None = None,
) -> tuple[BtSerial, FakeSocket]:
    """Build a BtSerial with an injected fake socket.

    ``timeout=None`` exercises the blocking read path and ``timeout=0`` the
    non-blocking one; both avoid select().
    """
    bt = BtSerial(timeout=timeout)
    sock = FakeSocket(chunks)
    bt.sock = cast(socket.socket, sock)
    return bt, sock


def test_parse_mac_normalizes() -> None:
    assert parse_mac("aa-bb-cc-dd-ee-ff") == "AA:BB:CC:DD:EE:FF"
    assert parse_mac("  AA:BB:CC:DD:EE:FF  ") == "AA:BB:CC:DD:EE:FF"


def test_parse_mac_rejects_garbage() -> None:
    with pytest.raises(ValueError, match="invalid Bluetooth MAC"):
        parse_mac("not-a-mac")


def test_parse_bt_url_defaults() -> None:
    mac, kwargs = parse_bt_url("bt://AA:BB:CC:DD:EE:FF")
    assert mac == "AA:BB:CC:DD:EE:FF"
    assert kwargs == {"channel": 1, "timeout": None, "connect_timeout": None}


def test_parse_bt_url_options() -> None:
    mac, kwargs = parse_bt_url(
        "bt://aa:bb:cc:dd:ee:ff/?channel=2&timeout=1.5&connect_timeout=3"
    )
    assert mac == "aa:bb:cc:dd:ee:ff"
    assert kwargs == {"channel": 2, "timeout": 1.5, "connect_timeout": 3.0}


@pytest.mark.parametrize(
    "url",
    [
        "serial://AA:BB:CC:DD:EE:FF",
        "bt://",
        "bt://AA:BB:CC:DD:EE:FF/extra",
        "bt://AA:BB:CC:DD:EE:FF?channel=abc",
        "bt://AA:BB:CC:DD:EE:FF?timeout=abc",
    ],
)
def test_parse_bt_url_rejects_invalid(url: str) -> None:
    with pytest.raises(ValueError):
        parse_bt_url(url)


def test_serial_for_url_returns_configured_bt_serial() -> None:
    import riden  # noqa: F401  (registers the bt:// handler)

    port = cast(
        BtSerial,
        serial.serial_for_url(
            "bt://AA:BB:CC:DD:EE:FF?channel=3&timeout=0.5", do_not_open=True
        ),
    )
    assert isinstance(port, BtSerial)
    assert port.port == "AA:BB:CC:DD:EE:FF"
    assert port.channel == 3
    assert port.timeout == 0.5
    assert not port.is_open


def test_closed_serial_raises() -> None:
    bt = BtSerial()
    assert not bt.is_open
    with pytest.raises(serial.SerialException, match="closed"):
        bt.read(1)


def test_write_sends_bytes() -> None:
    bt, sock = open_serial()
    assert bt.write(b"abc") == 3
    assert bytes(sock.sent) == b"abc"


def test_blocking_read_collects_all_bytes() -> None:
    bt, _ = open_serial([b"ab", b"cd"], timeout=None)
    assert bt.read(4) == b"abcd"


def test_blocking_read_raises_when_peer_closes() -> None:
    bt, _ = open_serial([], timeout=None)
    with pytest.raises(serial.SerialException, match="closed the link"):
        bt.read(1)


def test_non_blocking_read_returns_available_bytes() -> None:
    bt, _ = open_serial([b"xy"], timeout=0)
    assert bt.read(2) == b"xy"
    assert bt.read(2) == b""


def test_zero_size_read_returns_empty() -> None:
    bt, _ = open_serial([b"xy"], timeout=0)
    assert bt.read(0) == b""


def test_close_is_idempotent() -> None:
    bt, sock = open_serial()
    bt.close()
    bt.close()
    assert sock.closed
    assert not bt.is_open


def test_flush_helpers_do_not_raise() -> None:
    bt, _ = open_serial()
    bt.flush()
    bt.reset_output_buffer()
