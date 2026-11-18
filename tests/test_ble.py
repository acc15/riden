"""Lifecycle tests for the BLE transport, using fake Bleak and Modbus objects."""

import asyncio
from typing import Any, ClassVar

import pytest

from riden import ble


class FakeBleakClient:
    instances: ClassVar[list[FakeBleakClient]] = []
    next_connect_error: BaseException | None = None
    next_disconnect_error: BaseException | None = None
    next_start_notify_error: BaseException | None = None

    def __init__(
        self,
        target: Any,
        *,
        disconnected_callback: Any = None,
        timeout: float = 10.0,
    ) -> None:
        self.target = target
        self.disconnected_callback = disconnected_callback
        self.timeout = timeout
        self.is_connected = False
        self.connect_calls = 0
        self.disconnect_calls = 0
        self.start_notify_calls = 0
        self.writes: list[tuple[str, bytes, bool]] = []
        self.connect_error = type(self).next_connect_error
        self.disconnect_error = type(self).next_disconnect_error
        self.start_notify_error = type(self).next_start_notify_error
        self.write_error: Exception | None = None
        self.disconnect_started: asyncio.Event | None = None
        self.disconnect_gate: asyncio.Event | None = None
        type(self).instances.append(self)

    @classmethod
    def reset(cls) -> None:
        cls.instances.clear()
        cls.next_connect_error = None
        cls.next_disconnect_error = None
        cls.next_start_notify_error = None

    async def connect(self) -> None:
        self.connect_calls += 1
        if self.connect_error is not None:
            raise self.connect_error
        self.is_connected = True

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        if self.disconnect_started is not None:
            self.disconnect_started.set()
        if self.disconnect_gate is not None:
            await self.disconnect_gate.wait()
        was_connected = self.is_connected
        self.is_connected = False
        if was_connected and self.disconnected_callback is not None:
            self.disconnected_callback(self)
        if self.disconnect_error is not None:
            raise self.disconnect_error

    async def start_notify(self, _uuid: str, callback: Any) -> None:
        self.start_notify_calls += 1
        if self.start_notify_error is not None:
            raise self.start_notify_error
        self.notify_callback = callback

    async def write_gatt_char(
        self, uuid: str, data: bytes, response: bool
    ) -> None:
        self.writes.append((uuid, bytes(data), response))
        if self.write_error is not None:
            raise self.write_error

    def simulate_disconnect(self) -> None:
        self.is_connected = False
        if self.disconnected_callback is not None:
            self.disconnected_callback(self)


class FakeProtocol:
    instances: ClassVar[list[FakeProtocol]] = []

    def __init__(
        self,
        *,
        on_connection_lost: Any,
        timeout: float,
        interframe_delay: float,
    ) -> None:
        self.on_connection_lost = on_connection_lost
        self.timeout = timeout
        self.interframe_delay = interframe_delay
        self.connection_lost_calls: list[Exception | None] = []
        self.connection_made_calls: list[Any] = []
        self.data_received_calls: list[bytes] = []
        type(self).instances.append(self)

    @classmethod
    def reset(cls) -> None:
        cls.instances.clear()

    def connection_made(self, transport: Any) -> None:
        self.connection_made_calls.append(transport)

    def connection_lost(self, exc: Exception | None) -> None:
        self.connection_lost_calls.append(exc)
        self.on_connection_lost(exc)

    def data_received(self, data: bytes) -> None:
        self.data_received_calls.append(data)

    async def send_and_receive(self, unit_id: int, pdu: Any) -> Any:
        return unit_id, pdu


@pytest.fixture(autouse=True)
def fake_ble(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeBleakClient.reset()
    FakeProtocol.reset()
    monkeypatch.setattr(ble, "BleakClient", FakeBleakClient)
    monkeypatch.setattr(ble, "ModbusRtuProtocol", FakeProtocol)


async def open_transport() -> tuple[
    ble.BleTransport,
    list[Exception | None],
    FakeBleakClient,
    FakeProtocol,
    ble.BleSession,
]:
    transport = ble.BleTransport("AA:BB:CC:DD:EE:FF")
    lost: list[Exception | None] = []
    transport.on_connection_lost = lost.append
    await transport.open()
    session = transport._session
    assert session is not None
    return (
        transport,
        lost,
        FakeBleakClient.instances[-1],
        FakeProtocol.instances[-1],
        session,
    )


async def drain_writes(session: ble.BleSession) -> None:
    for _ in range(10):
        if not session.write_transport._tasks:
            return
        await asyncio.sleep(0)
    raise AssertionError("write tasks did not finish")


async def test_clean_close_is_idempotent_and_does_not_notify() -> None:
    transport, lost, client, protocol, session = await open_transport()

    await transport.close()
    await transport.close()

    assert lost == []
    assert protocol.connection_lost_calls == [None]
    assert client.disconnect_calls == 1
    assert session.lost
    assert not transport.is_open()


async def test_unexpected_disconnect_notifies_once() -> None:
    transport, lost, client, protocol, session = await open_transport()

    client.simulate_disconnect()

    assert lost == [None]
    assert protocol.connection_lost_calls == [None]
    assert session.lost
    assert not transport.is_open()

    await transport.close()

    assert lost == [None]
    assert protocol.connection_lost_calls == [None]


async def test_multiple_write_errors_notify_once() -> None:
    transport, lost, client, protocol, session = await open_transport()
    error = RuntimeError("write failed")
    client.write_error = error

    session.write_transport.write(b"\x01")
    session.write_transport.write(b"\x02")
    await drain_writes(session)

    assert lost == [error]
    assert protocol.connection_lost_calls == [error]
    assert session.lost
    assert not transport.is_open()

    await transport.close()

    assert lost == [error]
    assert protocol.connection_lost_calls == [error]


async def test_open_after_write_error_creates_a_new_session() -> None:
    transport, lost, client, protocol, session = await open_transport()
    error = RuntimeError("write failed")
    client.write_error = error

    session.write_transport.write(b"\x01")
    await drain_writes(session)
    assert lost == [error]

    await transport.open()

    assert len(FakeBleakClient.instances) == 2
    assert len(FakeProtocol.instances) == 2
    assert transport.is_open()
    assert lost == [error]
    assert protocol.connection_lost_calls == [error]


async def test_failed_start_notify_does_not_notify() -> None:
    FakeBleakClient.next_start_notify_error = RuntimeError("notify failed")
    transport = ble.BleTransport("AA:BB:CC:DD:EE:FF")
    lost: list[Exception | None] = []
    transport.on_connection_lost = lost.append

    with pytest.raises(RuntimeError, match="notify failed"):
        await transport.open()

    assert transport._session is None
    assert lost == []
    client = FakeBleakClient.instances[-1]
    protocol = FakeProtocol.instances[-1]
    assert client.disconnect_calls == 1
    assert protocol.connection_lost_calls == [None]


async def test_close_suppresses_disconnect_error() -> None:
    transport, lost, client, protocol, _ = await open_transport()
    client.disconnect_error = RuntimeError("disconnect failed")

    await transport.close()

    assert lost == []
    assert protocol.connection_lost_calls == [None]


async def test_cancelled_close_still_calls_connection_lost() -> None:
    transport, lost, client, protocol, session = await open_transport()
    started = asyncio.Event()
    gate = asyncio.Event()
    client.disconnect_started = started
    client.disconnect_gate = gate

    task = asyncio.create_task(session.close())
    await started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert lost == []
    assert protocol.connection_lost_calls == [None]
    assert transport.is_open() is False
