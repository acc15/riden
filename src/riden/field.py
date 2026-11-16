from collections.abc import Iterable, Mapping
from enum import StrEnum, auto
from typing import Any, override


class Field(StrEnum):
    """Names of fields exposed by Riden devices.

    The enum only names fields.  Which register a field uses, how many
    registers it occupies and how it is encoded belongs to the model's
    :class:`riden.spec.Spec`.
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

    M0_V = auto()
    M0_I = auto()
    M0_OVP = auto()
    M0_OCP = auto()
    M0_I_RANGE = auto()

    M1_V = auto()
    M1_I = auto()
    M1_OVP = auto()
    M1_OCP = auto()
    M1_I_RANGE = auto()

    M2_V = auto()
    M2_I = auto()
    M2_OVP = auto()
    M2_OCP = auto()
    M2_I_RANGE = auto()

    M3_V = auto()
    M3_I = auto()
    M3_OVP = auto()
    M3_OCP = auto()
    M3_I_RANGE = auto()

    M4_V = auto()
    M4_I = auto()
    M4_OVP = auto()
    M4_OCP = auto()
    M4_I_RANGE = auto()

    M5_V = auto()
    M5_I = auto()
    M5_OVP = auto()
    M5_OCP = auto()
    M5_I_RANGE = auto()

    M6_V = auto()
    M6_I = auto()
    M6_OVP = auto()
    M6_OCP = auto()
    M6_I_RANGE = auto()

    M7_V = auto()
    M7_I = auto()
    M7_OVP = auto()
    M7_OCP = auto()
    M7_I_RANGE = auto()

    M8_V = auto()
    M8_I = auto()
    M8_OVP = auto()
    M8_OCP = auto()
    M8_I_RANGE = auto()

    M9_V = auto()
    M9_I = auto()
    M9_OVP = auto()
    M9_OCP = auto()
    M9_I_RANGE = auto()

    @override
    @classmethod
    def _missing_(cls, value: object) -> Field | None:
        if isinstance(value, str):
            return cls.__members__.get(value.upper())
        return None


def flatten_fields(fields: Iterable[str | Iterable[str]]):
    for field in fields:
        match field:
            case Field(): yield field
            case str(): yield Field(field)
            case _: yield from flatten_fields(field)


def merge_fields(
    *mappings: Mapping[str, Any] | Mapping[Field, Any],
) -> dict[Field, Any]:
    """Merge field mappings into one, normalizing keys to :class:`Field`.

    Later mappings override earlier ones.  ``Riden.write`` relies on that
    order: the values it is called with, then its keyword arguments.
    """
    merged: dict[Field, Any] = {}
    for mapping in mappings:
        for field, value in mapping.items():
            merged[Field(field)] = value
    return merged
