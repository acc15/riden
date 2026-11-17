"""Asynchronous client for Riden power supplies."""
import contextlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, Self, override

import tmodbus
from bleak.backends.device import BLEDevice
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_fixed,
)
from tmodbus import AsyncModbusClient
from tmodbus.transport import AsyncBaseTransport
from tmodbus.transport.async_smart import AsyncSmartTransport

from .ble import BleTransport
from .field import Field, flatten_fields, merge_fields
from .layout import Layout
from .model import Model
from .register import Registers


class ModbusClient(Protocol):
    """Minimal tmodbus client surface used by Riden."""
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def read_holding_registers(self, start_address: int, quantity: int) -> list[int]: ...
    async def write_multiple_registers(self, start_address: int, values: list[int]) -> int: ...


DEFAULT_BAUDRATE = 115200
DEFAULT_TIMEOUT = 1
DEFAULT_CONNECT_TIMEOUT = 10.0
DEFAULT_DELAY = 0.02
DEFAULT_RESPONSE_RETRY = AsyncRetrying(
    retry=retry_if_exception_type(TimeoutError),
    stop=stop_after_attempt(3),
    wait=wait_fixed(0.2),
)
BT_PREFIX = "bt://"

type ClientSource = str | ModbusClient | AsyncBaseTransport | BLEDevice


