import re
from collections.abc import Iterable, Mapping
from enum import StrEnum, auto
from typing import Any, Self, override

from .preset import PresetField, PresetParam


class Field(StrEnum):
    """Names of global fields exposed by Riden devices.

    The enum only names fields.  Which register a field uses, how many
    registers it occupies and how it is encoded belongs to the model's
    :class:`riden.spec.Spec`.  Preset fields are represented by
    :class:`riden.preset.PresetField`, which adds the preset number.
    """

    ID = auto()
    SN = auto()
    FW = auto()
    TEMP_C = auto()
    TEMP_F = auto()
    V_SET = auto()
    I_SET = auto()
    V = auto()
    I = auto()
    P = auto()
    V_IN = auto()
    LOCK = auto()
    PROTECTION = auto()
    MODE = auto()
    EN = auto()
    PRESET = auto()
    I_RANGE = auto()

    V_MAX = auto()
    V_SCALE = auto()
    V_TOLERANCE = auto()
    OVP_TOLERANCE = auto()
    I_MAX = auto()
    I_SCALE = auto()
    I_TOLERANCE = auto()
    OCP_TOLERANCE = auto()
    P_MAX = auto()
    P_SCALE = auto()

    BAT_EN = auto()
    BAT_V = auto()
    EXT_TEMP_C = auto()
    EXT_TEMP_F = auto()
    AH = auto()
    WH = auto()

    YEAR = auto()
    MONTH = auto()
    DAY = auto()
    HOUR = auto()
    MINUTE = auto()
    SECOND = auto()

    CAL_COMMIT = auto()
    CAL_V_ZERO = auto()
    CAL_V_SCALE = auto()
    CAL_BV_ZERO = auto()
    CAL_BV_SCALE = auto()
    CAL_I_ZERO = auto()
    CAL_I_SCALE = auto()
    CAL_BI_ZERO = auto()
    CAL_BI_SCALE = auto()
    CAL_I12_ZERO = auto()
    CAL_I12_SCALE = auto()

    TAKE_OK = auto()
    TAKE_OUT = auto()
    BOOT_EN = auto()
    VOLUME = auto()
    LOGO = auto()
    LANG = auto()
    BACKLIGHT = auto()

    @override
    @classmethod
    def _missing_(cls, value: object) -> Field | None:
        if isinstance(value, str):
            return cls.__members__.get(value.upper())
        return None


_PRESET_RE = re.compile(
    r"m(\d+)_(i_range|i_max|i_scale|ovp|ocp|v|i)",
    re.IGNORECASE,
)

class FieldRef:
    """A reference to a global field or to a concrete preset field.

    This is the normalized key used internally by the client and the layout.
    It accepts the public field forms: a name, a :class:`Field` member or a
    :class:`riden.preset.PresetField`.
    """

    __slots__ = ("target",)

    target: Field | PresetField

    def __new__(cls, value: FieldLike) -> Self:
        if isinstance(value, cls):
            return value
        return super().__new__(cls)

    def __init__(self, value: FieldLike):
        if isinstance(value, FieldRef):
            target = value.target
        elif isinstance(value, PresetParam):
            raise TypeError("PresetParam must be indexed: use PresetField")
        elif isinstance(value, (PresetField, Field)):
            target = value
        elif isinstance(value, str):
            target = (
                PresetField(int(match[1]), match[2])
                if (match := _PRESET_RE.fullmatch(value))
                else Field(value)
            )
        else:
            raise TypeError(f"not a field: {value!r}")
        object.__setattr__(self, "target", target)

    @override
    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("FieldRef is immutable")

    @property
    def value(self) -> str:
        return str(self.target)

    @override
    def __hash__(self) -> int:
        return hash(self.target)

    @override
    def __eq__(self, other: object) -> bool:
        if isinstance(other, FieldRef):
            return self.target == other.target
        if isinstance(other, str):
            return self.target == other
        return NotImplemented

    @override
    def __str__(self) -> str:
        return self.value

    @override
    def __repr__(self) -> str:
        return f"FieldRef({self.target!r})"


type FieldLike = str | Field | PresetField | FieldRef
"""A field as accepted by the public API: a name or a typed field object."""


type FieldMapping = (
    Mapping[str, Any]
    | Mapping[Field, Any]
    | Mapping[PresetField, Any]
    | Mapping[Field | PresetField, Any]
    | Mapping[FieldRef, Any]
)
"""Field names or field objects mapped to their values.

Keys are normalized through :class:`FieldRef`.  The union is explicit
because ``Mapping`` is invariant in its key type: a ``dict[Field, Any]`` is
not assignable to ``Mapping[str, Any]``.
"""


def flatten_fields(
    fields: Iterable[FieldLike | Iterable[FieldLike]],
) -> Iterable[FieldRef]:
    for field in fields:
        if isinstance(field, PresetParam):
            raise TypeError("PresetParam must be indexed: use PresetField")
        if isinstance(field, FieldRef):
            yield field
        elif isinstance(field, str):
            yield FieldRef(field)
        else:
            yield from flatten_fields(field)


def merge_fields(
    *mappings: FieldMapping,
) -> dict[FieldRef, Any]:
    """Merge field mappings into one, normalizing keys to :class:`FieldRef`.

    Later mappings override earlier ones.  ``Riden.write`` relies on that
    order: the values it is called with, then its keyword arguments.
    """
    merged: dict[FieldRef, Any] = {}
    for mapping in mappings:
        for field, value in mapping.items():
            merged[FieldRef(field)] = value
    return merged
