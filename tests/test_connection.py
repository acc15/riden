"""Tests for tmodbus client construction."""

from typing import cast

from bleak.backends.device import BLEDevice
from tmodbus import AsyncModbusClient

from riden.ble import BleTransport
from riden.connection import ModbusClient, make_client


def test_make_client_returns_a_prebuilt_client() -> None:
    fake = cast(ModbusClient, object())
    assert make_client(fake) is fake


def test_make_client_builds_ble_without_io() -> None:
    client = make_client("bt://AA:BB:CC:DD:EE:FF", timeout=0.5)
    assert isinstance(client, AsyncModbusClient)


def test_make_client_builds_serial_without_io() -> None:
    client = make_client("/dev/ttyUSB0", baudrate=9600, timeout=0.5)
    assert isinstance(client, AsyncModbusClient)


def test_make_client_accepts_a_bledevice() -> None:
    device = BLEDevice(
        "AA:BB:CC:DD:EE:FF",
        "RK6006",
        {"path": "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF", "props": {}},
    )
    client = make_client(device, timeout=0.5, connect_timeout=3)
    assert isinstance(client, AsyncModbusClient)


def test_make_client_wraps_a_prebuilt_ble_transport() -> None:
    transport = BleTransport("AA:BB:CC:DD:EE:FF", timeout=0.5)
    client = make_client(transport)
    assert isinstance(client, AsyncModbusClient)
