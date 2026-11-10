import contextlib
from collections.abc import Sequence
from contextlib import AbstractContextManager
from typing import Any, Self

import minimalmodbus

from .field import Field, flatten_fields
from .model import Model
from .transport import Transport


class Riden(AbstractContextManager):
    """Riden power supply client.

    The client knows only the device register map.  Its transport argument is
    a Transport: open() creates a Modbus client and close() closes that exact
    session.  Construction does no I/O; open() creates the transport session
    and reads the identity.
    Intended use:

        with Riden(DelayedTransport(ModbusTransport("bt://..."))) as rd:
            ...
    """

    def __init__(self, transport: Transport[minimalmodbus.Instrument]):
        self.transport = transport
        self.inst: minimalmodbus.Instrument | None = None
        self.id = None
        self.sn = None
        self.fw = None
        self.model = None

    def open(self):
        if self.inst is not None:
            return self

        self.inst = self.transport.open()
        try:
            # Identification is I/O, so it belongs to open(), not __init__.
            self.id, self.sn, self.fw = self.read(
                Field.ID, Field.SN, Field.FW
            ).values()
            self.model = Model.find(self.id)
        except BaseException:
            # The transport owns the session; close exactly what open() returned.
            # BaseException also covers Ctrl-C, since __exit__ is not called
            # when __enter__ raises.
            with contextlib.suppress(Exception):
                self.transport.close(self.inst)
            self.inst = None
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

        not_readable = [field.value for field in selected if not field.is_readable]
        if not_readable:
            raise ValueError(f"fields are not readable: {', '.join(not_readable)}")

        start = min(field.addr for field in selected)
        end = max(field.addr + field.count for field in selected)
        regs = self.inst.read_registers(start, end - start)

        for field in selected:
            offset = field.addr - start
            raw = regs[offset] if field.count == 1 else regs[offset:offset + field.count]
            selected[field] = field.read(raw, self.model)
        return selected

    def write(self, *values: dict[str | Field, Any], **fields: Any) -> None:
        updates: dict[Field, Any] = {}
        for mapping in values:
            if not isinstance(mapping, dict):
                raise TypeError(f"expected dict, got {type(mapping).__name__}")
            for field, value in mapping.items():
                updates[Field(field)] = value
        for field, value in fields.items():
            updates[Field(field)] = value

        if not updates:
            return

        # Encode and validate everything before touching the bus, so an invalid
        # value does not leave the device partially updated.
        encoded: dict[Field, list[int]] = {}
        for field, value in updates.items():
            if not field.is_writable:
                raise ValueError(f"field is not writable: {field.value}")

            raw = field.write(value, self.model)
            regs = [raw] if isinstance(raw, int) else raw
            if len(regs) != field.count:
                raise ValueError(
                    f"field {field.value} produced {len(regs)} registers, "
                    f"expected {field.count}"
                )
            if any(not 0 <= reg <= 0xFFFF for reg in regs):
                raise ValueError(
                    f"field {field.value} produced out-of-range registers: {regs}"
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
            if len(regs) == 1:
                self.inst.write_register(start, regs[0])
            else:
                self.inst.write_registers(start, regs)

    def _identity(self, v_in: float) -> str:
        return (
            f"model={self.model} type={self.id} sn={self.sn:08X} fw={self.fw:.2f} "
            f"input={v_in:.2f}V vscale={self.model.v_scale} iscale={self.model.i_scale}"
        )

    def identity(self) -> str:
        return self._identity(self.read(Field.V_IN)[Field.V_IN])

    def close(self) -> None:
        # The client decides when to call this; close exactly the session
        # returned by link.open().
        inst = self.inst
        self.inst = None
        if inst is not None:
            self.transport.close(inst)

    def __enter__(self) -> Self:
        self.open()
        return self

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
