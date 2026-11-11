"""Protocol shared by the device client and the transport layer.

``Transport`` deliberately differs from ``retry.OpenClose``:

* ``OpenClose`` is for an object that manages its own lifetime (``Riden``);
  ``RetryOpen`` calls ``obj.open()`` and returns ``obj`` itself.
* ``Transport`` creates a separate resource, and ``Session`` closes exactly
  that resource.  The caller owns the produced object.

A transport stores the configuration needed to create sessions, and ``open()``
returns the session.  Composed transports return a wrapper session around the
inner one; the base ``Modbus`` transport is its own session because there is
exactly one port, so ``open()`` returns self.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum, auto
from typing import Protocol, Self


class Op(Enum):
    READ = auto()
    WRITE = auto()


@dataclass(frozen=True, slots=True)
class Tx:
    """One Modbus register transaction."""

    op: Op
    start: int
    count: int
    data: tuple[int, ...]

    @classmethod
    def read(cls, start: int, count: int) -> Self:
        return cls(Op.READ, start, count, ())

    @classmethod
    def write(cls, start: int, data: Sequence[int]) -> Self:
        values = tuple(data)
        return cls(Op.WRITE, start, len(values), values)


class Session(Protocol):
    """An open connection that executes one register transaction at a time."""

    def execute(self, tx: Tx) -> tuple[int, ...]: ...

    def close(self) -> None: ...


class Transport(Protocol):
    """Create a session; the session is responsible for closing itself."""

    def open(self) -> Session: ...
