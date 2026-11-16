"""Asynchronous client for Riden power supplies."""
import contextlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Self, override

from tenacity import AsyncRetrying

from .connection import (
    DEFAULT_BAUDRATE,
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_DELAY,
    DEFAULT_RESPONSE_RETRY,
    DEFAULT_TIMEOUT,
    ClientSource,
    ModbusClient,
    make_client,
)
from .field import Field, flatten_fields, merge_fields
from .layout import Layout
from .model import Model
from .register import Registers, RegRead, RegWrite


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
        timeout: float | None = DEFAULT_TIMEOUT,
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
        client = make_client(
            port,
            address,
            baudrate=baudrate,
            timeout=timeout,
            connect_timeout=connect_timeout,
            delay=delay,
            auto_reconnect=auto_reconnect,
            response_retry=response_retry,
        )
        return cls(client)

    async def open(self) -> Self:
        if self.state is not None:
            return self

        try:
            await self.client.connect()
            # Identification is I/O, so it belongs to open(), not __init__.
            values = await self.client.read_holding_registers(0, 4)
            model = Model.find(values[0])
            self.state = Riden.State(
                client=self.client,
                id=values[0],
                sn=values[1] << 16 | values[2],
                fw=values[3] / 100.0,
                model=model,
                layout=model.value.layout(),
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

        # Validate and collect readers in one pass.  This reports all
        # unreadable fields before I/O and narrows away the optional ``None``
        # in Register.read for the type checker.  Dependencies are validated
        # too: an unreadable dependency breaks the whole request.
        readers: dict[Field, RegRead] = {}
        not_readable: list[str] = []
        for field in order:
            read = layout.registers[field].read
            if read is None:
                not_readable.append(field.value)
            else:
                readers[field] = read
        if not_readable:
            raise ValueError(f"fields are not readable: {', '.join(not_readable)}")

        span = layout.register_span(order)
        regs: Registers = ()
        start = 0
        if span is not None:
            start, count = span
            regs = tuple(await state.client.read_holding_registers(start, count))

        # Each codec gets only the fields it declared in deps, never the
        # whole decoded map.  Keys are field names, so the result is already
        # in the shape the public API returns.
        values: dict[str, Any] = {}
        for field in order:
            register = layout.registers[field]
            if register.size == 0:
                raw: Registers = ()
            else:
                index = register.addr - start
                raw = regs[index:index + register.size]
            values[field.value] = readers[field](raw, register.make_deps(values))

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

        # Validate and collect writers in one pass, exactly like read().
        # All unsupported and unwritable fields are reported before any I/O.
        writers: dict[Field, RegWrite] = {}
        unsupported: list[str] = []
        not_writable: list[str] = []
        for field in updates:
            register = layout.registers.get(field)
            if register is None:
                unsupported.append(field.value)
            elif register.write is None:
                not_writable.append(field.value)
            else:
                writers[field] = register.write

        if unsupported:
            raise ValueError(f"fields are not supported: {', '.join(unsupported)}")
        if not_writable:
            raise ValueError(f"fields are not writable: {', '.join(not_writable)}")

        # A codec is encoded with the fields it declares in deps.  What the
        # caller supplied is used as-is; everything else is read first, in one
        # transaction, together with its own transitive dependencies.
        missing = layout.dependency_order(updates, supplied=updates.keys())
        dependencies = await self.read(*missing) if missing else {}

        # Encode and validate everything before touching the bus, so an invalid
        # value does not leave the device partially updated.
        # Reads are keyed by name and updates by Field; Field is a str
        # subclass, so the merged map answers both kinds of lookup.
        values_by_field: dict[str, Any] = {**dependencies, **updates}
        encoded: dict[Field, Registers] = {}
        for field, value in updates.items():
            register = layout.registers[field]
            try:
                regs = writers[field](value, register.make_deps(values_by_field))
            except ValueError as exc:
                raise ValueError(f"field {field.value}: {exc}") from exc
            if len(regs) != register.size:
                raise ValueError(
                    f"field {field.value} produced {len(regs)} registers, "
                    f"expected {register.size}"
                )
            if any(reg < 0 or reg > 0xFFFF for reg in regs):
                raise ValueError(f"field {field.value} produced out-of-range registers: {regs}")
            if register.size == 0:
                # A virtual field validated its value but has no registers to
                # send.
                continue
            encoded[field] = regs

        # Adjacent registers share one transaction; a block that another block
        # depends on is written first.
        for start, regs in layout.write_blocks(encoded):
            await state.client.write_multiple_registers(start, list(regs))

    def _identity(self, v_in: float) -> str:
        state = self.require_state()
        return (
            f"model={state.model} type={state.id} sn={state.sn:08X} fw={state.fw:.2f} "
            f"input={v_in:.2f}V"
        )

    async def identity(self) -> str:
        values = await self.read(Field.V_IN)
        return self._identity(values[Field.V_IN])

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

    async def status(self) -> str:
        values = await self.read(
            Field.V_IN,
            Field.V_SET,
            Field.I_SET,
            Field.V,
            Field.I,
            Field.P,
            Field.EN,
            Field.MODE,
            Field.PROTECTION,
            Field.TEMP_C,
        )
        return "\n".join(
            [
                self._identity(values[Field.V_IN]),
                f"set:      {values[Field.V_SET]:.3f} V, {values[Field.I_SET]:.3f} A",
                f"output:   {values[Field.V]:.3f} V, {values[Field.I]:.3f} A, {values[Field.P]:.3f} W",
                f"enabled:  {values[Field.EN]}",
                f"mode:     {values[Field.MODE]}",
                f"protection={values[Field.PROTECTION]}, temp={values[Field.TEMP_C]} C",
            ]
        )
