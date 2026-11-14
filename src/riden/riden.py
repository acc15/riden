import contextlib
import logging
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Self, override

import serial

from .field import Field, RegRead, RegWrite, flatten_fields
from .model import Model
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
        """Identity of the connected device, read once by open()."""

        session: Session
        id: int
        sn: int
        fw: float
        model: Model

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
            self.state = Riden.State(
                session=session,
                id=values[0],
                sn=values[1] << 16 | values[2],
                fw=values[3] / 100.0,
                model=Model.find(values[0]),
            )
        except BaseException:
            # The transport owns the session; close exactly what open() returned.
            # BaseException also covers Ctrl-C, since __exit__ is not called
            # when __enter__ raises.
            with contextlib.suppress(Exception):
                session.close()
            raise
        return self

    def read(self, *fields: str | Field | Iterable[str | Field]) -> dict[Field, Any]:

        state = self.require_state()

        # dict.fromkeys() flattens, normalizes and deduplicates in one pass,
        # while preserving the requested order.
        selected: dict[Field, Any] = dict.fromkeys(flatten_fields(fields))
        if not selected:
            return {}

        # Validate and collect readers in one pass.  This both reports all
        # unreadable fields before any I/O and narrows away the optional
        # `None` in Field.read for the type checker.
        readers: dict[Field, RegRead] = {}
        not_readable: list[str] = []
        for field in selected:
            if field.read is None:
                not_readable.append(field.label)
            else:
                readers[field] = field.read

        if not_readable:
            raise ValueError(f"fields are not readable: {', '.join(not_readable)}")

        start = min(field.addr for field in selected)
        end = max(field.addr + field.count for field in selected)
        
        regs = state.session.execute(Tx.read(start, end - start))
        for field, reader in readers.items():
            offset = field.addr - start
            raw = regs[offset:offset + field.count]
            selected[field] = reader(raw, state.model.value)
        return selected

    def write(self, *values: dict[str | Field, Any], **fields: Any) -> None:
        
        state = self.require_state()

        updates: dict[Field, Any] = {}
        for mapping in values:
            for field, value in mapping.items():
                updates[Field(field)] = value
        for field, value in fields.items():
            updates[Field(field)] = value

        if not updates:
            return

        # Validate and collect writers in one pass, exactly like read().
        # All unwritable fields are reported before any encoding or I/O.
        writers: dict[Field, RegWrite] = {}
        not_writable: list[str] = []
        for field in updates:
            if field.write is None:
                not_writable.append(field.label)
            else:
                writers[field] = field.write

        if not_writable:
            raise ValueError(f"fields are not writable: {', '.join(not_writable)}")

        # Encode and validate everything before touching the bus, so an invalid
        # value does not leave the device partially updated.
        encoded: dict[Field, Registers] = {}
        for field, value in updates.items():
            try:
                regs = writers[field](value, state.model.value)
            except ValueError as exc:
                raise ValueError(f"field {field.label}: {exc}") from exc
            if len(regs) != field.count:
                raise ValueError(f"field {field.label} produced {len(regs)} registers, expected {field.count}")
            if any(reg < 0 or reg > 0xFFFF for reg in regs):
                raise ValueError(f"field {field.label} produced out-of-range registers: {regs}")
            encoded[field] = regs

        # Merge fields into contiguous blocks; Modbus cannot write sparse
        # register lists in one transaction.  Blocks stay mutable while
        # merging and are converted to tuples only when sent to the session.
        blocks: list[tuple[int, list[int]]] = []
        for field, regs in sorted(encoded.items(), key=lambda item: item[0].addr):
            if blocks:
                block_start, block_regs = blocks[-1]
                offset = field.addr - block_start
                if offset <= len(block_regs):
                    block_regs[offset:offset + len(regs)] = regs
                    continue
            blocks.append((field.addr, list(regs)))

        for start, regs in blocks:
            state.session.execute(Tx.write(start, tuple(regs)))

    def _identity(self, v_in: float) -> str:
        state = self.require_state()
        return (
            f"model={state.model} type={state.id} sn={state.sn:08X} fw={state.fw:.2f} "
            f"input={v_in:.2f}V vscale={state.model.value.v_scale} iscale={state.model.value.i_scale}"
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
