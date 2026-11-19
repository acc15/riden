import re
from collections.abc import Iterable, Mapping
from enum import Enum, StrEnum, auto
from typing import Any, override


class Field(StrEnum):
    """Names of global fields exposed by Riden devices.

    The enum only names fields.  Which register a field uses, how many
    registers it occupies and how it is encoded belongs to the model's
    :class:`riden.spec.Spec`.  Preset fields are represented by
    :class:`riden.field.PresetField`, which adds the preset number.
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


class PresetParam(Enum):
    """One parameter of a preset.

    ``PresetField`` combines a parameter with a preset number; this enum only
    names the parameter itself.
    """

    @override
    @staticmethod
    def _generate_next_value_(name: str, start: int, count: int, last_values: list[str]):
        return name.lower()

    V = auto()
    I = auto()
    OVP = auto()
    OCP = auto()
    I_RANGE = auto()
    I_MAX = auto()
    I_SCALE = auto()

    @override
    @classmethod
    def _missing_(cls, value: object) -> PresetParam | None:
        if isinstance(value, str):
            return cls.__members__.get(value.upper())
        return None


class PresetField(str):
    """A concrete field of one preset: a preset number and a parameter.

    It is a ``str`` so it can index the name-keyed result of
    :meth:`riden.riden.Riden.read` directly::

        field = PresetField(1, PresetParam.V)
        value = (await rd.read(field))[field]
    """

    __slots__ = ("num", "param")

    num: int
    param: PresetParam

    def __new__(cls, num: int, param: PresetParam | str):
        param = PresetParam(param)
        if num < 0:
            raise ValueError(f"preset number must be non-negative: {num}")
        self = super().__new__(cls, f"m{num}_{param.value}")
        object.__setattr__(self, "num", num)
        object.__setattr__(self, "param", param)
        return self

    @override
    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("PresetField is immutable")

    @property
    def value(self) -> str:
        return str(self)

    @override
    def __repr__(self) -> str:
        return f"PresetField({self.num}, {self.param!r})"


_PRESET_RE = re.compile(
    r"m(\d+)_(i_range|i_max|i_scale|ovp|ocp|v|i)",
    re.IGNORECASE,
)

type FieldRef = Field | PresetField
"""A normalized reference: a global field or a concrete preset field."""

type FieldLike = str | FieldRef
"""A field as accepted by the public API: a name or a typed field object."""


def ref(value: FieldLike) -> FieldRef:
    """Normalize a field name or field object to a :class:`FieldRef`."""
    if isinstance(value, (PresetField, Field)):
        return value
    if isinstance(value, str):
        if match := _PRESET_RE.fullmatch(value):
            return PresetField(int(match[1]), match[2])
        return Field(value)
    raise TypeError(f"not a field: {value!r}")


type FieldMapping = (
    Mapping[str, Any]
    | Mapping[Field, Any]
    | Mapping[PresetField, Any]
    | Mapping[FieldRef, Any]
)
"""Field names or field objects mapped to their values.

The union is explicit because ``Mapping`` is invariant in its key type: a
``dict[Field, Any]`` is not assignable to ``Mapping[str, Any]``.
"""


def flatten_fields(
    fields: Iterable[FieldLike | Iterable[FieldLike]],
) -> Iterable[FieldRef]:
    for field in fields:
        if isinstance(field, str):
            yield ref(field)
        elif isinstance(field, Iterable):
            yield from flatten_fields(field)
        else:
            raise TypeError(f"not a field: {field!r}")


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
            merged[ref(field)] = value
    return merged
