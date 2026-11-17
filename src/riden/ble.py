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
from collections.abc import Callable, Coroutine
from typing import Any, override

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from tmodbus.exceptions import ModbusConnectionError
from tmodbus.transport.async_base import AsyncBaseTransport
from tmodbus.transport.async_rtu import ModbusRtuProtocol

# Riden's BLE UART: FFE2 carries writes, FFE1 delivers notifications.
NOTIFY_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"
WRITE_UUID = "0000ffe2-0000-1000-8000-00805f9b34fb"


class DelegatingWriteTransport(asyncio.WriteTransport):
    """One fully established BLE link and its write channel.

    ``ModbusRtuProtocol`` calls ``write()`` synchronously and then awaits the
    response.  Each call schedules one GATT write task; the protocol's request
    lock guarantees that only one Modbus frame is on the wire at a time.
    """

    def __init__(
        self,
        on_write: Callable[[bytes], Coroutine[Any, Any, None]],
        on_error: Callable[[Exception], None]
    ):
        super().__init__()
        self.on_write = on_write
        self.on_error = on_error 
        self._tasks: set[asyncio.Task[None]] = set()
        self._closing = False

    @override
    def write(self, data: bytes | bytearray | memoryview) -> None:
        if self._closing:
            return
        payload = bytes(data)
        task = asyncio.create_task(self.on_write(payload))
        self._tasks.add(task)
        task.add_done_callback(self._task_done)

    def _task_done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if isinstance(exc, Exception):
            self.on_error(exc)

    @override
    def is_closing(self) -> bool:
        return self._closing

    @override
    def close(self) -> None:
        self._closing = True
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()


class BleSession:
    """One fully established BLE link."""

    client: BleakClient
    protocol: ModbusRtuProtocol
    write_transport: DelegatingWriteTransport

    def __init__(
        self,
        transport: BleTransport
    ):
        self.protocol = ModbusRtuProtocol(
            on_connection_lost=transport._notify_connection_lost,
            timeout=transport.timeout,
            interframe_delay=0.0,
        )
        self.client = BleakClient(
            transport.target,
            disconnected_callback=lambda _: self.protocol.connection_lost(None),
            timeout=transport.connect_timeout,
        )
        self.write_transport = DelegatingWriteTransport(self.write, self.protocol.connection_lost)
        self.write_uuid = transport.write_uuid
        self.notify_uuid = transport.notify_uuid

    async def open(self):
        try:
            await self.client.connect()
            await self.client.start_notify(
                self.notify_uuid, 
                lambda _, data: self.protocol.data_received(bytes(data))
            )
            self.protocol.connection_made(self.write_transport)
        except BaseException:
            self.write_transport.close()
            with contextlib.suppress(Exception):
                await self.client.disconnect()
            raise

    async def write(self, data: bytes):
        await self.client.write_gatt_char(self.write_uuid, data, response=True)


    async def close(self):
        self.protocol.connection_lost(None)
        self.write_transport.close()
        with contextlib.suppress(Exception):
            await self.client.disconnect()



class BleTransport(AsyncBaseTransport):
    """tmodbus transport over a Riden BLE UART.

    ``target`` is a BLE address or an already discovered ``BLEDevice``.
    Passing a ``BLEDevice`` avoids the internal BlueZ scan and is useful when
    several supplies are opened together: one scan can feed all of them.
    """

    def __init__(
        self,
        target: str | BLEDevice,
        *,
        timeout: float = 1.0,
        connect_timeout: float = 10.0,
        notify_uuid: str = NOTIFY_UUID,
        write_uuid: str = WRITE_UUID,
    ):
        self.target = target
        self.timeout = timeout
        self.connect_timeout = connect_timeout
        self.notify_uuid = notify_uuid
        self.write_uuid = write_uuid

        # Exactly one link state: either a fully established connection or
        # nothing.  There is no partially connected state to inspect.
        self._session: BleSession | None = None

    @override
    async def open(self) -> None:
        if (old_session := self._session) is not None:
            if old_session.client.is_connected:
                return
            self._session = None
            await old_session.close()
        session = BleSession(self)
        await session.open()
        self._session = session

    @override
    async def close(self) -> None:
        if (session := self._session) is None:
            return
        # Clearing the state first makes close() idempotent and tells the
        # callbacks below that a disconnect is intentional, not a link loss.
        self._session = None
        await session.close()

    @override
    def is_open(self) -> bool:
        return (session := self._session) is not None and session.client.is_connected

    @override
    async def send_and_receive(self, unit_id: int, pdu: Any) -> Any:
        if (session := self._session) is None or not session.client.is_connected:
            raise ModbusConnectionError("Transport is not connected.")
        return await session.protocol.send_and_receive(unit_id, pdu)

