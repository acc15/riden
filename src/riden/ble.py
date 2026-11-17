"""Bluetooth Low Energy transport for tmodbus.

Riden's BLE module is a transparent UART: Modbus RTU frames are written to the
``FFE2`` characteristic and replies arrive as notifications from ``FFE1``
(service ``FFE0``).  This module adapts that link to tmodbus's
:class:`~tmodbus.transport.async_base.AsyncBaseTransport`, reusing tmodbus's
:class:`~tmodbus.transport.async_rtu.ModbusRtuProtocol` for RTU framing, CRC
validation, timeouts and resynchronisation.

A pyserial-like shim is deliberately absent: the whole client is asyncio-based,
so BLE and the Modbus client share the caller's event loop.
"""

import asyncio
import contextlib
from dataclasses import dataclass
from typing import Any, override

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from tmodbus.exceptions import ModbusConnectionError
from tmodbus.transport.async_base import AsyncBaseTransport
from tmodbus.transport.async_rtu import ModbusRtuProtocol

# Riden's BLE UART: FFE2 carries writes, FFE1 delivers notifications.
NOTIFY_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"
WRITE_UUID = "0000ffe2-0000-1000-8000-00805f9b34fb"

# ATT's default payload.  Riden's normal Modbus writes fit in one chunk (a
# five-register preset is 19 bytes).
_CHUNK_SIZE = 20


class _BleWriteTransport(asyncio.WriteTransport):
    """Minimal asyncio write transport that feeds bytes into a BLE UART.

    ``ModbusRtuProtocol`` calls ``write()`` synchronously and then awaits the
    response.  Each call schedules one GATT write task; the protocol's request
    lock guarantees that only one Modbus frame is on the wire at a time.
    """

    def __init__(
        self,
        client: BleakClient,
        write_uuid: str,
        chunk_size: int,
        protocol: ModbusRtuProtocol,
    ):
        super().__init__()
        self._client = client
        self._write_uuid = write_uuid
        self._chunk_size = chunk_size
        self._protocol = protocol
        self._tasks: set[asyncio.Task[None]] = set()
        self._closing = False

    @override
    def write(self, data: bytes | bytearray | memoryview) -> None:
        if self._closing:
            return
        payload = bytes(data)
        task = asyncio.create_task(self._write(payload))
        self._tasks.add(task)
        task.add_done_callback(self._task_done)

    def _task_done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if isinstance(exc, Exception):
            self._protocol.connection_lost(exc)

    async def _write(self, data: bytes) -> None:
        for offset in range(0, len(data), self._chunk_size):
            await self._client.write_gatt_char(
                self._write_uuid,
                data[offset : offset + self._chunk_size],
                response=False,
            )

    @override
    def is_closing(self) -> bool:
        return self._closing

    @override
    def close(self) -> None:
        self._closing = True
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()


class BleTransport(AsyncBaseTransport):
    """tmodbus transport over a Riden BLE UART.

    ``target`` is a BLE address or an already discovered ``BLEDevice``.
    Passing a ``BLEDevice`` avoids the internal BlueZ scan and is useful when
    several supplies are opened together: one scan can feed all of them.
    """

    @dataclass(frozen=True, slots=True)
    class State:
        """One fully established BLE link."""

        client: BleakClient
        protocol: ModbusRtuProtocol
        write_transport: _BleWriteTransport

    def __init__(
        self,
        target: str | BLEDevice,
        *,
        timeout: float = 1.0,
        connect_timeout: float = 10.0,
        notify_uuid: str = NOTIFY_UUID,
        write_uuid: str = WRITE_UUID,
        chunk_size: int = _CHUNK_SIZE,
    ):
        self.target = target
        self.timeout = timeout
        self.connect_timeout = connect_timeout
        self.notify_uuid = notify_uuid
        self.write_uuid = write_uuid
        self.chunk_size = chunk_size

        # Exactly one link state: either a fully established connection or
        # nothing.  There is no partially connected state to inspect.
        self._state: BleTransport.State | None = None

    @override
    async def open(self) -> None:
        if self.is_open():
            return
        if self._state is not None:
            await self.close()

        client = BleakClient(
            self.target,
            disconnected_callback=self._on_disconnect,
            timeout=self.connect_timeout,
        )
        protocol = ModbusRtuProtocol(
            on_connection_lost=self._on_protocol_lost,
            timeout=self.timeout,
            interframe_delay=0.0,
        )
        # Both objects are passive; creating them before connect() keeps the
        # failure path uniform: nothing can be left half-initialised.
        write_transport = _BleWriteTransport(
            client, self.write_uuid, self.chunk_size, protocol
        )

        try:
            await client.connect()
            await client.start_notify(self.notify_uuid, self._on_notify)
            protocol.connection_made(write_transport)
        except BaseException:
            write_transport.close()
            with contextlib.suppress(Exception):
                await client.disconnect()
            raise

        self._state = BleTransport.State(client, protocol, write_transport)

    @override
    async def close(self) -> None:
        state = self._state
        if state is None:
            return
        # Clearing the state first makes close() idempotent and tells the
        # callbacks below that a disconnect is intentional, not a link loss.
        self._state = None
        state.protocol.connection_lost(None)
        state.write_transport.close()
        with contextlib.suppress(Exception):
            await state.client.disconnect()

    @override
    def is_open(self) -> bool:
        state = self._state
        return state is not None and state.client.is_connected

    @override
    async def send_and_receive(self, unit_id: int, pdu: Any) -> Any:
        state = self._state
        if state is None or not state.client.is_connected:
            raise ModbusConnectionError("Transport is not connected.")
        return await state.protocol.send_and_receive(unit_id, pdu)

    def _on_notify(self, _sender: Any, data: bytearray) -> None:
        state = self._state
        if state is not None:
            state.protocol.data_received(bytes(data))

    def _on_disconnect(self, _client: BleakClient) -> None:
        state = self._state
        if state is not None:
            state.protocol.connection_lost(None)

    def _on_protocol_lost(self, exc: Exception | None) -> None:
        if self._state is not None:
            self._notify_connection_lost(exc)