class Riden:
    """Async Riden power supply client.

    Construction parses the port URL and builds a tmodbus client without
    doing I/O.  ``async with`` (or ``await open()``) connects and reads the
    identity; ``read`` and ``write`` are coroutines.

    The common case is a single call:

        async with Riden.connect("bt://E1:F9:C6:24:71:C8") as rd:
            print(await rd.read("v", "i", "p"))

    A custom tmodbus client can be passed directly.
    """

    @dataclass(frozen=True, slots=True)
    class State:
        """Identity of the connected device and its register map.

        ``layout`` is built once by open() from the model's layout and is
        read-only: a connected client uses exactly one map.
        """

        client: ModbusClient
        id: int
        sn: int
        fw: float
        model: Model
        layout: Layout

    def __init__(self, client: ModbusClient):
        self.client = client
        self.state: Riden.State | None = None

    def require_state(self) -> Riden.State:
        state = self.state
        if state is None:
            raise RuntimeError("Riden is not initialized")
        return state

    @classmethod
    def connect(
        cls,
        port: ClientSource,
        address: int = 1,
        *,
        baudrate: int = DEFAULT_BAUDRATE,
        timeout: float = DEFAULT_TIMEOUT,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        delay: float = DEFAULT_DELAY,
        auto_reconnect: bool = True,
        response_retry: AsyncRetrying | None = DEFAULT_RESPONSE_RETRY
    ) -> Self:
        """Return a client for a serial port or a Bluetooth LE URL.

        Construction does no I/O; the returned client is opened by
        ``async with`` or ``await open()``.  ``timeout`` is the Modbus
        response timeout in seconds, ``delay`` the pause between transactions,
        and ``auto_reconnect`` enables tmodbus's automatic reconnect.

        ``bt://`` URLs pass everything after the scheme to bleak as the BLE
        address; ``connect_timeout`` is a regular argument::

            Riden.connect("bt://E1:F9:C6:24:71:C8", connect_timeout=5)

        A plain path or a serialx URL creates an async RTU client; ``baudrate``
        applies only to that serial transport.  A ``BLEDevice`` from one shared
        scan is wrapped directly; a prebuilt ``BleTransport`` is accepted when
        its UUIDs or settings need to be customised.
        """
        # Return a configured client; construction performs no I/O.  A path
        # or a ``serialx`` URL creates an async RTU client.  A ``bt://`` URL
        # creates a BLE transport wrapped in tmodbus's smart transport for
        # pacing and reconnect.  An already constructed client is returned
        # unchanged, which keeps tests and custom transports easy.
        if isinstance(port, str):
            port = port.strip()
            if port.lower().startswith(BT_PREFIX):
                target = port[len(BT_PREFIX):].strip()
                if not target:
                    raise ValueError(f"no Bluetooth address in URL: {port!r}")
                port = target
            else:
                port = tmodbus.AsyncRtuTransport(
                    port,
                    timeout=timeout,
                    baudrate=baudrate,
                    connect_timeout=connect_timeout,
                )

        if isinstance(port, (str, BLEDevice)):
            port = BleTransport(
                port,
                timeout=timeout,
                connect_timeout=connect_timeout,
            )

        if isinstance(port, AsyncBaseTransport):
            if response_retry is not None or delay > 0 or auto_reconnect:
                port = AsyncSmartTransport(
                    port,
                    wait_between_requests=delay,
                    auto_reconnect=auto_reconnect,
                    response_retry_strategy=response_retry,
                )
            port = AsyncModbusClient(port, unit_id=address)

        return cls(port)

    async def open(self) -> Self:
        if self.state is not None:
            return self

        try:
            await self.client.connect()
            # Identification is I/O, so it belongs to open(), not __init__.
            raw = await self.client.read_holding_registers(0, 4)
            model = Model.find(raw[0])
            layout = model.value.layout()
            decoded = layout.decode(tuple(raw), 0, layout.readers(layout.dependency_order((Field.ID, Field.SN, Field.FW))))
            self.state = Riden.State(
                client=self.client,
                id=decoded["id"],
                sn=decoded["sn"],
                fw=decoded["fw"],
                model=model,
                layout=layout,
            )
        except BaseException:
            # __aexit__ is not called when __aenter__ raises.
            with contextlib.suppress(Exception):
                await self.client.disconnect()
            raise
        return self

    async def read(self, *fields: str | Iterable[str]) -> dict[str, Any]:
        """Return the requested fields, keyed by name.

        Fields that are only needed to decode another one are read but are not
        part of the result, so a request for one field returns exactly it.
        """
        state = self.require_state()
        layout = state.layout

        # dict.fromkeys() flattens, normalizes and deduplicates in one pass,
        # while preserving the requested order.
        requested = list(dict.fromkeys(flatten_fields(fields)))
        if not requested:
            return {}

        # Dependencies are decoded before their dependents; unsupported
        # fields and cycles fail here, before any I/O.
        order = layout.dependency_order(requested)

        # Readability is validated (and codecs collected) by the layout,
        # before any I/O.
        readers = layout.readers(order)

        span = layout.register_span(order)
        regs: Registers = ()
        start = 0
        if span is not None:
            start, count = span
            regs = tuple(await state.client.read_holding_registers(start, count))

        values = layout.decode(regs, start, readers)

        # Dependencies are not part of the result: only what was requested.
        return {field.value: values[field.value] for field in requested}

    async def write(
        self,
        *values: Mapping[str, Any] | Mapping[Field, Any],
        **fields: Any,
    ) -> None:
        state = self.require_state()
        layout = state.layout

        updates = merge_fields(*values, fields)
        if not updates:
            return

        # Support and writability are validated (and codecs collected) by the
        # layout, before any I/O.
        writers = layout.writers(updates)

        # A codec is encoded with the fields it declares in deps.  What the
        # caller supplied is used as-is; everything else is read first, in one
        # transaction, together with its own transitive dependencies.
        missing = layout.dependency_order(updates, supplied=updates.keys())
        dependencies = await self.read(*missing) if missing else {}

        # Reads are keyed by name and updates by Field; Field is a str
        # subclass, so the merged map answers both kinds of lookup.
        values_by_field: dict[str, Any] = {**dependencies, **updates}

        # Encode and validate everything before touching the bus, so an invalid
        # value does not leave the device partially updated.
        encoded = layout.encode(updates, writers, values_by_field)

        # Adjacent registers share one transaction; a block that another block
        # depends on is written first.
        for start, regs in layout.write_blocks(encoded):
            await state.client.write_multiple_registers(start, list(regs))

    def identity(self) -> str:
        state = self.require_state()
        return f"model={state.model} type={state.id} sn={state.sn:08X} fw={state.fw:.2f}"

    async def close(self) -> None:
        state = self.state
        if state is None:
            return
        self.state = None
        await state.client.disconnect()

    @override
    def __repr__(self) -> str:
        state = self.state
        if state is None:
            return f"{type(self).__name__}(closed)"
        return f"{type(self).__name__}({state.model.name})"

    async def __aenter__(self) -> Self:
        return await self.open()

    async def __aexit__(self, *_):
        await self.close()

    _STATUS_ROWS = (
        ("input", (Field.V_IN,), "{:.2f}V"),
        ("set", (Field.V_SET, Field.I_SET), "{:.3f} V, {:.3f} A"),
        ("output", (Field.V, Field.I, Field.P), "{:.3f} V, {:.3f} A, {:.3f} W"),
        ("enabled", (Field.EN,), "{}"),
        ("mode", (Field.MODE,), "{}"),
        ("protection", (Field.PROTECTION,), "{}"),
        ("temp", (Field.TEMP_C,), "{} C"),
    )

    async def status(self) -> str:
        fields: list[Field] = []
        for _, row_fields, _ in self._STATUS_ROWS:
            fields.extend(row_fields)
        values = await self.read(*dict.fromkeys(fields))

        rows = [
            (label, template.format(*(values[field] for field in row_fields)))
            for label, row_fields, template in self._STATUS_ROWS
        ]
        width = max(len(label) for label, _ in rows) + 2
        body = "\n".join(f"{label + ':':<{width}}{value}" for label, value in rows)
        return f"{self.identity()}\n{body}"
