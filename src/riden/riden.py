import contextlib
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from typing import Any, Self, cast, override

from .field import Field, flatten_fields
from .model import Model
from .transport import Transport, build_transport
from .transport.errors import is_link_error as default_is_link_error
from .transport.modbus import Port
from .transport.transport import Session, Tx


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

    def __init__(self, transport: Transport):
        self.transport = transport
        self.session: Session | None = None
        self.id: int | None = None
        self.sn: int | None = None
        self.fw: float | None = None
        self.model: Model | None = None

    @classmethod
    def connect(
        cls,
        port: Port,
        address: int = 1,
        *,
        delay: float = 0.02,
        keepalive: float | None = 5.0,
        retry_attempts: int = 1,
        retry_delay: float = 0.2,
        is_link_error: Callable[[BaseException], bool] = default_is_link_error,
    ) -> Self:
        """Return a client using the default transport stack.

        The stack is Modbus -> Delayed -> KeepAlive -> Reconnectable.  Keyword
        options (``delay``, ``keepalive``, ``retry_attempts``, ``retry_delay``,
        ``is_link_error``) are documented in
        :func:`riden.transport.build_transport`; ``keepalive=None`` disables
        the idle pings.  A failed ping stops the pings for that session; the
        next operation that proves the link works registers it again.

        Usage::

            with Riden.connect("bt://AA:BB:CC:DD:EE:FF?channel=1", 1) as rd:
                print(rd.status())
        """
        return cls(
            build_transport(
                port,
                address,
                delay=delay,
                keepalive=keepalive,
                retry_attempts=retry_attempts,
                retry_delay=retry_delay,
                is_link_error=is_link_error,
            )
        )

    def _require_open(self) -> Session:
        session = self.session
        if session is None:
            raise RuntimeError("Riden is not open")
        return session

    def open(self) -> Self:
        if self.session is not None:
            return self

        self.session = self.transport.open()
        try:
            # Identification is I/O, so it belongs to open(), not __init__.
            identity = self.read(Field.ID, Field.SN, Field.FW)
            self.id = cast(int, identity[Field.ID])
            self.sn = cast(int, identity[Field.SN])
            self.fw = cast(float, identity[Field.FW])
            self.model = Model.find(self.id)
        except BaseException:
            # The transport owns the session; close exactly what open() returned.
            # BaseException also covers Ctrl-C, since __exit__ is not called
            # when __enter__ raises.
            with contextlib.suppress(Exception):
                self.session.close()
            self.session = None
            raise
        return self

    def read(
        self, *fields: str | Field | Sequence[str | Field]
    ) -> dict[Field, Any]:
        # dict.fromkeys() flattens, normalizes and deduplicates in one pass,
        # while preserving the requested order.
        selected: dict[Field, Any] = dict.fromkeys(flatten_fields(fields))
        if not selected:
            return {}

        not_readable = [field.label for field in selected if not field.is_readable]
        if not_readable:
            raise ValueError(f"fields are not readable: {', '.join(not_readable)}")

        start = min(field.addr for field in selected)
        end = max(field.addr + field.count for field in selected)
        session = self._require_open()
        regs = session.execute(Tx.read(start, end - start))

        # During open() the model is not known yet; the ID/SN/FW readers
        # ignore it, so the cast is safe there.
        model = cast(Model, self.model)
        for field in selected:
            reader = field.read
            if reader is None:
                raise ValueError(f"field is not readable: {field.label}")
            offset = field.addr - start
            raw = regs[offset:offset + field.count]
            selected[field] = reader(raw, model)
        return selected

    def write(self, *values: dict[str | Field, Any], **fields: Any) -> None:
        updates: dict[Field, Any] = {}
        for mapping in values:
            for field, value in mapping.items():
                updates[Field(field)] = value
        for field, value in fields.items():
            updates[Field(field)] = value

        if not updates:
            return

        # Encode and validate everything before touching the bus, so an invalid
        # value does not leave the device partially updated.
        session = self._require_open()
        model = cast(Model, self.model)
        encoded: dict[Field, list[int]] = {}
        for field, value in updates.items():
            writer = field.write
            if writer is None:
                raise ValueError(f"field is not writable: {field.label}")

            regs = writer(value, model)
            if len(regs) != field.count:
                raise ValueError(
                    f"field {field.label} produced {len(regs)} registers, "
                    f"expected {field.count}"
                )
            if any(not 0 <= reg <= 0xFFFF for reg in regs):
                raise ValueError(
                    f"field {field.label} produced out-of-range registers: {regs}"
                )
            encoded[field] = regs

        # Merge fields into contiguous blocks; Modbus cannot write sparse
        # register lists in one transaction.
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
            session.execute(Tx.write(start, regs))

    def _identity(self, v_in: float) -> str:
        model, sn, fw = self.model, self.sn, self.fw
        if model is None or sn is None or fw is None:
            raise RuntimeError("Riden is not initialized")
        return (
            f"model={model} type={self.id} sn={sn:08X} fw={fw:.2f} "
            f"input={v_in:.2f}V vscale={model.v_scale} iscale={model.i_scale}"
        )

    def identity(self) -> str:
        return self._identity(self.read(Field.V_IN)[Field.V_IN])

    def close(self) -> None:
        # The client decides when to call this; close exactly the session
        # returned by transport.open().
        session = self.session
        self.session = None
        if session is not None:
            session.close()

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
