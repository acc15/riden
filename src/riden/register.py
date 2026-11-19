"""One field in a model's register map."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from .field import Field, PresetField, PresetParam

type Registers = tuple[int, ...]

type RegRead = Callable[[Registers, Mapping[Field, Any]], Any]
type RegWrite = Callable[[Any, Mapping[Field, Any]], Registers]

type DepTarget = Field | PresetField | PresetParam
"""A dependency target.

``Field`` and ``PresetField`` are absolute; ``PresetParam`` is relative to
the preset whose template declares it.
"""


@dataclass(frozen=True, slots=True)
class Register:
    """One field in a model's register map.

    ``addr`` is the Modbus register address and ``size`` the number of 16-bit
    registers the field occupies.  ``size == 0`` means the field is virtual:
    its codecs run without register data and a write must produce no registers,
    so it never touches the device.  This lets a model expose a field it does
    not physically have.  Its ``addr`` is then unused.  ``read``/``write`` are
    the value codecs; ``None`` means the field is not readable or not writable
    respectively, virtual or not.

    In a layout's direct register map ``addr`` is absolute.  In a
    :class:`riden.layout.PresetLayout` template it is relative to the start of
    one preset.

    ``deps`` maps the name a codec sees to the field the value is read from.
    Keys are codec-side aliases, values are absolute fields or a
    :class:`riden.field.PresetParam` meaning "the same preset's parameter".
    The layout resolves relative targets before calling a codec.
    """

    addr: int
    size: int
    read: RegRead | None = None
    write: RegWrite | None = None
    deps: Mapping[Field, DepTarget] = MappingProxyType({})

    @property
    def is_readable(self) -> bool:
        return self.read is not None

    @property
    def is_writable(self) -> bool:
        return self.write is not None



@dataclass(frozen=True, slots=True)
class LocatedRegister:
    """A register together with its absolute address in one layout."""

    addr: int
    reg: Register
