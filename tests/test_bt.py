"""Tests for the Bluetooth serial shim and its URL handler."""

import contextlib
import re
import socket
import threading
from collections.abc import Iterator
from typing import Any, cast

import pytest
import serial

from riden.bt import bt_serial
from riden.bt.bt_serial import BtSerial, SecurityLevel, parse_mac
from riden.bt.protocol_bt import parse_bt_url


@pytest.fixture
def pair() -> Iterator[tuple[BtSerial, socket.socket]]:
    """An open BtSerial on one end of a socketpair, and the peer end.

    A real socket keeps select(), FIONREAD and MSG_DONTWAIT honest.
    """
    ours, peer = socket.socketpair()
    bt = BtSerial()
    bt.sock = ours
    bt.is_open = True
    yield bt, peer
    bt.close()
    peer.close()


def fill_send_buffer(bt: BtSerial) -> None:
    """Fill the kernel send buffer, so the next write would block."""
    sock = cast(socket.socket, bt.sock)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
    with contextlib.suppress(BlockingIOError):
        while True:
            sock.send(b"x" * 4096, socket.MSG_DONTWAIT)


def test_parse_mac_normalizes() -> None:
    assert parse_mac("aa-bb-cc-dd-ee-ff") == "AA:BB:CC:DD:EE:FF"
    assert parse_mac("  AA:BB:CC:DD:EE:FF  ") == "AA:BB:CC:DD:EE:FF"


def test_parse_mac_rejects_garbage() -> None:
    with pytest.raises(ValueError, match="invalid Bluetooth MAC"):
        parse_mac("not-a-mac")


def test_parse_bt_url_returns_only_present_params() -> None:
    mac, kwargs = parse_bt_url("bt://AA:BB:CC:DD:EE:FF")
    assert mac == "AA:BB:CC:DD:EE:FF"
    assert kwargs == {}

    _, kwargs = parse_bt_url("bt://AA:BB:CC:DD:EE:FF?channel=2")
    assert kwargs == {"channel": 2}


def test_serial_for_url_keeps_bt_serial_defaults() -> None:
    import riden  # noqa: F401  (registers the bt:// handler)

    port = cast(
        BtSerial, serial.serial_for_url("bt://AA:BB:CC:DD:EE:FF", do_not_open=True)
    )
    default = BtSerial()
    assert port.channel == default.channel
    assert port.timeout == default.timeout
    assert port.connect_timeout == default.connect_timeout
    assert port.security == default.security == SecurityLevel.MEDIUM


def test_parse_bt_url_options() -> None:
    mac, kwargs = parse_bt_url(
        "bt://aa:bb:cc:dd:ee:ff/?channel=2&connect_timeout=3&security=LOW"
    )
    assert mac == "aa:bb:cc:dd:ee:ff"
    assert kwargs == {
        "channel": 2, "connect_timeout": 3.0,
        "security": SecurityLevel.LOW,
    }


def test_parse_bt_url_keeps_zero_security_level() -> None:
    _, kwargs = parse_bt_url("bt://AA:BB:CC:DD:EE:FF?security=sdp")
    assert kwargs["security"] is SecurityLevel.SDP


@pytest.mark.parametrize(
    "url",
    [
        "serial://AA:BB:CC:DD:EE:FF",
        "bt://",
        "bt://AA:BB:CC:DD:EE:FF/extra",
        "bt://AA:BB:CC:DD:EE:FF?channel=abc",
        "bt://AA:BB:CC:DD:EE:FF?connect_timeout=abc",
        # The read timeout is an argument, not a URL parameter.
        "bt://AA:BB:CC:DD:EE:FF?timeout=0.5",
        "bt://AA:BB:CC:DD:EE:FF?security=bogus",
        "bt://AA:BB:CC:DD:EE:FF?timout=1",
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
            "bt://AA:BB:CC:DD:EE:FF?channel=3", timeout=2, do_not_open=True
        ),
    )
    assert isinstance(port, BtSerial)
    assert port.port == "AA:BB:CC:DD:EE:FF"
    assert port.channel == 3
    assert port.timeout == 2
    assert not port.is_open


