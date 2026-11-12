"""Shared fakes for the Riden test suite.

The real transport stack talks to a serial port and a minimalmodbus
Instrument.  Both are replaced here by small in-memory objects, so the tests
never touch a device or a socket.
"""

from collections.abc import Iterator
from typing import Any, ClassVar, cast

import pytest

from riden.transport import keepalive
from riden.transport.modbus import Port
from riden.transport.transport import Op, Tx

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
    regs[13] = 6000          # P = 60.0 W
    regs[14] = 2400          # V_IN = 24.0 V
    regs[18] = 1             # EN = True
    return regs


class FakePort:
    """pyserial-like port that records open/close calls."""

    def __init__(self) -> None:
        self.port: str | None = "fake"
        self.is_open = False
        self.opens = 0
        self.closes = 0
        self.open_error: BaseException | None = None

    def open(self) -> None:
        if self.open_error is not None:
            raise self.open_error
        self.opens += 1
        self.is_open = True

    def close(self) -> None:
        self.closes += 1
        self.is_open = False


def as_port(port: FakePort) -> Port:
    """Type-only bridge: the transport accepts anything pyserial-like."""
    return cast(Port, port)


class FakeInstrument:
    """Register file standing in for minimalmodbus.Instrument."""

    instances: ClassVar[list[FakeInstrument]] = []

    def __init__(
        self,
        port: object,
        slaveaddress: int,
        mode: str | None = None,
        close_port_after_each_call: bool = False,
        debug: bool = False,
    ) -> None:
        self.port = port
        self.address = slaveaddress
        self.mode = mode
        self.debug = debug
        self.clear_buffers_before_each_transaction = False
        self.registers = make_registers()
        self.transactions: list[Tx] = []
        FakeInstrument.instances.append(self)

    def read_registers(
        self, registeraddress: int, number_of_registers: int, functioncode: int = 3
    ) -> list[int]:
        self.transactions.append(Tx.read(registeraddress, number_of_registers))
        return self.registers[
            registeraddress:registeraddress + number_of_registers
        ]

    def write_registers(self, registeraddress: int, values: list[int]) -> None:
        self.transactions.append(Tx.write(registeraddress, values))
        self.registers[
            registeraddress:registeraddress + len(values)
        ] = values


@pytest.fixture
def fake_instrument(monkeypatch: pytest.MonkeyPatch) -> type[FakeInstrument]:
    """Replace minimalmodbus.Instrument with the in-memory fake."""
    FakeInstrument.instances = []
    monkeypatch.setattr("minimalmodbus.Instrument", FakeInstrument)
    return FakeInstrument


@pytest.fixture(autouse=True)
def no_keepalive_thread(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Keep the global keepalive scheduler synchronous and empty."""
    keepalive._scheduler._deadlines.clear()
    monkeypatch.setattr(
        keepalive._scheduler, "_ensure_thread_locked", lambda: None
    )
    yield
    keepalive._scheduler._deadlines.clear()


class MemorySession:
    """Session backed by a register list, for testing Riden itself."""

    def __init__(self, registers: list[int] | None = None) -> None:
        self.registers = make_registers() if registers is None else list(registers)
        self.transactions: list[Tx] = []
        self.closed = False
        self.fail_with: BaseException | None = None

    def execute(self, tx: Tx) -> tuple[int, ...]:
        if self.fail_with is not None:
            raise self.fail_with
        self.transactions.append(tx)
        if tx.op is Op.READ:
            return tuple(self.registers[tx.start:tx.start + tx.count])
        self.registers[tx.start:tx.start + len(tx.data)] = tx.data
        return ()

    def close(self) -> None:
        self.closed = True


class MemoryTransport:
    """Transport that hands out one MemorySession."""

    def __init__(self, session: MemorySession | None = None) -> None:
        self.session = MemorySession() if session is None else session
        self.opens = 0

    def open(self) -> MemorySession:
        self.opens += 1
        return self.session


class RecordingSession:
    """Session that records transactions and returns canned data."""

    def __init__(self, result: tuple[int, ...] | None = None) -> None:
        self.result = () if result is None else result
        self.transactions: list[Tx] = []
        self.closed = False
        self.fail_with: BaseException | None = None

    def execute(self, tx: Tx) -> tuple[int, ...]:
        self.transactions.append(tx)
        if self.fail_with is not None:
            raise self.fail_with
        return self.result

    def close(self) -> None:
        self.closed = True


class RecordingTransport:
    """Transport that hands out one RecordingSession."""

    def __init__(self, session: RecordingSession | None = None) -> None:
        self.session = RecordingSession() if session is None else session
        self.opens = 0

    def open(self) -> RecordingSession:
        self.opens += 1
        return self.session


def any_value(value: object) -> Any:
    """Escape hatch for intentionally invalid runtime values in tests."""
    return value
