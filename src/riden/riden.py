import contextlib
import logging
from collections.abc import Callable, Iterable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Self, override

import serial

from .field import Field, flatten_fields, merge_fields
from .layout import Layout
from .model import Model
from .register import RegRead, RegWrite
from .transport import (
    Delayed,
    KeepAlive,
    Logging,
    Modbus,
    Reconnectable,
    Registers,
    Transport,
)
from .transport.errors import is_link_error as default_is_link_error
from .transport.modbus import DEFAULT_BAUDRATE, DEFAULT_TIMEOUT
from .transport.transport import Session, Tx

log = logging.getLogger("riden")


class Riden(AbstractContextManager["Riden"]):
    """Riden power supply client.

    The client knows only the device register map.  Its transport argument is
    a Transport: open() creates a Modbus client and close() closes that exact
    session.  Construction does no I/O; open() creates the transport session
    and reads the identity.

    The common case is a single call:

        with Riden.connect("bt://...", 1) as rd:
            ...

    A custom stack can be passed explicitly:

        with Riden(Reconnectable(Delayed(Modbus("/dev/ttyUSB0")))) as rd:
            ...
    """

    @dataclass(frozen=True, slots=True)
    class State:
        """Identity of the connected device and its register map.

        ``layout`` is built once by open() from the model's layout and is
        read-only: a connected client uses exactly one map.
        """

        session: Session
        id: int
        sn: int
        fw: float
        model: Model
        layout: Layout

    def __init__(self, transport: Transport):
        self.transport = transport
        self.state: Riden.State | None = None

    def require_state(self) -> Riden.State:
        state = self.state
        if state is None:
            raise RuntimeError("Riden is not initialized")
        return state

    @classmethod
    def connect(
        cls,
        port: serial.SerialBase | str,
        address: int = 1,
        *,
        baudrate: int = DEFAULT_BAUDRATE,
        timeout: float | None = DEFAULT_TIMEOUT,
        write_timeout: float | None = None,
        delay: float = 0.02,
        keepalive: float | None = None,
        retry_attempts: int = 1,
        retry_delay: float = 0.2,
        is_link_error: Callable[[BaseException], bool] = default_is_link_error,
        logger: logging.Logger | None = log,
        log_level: int = logging.DEBUG,
    ) -> Self:
        """Return a client on the default transport stack.

        The stack is Modbus -> Logging -> Delayed -> KeepAlive -> Reconnectable.
        Construction does no I/O; the returned client is opened by ``with``
        or open().

        ``baudrate``, ``timeout`` and ``write_timeout`` configure a port given
        as a string (path or URL); a port object keeps its own settings.  A
        port object is managed by the client: closing the client closes it,
        and a reconnect reopens it, even if it was passed in open.  See
        :class:`riden.transport.Modbus`.

        ``delay`` is the pause between transactions (``0`` leaves Delayed out).

        ``keepalive=None`` (the default) disables idle pings and the
        background thread they need.  A failed ping stops the pings for that
        session; the next operation that proves the link works registers it
        again.  KeepAlive never heals anything: only a real operation
        reconnects, because Reconnectable is outermost.

        ``retry_attempts`` reconnects (``0`` leaves Reconnectable out), with
        ``retry_delay`` seconds between them.  ``is_link_error`` is shared:
        Reconnectable retries these errors, and KeepAlive does not stop
        pinging on any other (logical) error.

        Logging sits directly above Modbus, so it also sees keepalive pings
        and reconnects.  ``logger`` defaults to the ``riden`` logger; ``None``
        leaves logging out of the stack.

        Usage::

            with Riden.connect("bt://AA:BB:CC:DD:EE:FF?channel=1", 1) as rd:
                print(rd.status())
        """
        transport: Transport = Modbus(
            port,
            address,
            baudrate=baudrate,
            timeout=timeout,
            write_timeout=write_timeout,
        )
        if logger is not None:
            transport = Logging(transport, logger, log_level)
        if delay > 0:
            transport = Delayed(transport, delay)
        if keepalive is not None:
            transport = KeepAlive(transport, keepalive, is_link_error)
        if retry_attempts > 0:
            transport = Reconnectable(transport, retry_attempts, retry_delay, is_link_error)
        return cls(transport)

    def open(self) -> Self:
        if self.state is not None:
            return self

        session = self.transport.open()
        try:
            # Identification is I/O, so it belongs to open(), not __init__.
            values = session.execute(Tx.read(0, 4))
            model = Model.find(values[0])
            self.state = Riden.State(
                session=session,
                id=values[0],
                sn=values[1] << 16 | values[2],
                fw=values[3] / 100.0,
                model=model,
                layout=model.value.layout(),
            )
        except BaseException:
            # The transport owns the session; close exactly what open() returned.
            # BaseException also covers Ctrl-C, since __exit__ is not called
            # when __enter__ raises.
            with contextlib.suppress(Exception):
                session.close()
            raise
        return self

    def read(self, *fields: str | Iterable[str]) -> dict[str, Any]:
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
            regs = state.session.execute(Tx.read(start, count))

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

    def write(
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
        dependencies = self.read(*missing) if missing else {}

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
            state.session.execute(Tx.write(start, regs))

    def _identity(self, v_in: float) -> str:
        state = self.require_state()
        return (
            f"model={state.model} type={state.id} sn={state.sn:08X} fw={state.fw:.2f} "
            f"input={v_in:.2f}V"
        )

    def identity(self) -> str:
        return self._identity(self.read(Field.V_IN)[Field.V_IN])

    def close(self) -> None:
        if self.state is not None:
            self.state.session.close()
            self.state = None

    @override
    def __enter__(self) -> Self:
        self.open()
        return self

    @override
    def __exit__(self, *_):
        self.close()

    def status(self) -> str:
        values = self.read(
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