class RecordingSocket:
    """socket.socket stand-in that records the calls made by BtSerial.open()."""

    def __init__(self, *_: Any) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        RecordingSocket.last = self

    def setsockopt(self, *args: Any) -> None:
        self.calls.append(("setsockopt", args))

    def settimeout(self, *args: Any) -> None:
        self.calls.append(("settimeout", args))

    def connect(self, *args: Any) -> None:
        self.calls.append(("connect", args))

    def close(self) -> None:
        pass

    last: RecordingSocket


@pytest.mark.parametrize(
    ("kwargs", "level"),
    [({}, SecurityLevel.MEDIUM), ({"security": SecurityLevel.LOW}, SecurityLevel.LOW)],
)
def test_open_sets_security_before_connect(
    monkeypatch: pytest.MonkeyPatch, kwargs: dict[str, Any], level: SecurityLevel
) -> None:
    monkeypatch.setattr(bt_serial.socket, "socket", RecordingSocket)
    BtSerial("AA:BB:CC:DD:EE:FF", **kwargs)
    calls = RecordingSocket.last.calls
    names = [name for name, _ in calls]
    assert calls[names.index("setsockopt")][1] == (
        bt_serial.SOL_BLUETOOTH, bt_serial.BT_SECURITY, bytes((level, 0))
    )
    assert names.index("setsockopt") < names.index("connect")


def test_is_a_pyserial_port() -> None:
    bt = BtSerial()
    assert isinstance(bt, serial.SerialBase)
    # pyserial defaults, straight from SerialBase.
    default = serial.Serial()
    assert (bt.baudrate, bt.timeout, bt.write_timeout) == (
        default.baudrate, default.timeout, default.write_timeout
    )


def test_accepts_pyserial_line_settings() -> None:
    bt = BtSerial(bytesize=7, parity=serial.PARITY_EVEN, inter_byte_timeout=0.1)
    assert (bt.bytesize, bt.parity, bt.inter_byte_timeout) == (7, "E", 0.1)
    with pytest.raises(ValueError, match="unexpected keyword"):
        BtSerial(bogus=1)


@pytest.mark.parametrize("op", ["read", "write", "in_waiting", "reset_input_buffer"])
def test_closed_serial_raises(op: str) -> None:
    bt = BtSerial()
    assert not bt.is_open
    with pytest.raises(serial.PortNotOpenError):
        attr = getattr(bt, op)
        if op == "write":
            attr(b"x")
        elif callable(attr):
            attr()


def test_write_sends_bytes(pair: tuple[BtSerial, socket.socket]) -> None:
    bt, peer = pair
    assert bt.write(b"abc") == 3
    assert peer.recv(10) == b"abc"


def test_blocking_read_collects_all_bytes(pair: tuple[BtSerial, socket.socket]) -> None:
    bt, peer = pair
    peer.send(b"ab")
    threading.Timer(0.05, peer.send, (b"cd",)).start()
    assert bt.read(4) == b"abcd"


def test_read_raises_when_peer_closes(pair: tuple[BtSerial, socket.socket]) -> None:
    bt, peer = pair
    peer.close()
    with pytest.raises(serial.SerialException, match="closed the link"):
        bt.read(1)


def test_non_blocking_read_returns_available_bytes(
    pair: tuple[BtSerial, socket.socket],
) -> None:
    bt, peer = pair
    bt.timeout = 0
    peer.send(b"xy")
    assert bt.read(5) == b"xy"
    assert bt.read(5) == b""


def test_timed_read_returns_partial_data(pair: tuple[BtSerial, socket.socket]) -> None:
    bt, peer = pair
    bt.timeout = 0.05
    peer.send(b"xy")
    assert bt.read(5) == b"xy"


