"""Tests for the BLE serial shim and its URL handler.

A fake bleak client runs on the real asyncio loop thread, so lifecycle,
timeouts and notification buffering are exercised without hardware.
"""

import io
import time
from collections.abc import Iterator
from typing import Any, ClassVar, cast

import minimalmodbus
import pytest
import serial

from riden.bt import bt_serial
from riden.bt.bt_serial import NOTIFY_UUID, WRITE_UUID, BtSerial, parse_mac
from riden.bt.protocol_bt import parse_bt_url


class FakeDevice:
    def __init__(self, address: str):
        self.address = address


class FakeClient:
    """Stand-in for bleak.BleakClient, with the same async surface."""

    instances: ClassVar[list[FakeClient]] = []
    fail_connect = False

    def __init__(
        self,
        address: Any,
        disconnected_callback: Any = None,
        timeout: float = 30,
    ):
        self.address = address
        self.disconnected_callback = disconnected_callback
        self.timeout = timeout
        self.notify_callback: Any = None
        self.writes: list[tuple[str, bytes, bool | None]] = []
        self.connected = False
        self.disconnected = False
        FakeClient.instances.append(self)

    async def connect(self) -> None:
        if FakeClient.fail_connect:
            raise bt_serial.BleakError("fake connect failure")
        self.connected = True

    async def start_notify(self, uuid: str, callback: Any) -> None:
        assert uuid == NOTIFY_UUID
        self.notify_callback = callback

    async def write_gatt_char(
        self, uuid: str, data: bytes, response: bool | None = None
    ) -> None:
        self.writes.append((uuid, bytes(data), response))

    async def disconnect(self) -> None:
        self.connected = False
        self.disconnected = True

    def notify(self, data: bytes) -> None:
        assert self.notify_callback is not None
        self.notify_callback(None, bytearray(data))

    def drop(self) -> None:
        self.connected = False
        if self.disconnected_callback is not None:
            self.disconnected_callback(self)


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> type[FakeClient]:
    FakeClient.instances.clear()
    FakeClient.fail_connect = False
    monkeypatch.setattr(bt_serial, "BleakClient", FakeClient)

    async def find_device_by_address(
        address: str, timeout: float = 10.0
    ) -> FakeDevice:
        return FakeDevice(address)

    monkeypatch.setattr(
        bt_serial.BleakScanner,
        "find_device_by_address",
        find_device_by_address,
    )
    return FakeClient


@pytest.fixture
def port(fake: type[FakeClient]) -> Iterator[BtSerial]:
    port = BtSerial("AA:BB:CC:DD:EE:FF", timeout=1)
    yield port
    port.close()


def client() -> FakeClient:
    return FakeClient.instances[-1]


def test_parse_mac_normalizes() -> None:
    assert parse_mac("aa-bb-cc-dd-ee-ff") == "AA:BB:CC:DD:EE:FF"
    assert parse_mac("  AA:BB:CC:DD:EE:FF  ") == "AA:BB:CC:DD:EE:FF"


def test_parse_mac_rejects_garbage() -> None:
    with pytest.raises(ValueError, match="invalid Bluetooth MAC"):
        parse_mac("not-a-mac")


def test_parse_bt_url_returns_only_present_params() -> None:
    target, kwargs = parse_bt_url("bt://AA:BB:CC:DD:EE:FF")
    assert target == "AA:BB:CC:DD:EE:FF"
    assert kwargs == {}

    _, kwargs = parse_bt_url("bt://AA:BB:CC:DD:EE:FF?connect_timeout=3")
    assert kwargs == {"connect_timeout": 3.0}


def test_parse_bt_url_accepts_a_device_name() -> None:
    assert parse_bt_url("bt://RK6006") == ("RK6006", {})
    assert parse_bt_url("bt://My%20Supply") == ("My Supply", {})


def test_parse_bt_url_options() -> None:
    target, kwargs = parse_bt_url(
        "bt://aa:bb:cc:dd:ee:ff/?connect_timeout=3"
    )
    assert target == "aa:bb:cc:dd:ee:ff"
    assert kwargs == {"connect_timeout": 3.0}


@pytest.mark.parametrize(
    "url",
    [
        "serial://AA:BB:CC:DD:EE:FF",
        "bt://",
        "bt://AA:BB:CC:DD:EE:FF/extra",
        "bt://AA:BB:CC:DD:EE:FF?connect_timeout=abc",
        "bt://AA:BB:CC:DD:EE:FF?connect_timeout=",
        # Channel and security belonged to the Classic SPP transport.
        "bt://AA:BB:CC:DD:EE:FF?channel=1",
        "bt://AA:BB:CC:DD:EE:FF?security=low",
        # The read timeout is an argument, not a URL parameter.
        "bt://AA:BB:CC:DD:EE:FF?timeout=0.5",
        "bt://AA:BB:CC:DD:EE:FF?timout=1",
    ],
)
def test_parse_bt_url_rejects_invalid(url: str) -> None:
    with pytest.raises(ValueError):
        parse_bt_url(url)


def test_serial_for_url_keeps_bt_serial_defaults() -> None:
    import riden  # noqa: F401  (registers the bt:// handler)

    port = cast(
        BtSerial, serial.serial_for_url("bt://AA:BB:CC:DD:EE:FF", do_not_open=True)
    )
    default = BtSerial()
    assert port.connect_timeout == default.connect_timeout
    assert port.timeout == default.timeout


def test_serial_for_url_returns_configured_bt_serial() -> None:
    import riden  # noqa: F401  (registers the bt:// handler)

    port = cast(
        BtSerial,
        serial.serial_for_url(
            "bt://AA:BB:CC:DD:EE:FF?connect_timeout=3",
            timeout=2,
            do_not_open=True,
        ),
    )
    assert isinstance(port, BtSerial)
    assert port.port == "AA:BB:CC:DD:EE:FF"
    assert port.connect_timeout == 3
    assert port.timeout == 2
    assert not port.is_open


