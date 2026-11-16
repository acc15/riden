"""One field in a model's register map."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from .field import Field
from .transport import Registers

type RegRead = Callable[[Registers, Mapping[Field, Any]], Any]
type RegWrite = Callable[[Any, Mapping[Field, Any]], Registers]


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

    ``deps`` maps the name a codec sees to the field the value is read from:
    ``{Field.I_RANGE: Field.M1_I_RANGE}`` lets one current codec serve the
    output and every preset by asking for ``deps[Field.I_RANGE]``.  Keys are
    codec-side aliases, values are the real fields that must be decoded first.
    The base map has no dependencies; the RD6012P map uses them for current
    ranges.
    """

    addr: int
    size: int
    read: RegRead | None = None
    write: RegWrite | None = None
    deps: Mapping[Field, Field] = MappingProxyType({})

    @property
    def is_readable(self) -> bool:
        return self.read is not None

    @property
    def is_writable(self) -> bool:
        return self.write is not None

    @property
    def dependencies(self) -> frozenset[Field]:
        """Real fields that must be decoded before this one."""
        return frozenset(self.deps.values())

    def make_deps(self, values: Mapping[str, Any]) -> dict[Field, Any]:
        """Return the dependency mapping a codec is allowed to see.

        ``values`` is keyed by field name; only fields declared in ``deps``
        are copied, so a codec can never depend on values it did not declare,
        and each one is aliased to the key the codec asks for.  Dependencies
        are decoded first, so every one of them is already in ``values``.
        """
        return {name: values[field.value] for name, field in self.deps.items()}