def test_inter_byte_timeout_ends_read(pair: tuple[BtSerial, socket.socket]) -> None:
    bt, peer = pair
    bt.timeout = None  # would block forever without inter_byte_timeout
    bt.inter_byte_timeout = 0.05
    peer.send(b"xy")
    assert bt.read(5) == b"xy"


def test_zero_size_read_returns_empty(pair: tuple[BtSerial, socket.socket]) -> None:
    bt, _ = pair
    assert bt.read(0) == b""


def test_in_waiting_and_reset_input_buffer(pair: tuple[BtSerial, socket.socket]) -> None:
    bt, peer = pair
    peer.send(b"abc")
    assert bt.in_waiting == 3
    bt.reset_input_buffer()
    assert bt.in_waiting == 0


def test_readline_comes_from_serialbase(pair: tuple[BtSerial, socket.socket]) -> None:
    bt, peer = pair
    bt.timeout = 0.05
    peer.send(b"one\ntwo")
    assert bt.readline() == b"one\n"


def test_close_is_idempotent(pair: tuple[BtSerial, socket.socket]) -> None:
    bt, _ = pair
    sock = cast(socket.socket, bt.sock)
    bt.close()
    bt.close()
    assert sock.fileno() == -1
    assert not bt.is_open


def test_noop_helpers_do_not_raise(pair: tuple[BtSerial, socket.socket]) -> None:
    bt, _ = pair
    bt.flush()
    bt.reset_output_buffer()
    bt.send_break()
    bt.rts = False
    bt.dtr = False
    bt.baudrate = 19200  # _reconfigure_port on an open port
    assert (bt.cts, bt.dsr, bt.ri, bt.cd) == (True, True, False, True)


@pytest.mark.parametrize(
    "kwargs",
    [{"baudrate": -1}, {"baudrate": "abc"}, {"timeout": -1}, {"write_timeout": "1"}],
)
def test_validation_matches_pyserial(kwargs: dict[str, Any]) -> None:
    # Validation comes from SerialBase: the same exception as serial.Serial.
    with pytest.raises(Exception) as expected:
        serial.Serial(**kwargs)
    with pytest.raises(expected.type, match=re.escape(str(expected.value))):
        BtSerial(**kwargs)


def test_open_leaves_socket_blocking(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bt_serial.socket, "socket", RecordingSocket)
    bt = BtSerial("AA:BB:CC:DD:EE:FF", timeout=0.5, connect_timeout=3)
    assert bt.is_open
    timeouts = [args for name, args in RecordingSocket.last.calls if name == "settimeout"]
    # connect_timeout for connect(), then blocking; never the read timeout.
    assert timeouts == [(3,), (None,)]


def test_timeout_change_does_not_touch_socket(pair: tuple[BtSerial, socket.socket]) -> None:
    bt, _ = pair
    sock = cast(socket.socket, bt.sock)
    bt.timeout = 0.5
    bt.write_timeout = 0
    assert sock.gettimeout() is None


def test_non_blocking_write_on_full_buffer_returns_zero(
    pair: tuple[BtSerial, socket.socket],
) -> None:
    bt, _ = pair
    bt.write_timeout = 0
    fill_send_buffer(bt)
    assert bt.write(b"abc") == 0


def test_timed_write_raises_on_full_buffer(pair: tuple[BtSerial, socket.socket]) -> None:
    bt, _ = pair
    bt.write_timeout = 0.05
    fill_send_buffer(bt)
    with pytest.raises(serial.SerialTimeoutException, match="Write timeout"):
        bt.write(b"abc")


def test_timed_write_sends_everything(pair: tuple[BtSerial, socket.socket]) -> None:
    bt, peer = pair
    bt.write_timeout = 1.0
    assert bt.write(b"abcde") == 5
    assert peer.recv(10) == b"abcde"
