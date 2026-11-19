"""Shared fakes for the Riden test suite.

A small in-memory tmodbus client replaces the network transport, so tests
never touch a device or a socket.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any

from riden.field import parse_field
from riden.layout import Layout
from riden.register import Register, Registers, RegRead, RegWrite

# Register map of a fake RD6006P device, in raw register values.
BASE_REGISTERS = 128


def make_registers() -> list[int]:
    """Return a register file with a valid RD6006P identity and readings."""
    regs = [0] * BASE_REGISTERS
    regs[0] = 60065          # ID: RD6006P
    regs[1] = 0              # SN high word
    regs[2] = 7              # SN low word
    regs[3] = 1234           # FW = 12.34
    regs[8] = 12500          # V_SET = 12.5 V
    regs[9] = 10000          # I_SET = 1.0 A
    regs[10] = 12000         # V = 12.0 V
    regs[11] = 5000          # I = 0.5 A
    regs[12] = 0             # P high word
    regs[13] = 60000         # P = 60.0 W (RD6006P: / 1000)
    regs[14] = 2400          # V_IN = 24.0 V
    regs[18] = 1             # EN = True
    return regs


class Op(Enum):
    READ = auto()
    WRITE = auto()


@dataclass(frozen=True, slots=True)
class Tx:
    """One recorded transaction, for assertions."""

    op: Op
    start: int
    count: int = 0
    data: Registers = ()

    @classmethod
    def read(cls, start: int, count: int) -> Tx:
        return cls(Op.READ, start, count)

    @classmethod
    def write(cls, start: int, data: Registers | list[int]) -> Tx:
        values = tuple(data)
        return cls(Op.WRITE, start, len(values), values)


class FakeClient:
    """In-memory stand-in for tmodbus's AsyncModbusClient."""

    def __init__(self, registers: list[int] | None = None) -> None:
        self.registers = make_registers() if registers is None else list(registers)
        self.transactions: list[Tx] = []
        self.connected = False
        self.closed = False
        self.connect_error: BaseException | None = None
        self.fail_with: BaseException | None = None

    async def connect(self) -> None:
        if self.connect_error is not None:
            raise self.connect_error
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False
        self.closed = True

    async def read_holding_registers(
        self, start_address: int, quantity: int
    ) -> list[int]:
        if self.fail_with is not None:
            raise self.fail_with
        self.transactions.append(Tx.read(start_address, quantity))
        return self.registers[start_address:start_address + quantity]

    async def write_multiple_registers(
        self, start_address: int, values: list[int]
    ) -> int:
        if self.fail_with is not None:
            raise self.fail_with
        self.transactions.append(Tx.write(start_address, values))
        self.registers[start_address:start_address + len(values)] = values
        return len(values)


def any_value(value: object) -> Any:
    """Escape hatch for intentionally invalid runtime values in tests."""
    return value


def reader(layout: Mapping[Any, Register] | Layout, field: str) -> RegRead:
    """Return a field's read codec, failing the test if it has none."""
    if isinstance(layout, Layout):
        located = layout.find(parse_field(field))
        assert located is not None
        register = located.reg
    else:
        register = layout[field]
    read = register.read
    assert read is not None
    return read


def writer(layout: Mapping[Any, Register] | Layout, field: str) -> RegWrite:
    """Return a field's write codec, failing the test if it has none."""
    if isinstance(layout, Layout):
        located = layout.find(parse_field(field))
        assert located is not None
        register = located.reg
    else:
        register = layout[field]
    write = register.write
    assert write is not None
    return write