def test_is_a_pyserial_port() -> None:
    port = BtSerial()
    assert isinstance(port, serial.SerialBase)
    default = serial.Serial()
    assert (port.baudrate, port.timeout, port.write_timeout) == (
        default.baudrate,
        default.timeout,
        default.write_timeout,
    )


def test_open_connects_and_close_is_idempotent(port: BtSerial) -> None:
    assert port.is_open
    assert client().connected
    port.close()
    assert not port.is_open
    assert client().disconnected
    port.close()


def test_open_without_port_raises() -> None:
    with pytest.raises(serial.SerialException, match="Port must be configured"):
        BtSerial().open()


def test_write_sends_a_modbus_sized_frame(port: BtSerial) -> None:
    frame = bytes.fromhex("010300000001840a")
    assert port.write(frame) == len(frame)
    assert client().writes == [(WRITE_UUID, frame, False)]


def test_write_chunks_large_payload(port: BtSerial) -> None:
    payload = b"x" * 50
    assert port.write(payload) == 50
    assert [len(data) for _, data, _ in client().writes] == [20, 20, 10]


def test_read_collects_notifications(port: BtSerial) -> None:
    client().notify(b"ab")
    client().notify(b"cd")
    assert port.read(4) == b"abcd"


def test_non_blocking_read_returns_available_bytes(port: BtSerial) -> None:
    port.timeout = 0
    client().notify(b"xy")
    assert port.read(5) == b"xy"
    assert port.read(5) == b""


def test_timed_read_returns_partial_data(port: BtSerial) -> None:
    port.timeout = 0.05
    client().notify(b"xy")
    started = time.monotonic()
    assert port.read(5) == b"xy"
    assert time.monotonic() - started < 1


def test_inter_byte_timeout_ends_read(port: BtSerial) -> None:
    port.timeout = None
    port.inter_byte_timeout = 0.05
    client().notify(b"xy")
    started = time.monotonic()
    assert port.read(5) == b"xy"
    assert time.monotonic() - started < 1


def test_zero_size_read_returns_empty(port: BtSerial) -> None:
    assert port.read(0) == b""


def test_in_waiting_and_reset_input_buffer(port: BtSerial) -> None:
    client().notify(b"abc")
    assert port.in_waiting == 3
    port.reset_input_buffer()
    assert port.in_waiting == 0


def test_readline_comes_from_serialbase(port: BtSerial) -> None:
    port.timeout = 0.05
    client().notify(b"one\ntwo")
    assert port.readline() == b"one\n"


def test_peer_disconnect_wakes_read(port: BtSerial) -> None:
    client().drop()
    with pytest.raises(serial.SerialException, match="closed the link"):
        port.read(1)


def test_connect_failure_is_a_serial_exception(fake: type[FakeClient]) -> None:
    FakeClient.fail_connect = True
    with pytest.raises(serial.SerialException, match="connect failed"):
        BtSerial("AA:BB:CC:DD:EE:FF", timeout=1)


def test_name_is_resolved_with_a_scan(
    fake: type[FakeClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, float]] = []

    async def find_device_by_name(name: str, timeout: float = 10.0) -> str:
        calls.append((name, timeout))
        return "scanned-device"

    monkeypatch.setattr(
        bt_serial.BleakScanner,
        "find_device_by_name",
        find_device_by_name,
    )
    port = BtSerial("RK6006", timeout=1)
    try:
        assert calls == [("RK6006", 10)]
        assert client().address == "scanned-device"
    finally:
        port.close()


def test_unknown_name_raises(
    fake: type[FakeClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def not_found(name: str, timeout: float = 10.0) -> None:
        return None

    monkeypatch.setattr(
        bt_serial.BleakScanner,
        "find_device_by_name",
        not_found,
    )
    with pytest.raises(serial.SerialException, match="device not found"):
        BtSerial("RK6006", timeout=1)


@pytest.mark.parametrize("op", ["read", "write", "in_waiting", "reset_input_buffer"])
def test_closed_serial_raises(op: str) -> None:
    port = BtSerial()
    assert not port.is_open
    with pytest.raises(serial.PortNotOpenError):
        attr = getattr(port, op)
        if op == "write":
            attr(b"x")
        elif callable(attr):
            attr()


def test_non_blocking_write_returns_length(port: BtSerial) -> None:
    port.write_timeout = 0
    assert port.write(b"abc") == 3
    deadline = time.monotonic() + 1
    while not client().writes and time.monotonic() < deadline:
        time.sleep(0.01)
    assert client().writes == [(WRITE_UUID, b"abc", False)]


def test_noop_helpers_do_not_raise(port: BtSerial) -> None:
    port.flush()
    port.reset_output_buffer()
    port.send_break()
    port.rts = False
    port.dtr = False
    port.baudrate = 19200
    assert (port.cts, port.dsr, port.ri, port.cd) == (True, True, False, True)


def test_fileno_is_unsupported(port: BtSerial) -> None:
    with pytest.raises(io.UnsupportedOperation):
        port.fileno()


def test_minimalmodbus_round_trip(port: BtSerial) -> None:
    fake_client = client()

    async def respond(uuid: str, data: bytes, response: bool | None = None) -> None:
        fake_client.writes.append((uuid, bytes(data), response))
        # Response to "read register 0": value 60122 (0xEADA).
        fake_client.notify(bytes.fromhex("010302eada76bf"))

    fake_client.write_gatt_char = respond  # type: ignore[method-assign]
    instrument = minimalmodbus.Instrument(cast(serial.Serial, port), 1)
    assert instrument.read_register(0) == 60122
