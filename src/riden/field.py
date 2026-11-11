
from collections.abc import Callable, Iterator, Sequence
from enum import Enum
from functools import partial
from typing import Any, override

from .enums import Mode, Protection
from .model import Model

type ValueMap = Callable[[list[int], Model], Any] | None
type RegMap = Callable[[Any, Model], list[int]] | None

def compose(*funcs):
    def composed_fn(arg: Any, *others):
        for fn in funcs:
            arg = fn(arg, *others)
        return arg
    return composed_fn

def flag(r: list[int], _: Model):
    return bool(r[0])

def number(r: list[int], _: Model):
    return r[0]

def write_number(v, _: Model) -> list[int]:
    return [int(v)]

def protection(r: list[int], _: Model):
    return Protection(r[0])

def mode(r: list[int], _: Model):
    return Mode(r[0])

def div(d, x, _: Model):
    return x / d

def div_reg(d, r: list[int], _: Model):
    return r[0] / d

def read_dw(r: list[int], _: Model):
    return r[0] << 16 | r[1]

def read_temp(r: list[int], _: Model):
    return (-1 if r[0] else 1) * r[1]

def read_v(r: list[int], m: Model):
    return r[0] / m.v_scale

def write_v(v, m: Model, off = 0) -> list[int]:
    return [m.v_clamp(v, off)]

def read_i(r: list[int], m: Model):
    return r[0] / m.i_scale

def write_i(v, m: Model, off = 0) -> list[int]:
    return [m.i_clamp(v, off)]

class Field(Enum):
    ID = 0, 1, number, None
    SN = 1, 2, read_dw, None
    FW = 3, 1, partial(div_reg, 100), None
    TEMP_C = 4, 2, read_temp, None
    TEMP_F = 6, 2, read_temp, None
    V_SET = 8, 1, read_v, write_v
    I_SET = 9, 1, read_i, write_i
    V = 10, 1, read_v, None
    I = 11, 1, read_i, None
    P = 12, 2, compose(read_dw, partial(div, 100)), None
    V_IN = 14, 1, partial(div_reg, 100), None
    LOCK = 15, 1, flag, write_number
    PROTECTION = 16, 1, protection, None
    MODE = 17, 1, mode, None
    EN = 18, 1, flag, write_number
    PRESET = 19, 1, number, write_number

    BAT_EN = 32, 1, flag, None
    BAT_V = 33, 1, read_v, None
    EXT_TEMP_C = 34, 2, read_temp, None
    EXT_TEMP_F = 36, 2, read_temp, None
    AH = 38, 2, compose(read_dw, partial(div, 1000)), None
    WH = 40, 2, compose(read_dw, partial(div, 1000)), None

    YEAR = 48, 1, number, write_number
    MONTH = 49, 1, number, write_number
    DAY = 50, 1, number, write_number
    HOUR = 51, 1, number, write_number
    MINUTE = 52, 1, number, write_number
    SECOND = 53, 1, number, write_number

    # Calibration values are raw register values; writing CAL_DATE commits
    # the calibration registers to NVRAM (the documented magic value is 5377).
    CAL_DATE = 54, 1, None, write_number
    CAL_V_ZERO = 55, 1, number, write_number
    CAL_V_SCALE = 56, 1, number, write_number
    CAL_BV_ZERO = 57, 1, number, write_number
    CAL_BV_SCALE = 58, 1, number, write_number
    CAL_I_ZERO = 59, 1, number, write_number
    CAL_I_SCALE = 60, 1, number, write_number
    CAL_BI_ZERO = 61, 1, number, write_number
    CAL_BI_SCALE = 62, 1, number, write_number

    TAKE_OK = 66, 1, flag, write_number
    TAKE_OUT = 67, 1, flag, write_number
    BOOT_EN = 68, 1, flag, write_number
    VOLUME = 69, 1, flag, write_number
    LOGO = 70, 1, flag, write_number
    LANG = 71, 1, number, write_number
    BACKLIGHT = 72, 1, number, write_number

    M0_V = 80, 1, read_v, write_v
    M0_A = 81, 1, read_i, write_i
    M0_OVP = 82, 1, read_v, partial(write_v, off=2)
    M0_OCP = 83, 1, read_i, write_i

    M1_V = 84, 1, read_v, write_v
    M1_A = 85, 1, read_i, write_i
    M1_OVP = 86, 1, read_v, partial(write_v, off=2)
    M1_OCP = 87, 1, read_i, write_i

    M2_V = 88, 1, read_v, write_v
    M2_A = 89, 1, read_i, write_i
    M2_OVP = 90, 1, read_v, partial(write_v, off=2)
    M2_OCP = 91, 1, read_i, write_i

    M3_V = 92, 1, read_v, write_v
    M3_A = 93, 1, read_i, write_i
    M3_OVP = 94, 1, read_v, partial(write_v, off=2)
    M3_OCP = 95, 1, read_i, write_i

    M4_V = 96, 1, read_v, write_v
    M4_A = 97, 1, read_i, write_i
    M4_OVP = 98, 1, read_v, partial(write_v, off=2)
    M4_OCP = 99, 1, read_i, write_i

    M5_V = 100, 1, read_v, write_v
    M5_A = 101, 1, read_i, write_i
    M5_OVP = 102, 1, read_v, partial(write_v, off=2)
    M5_OCP = 103, 1, read_i, write_i

    M6_V = 104, 1, read_v, write_v
    M6_A = 105, 1, read_i, write_i
    M6_OVP = 106, 1, read_v, partial(write_v, off=2)
    M6_OCP = 107, 1, read_i, write_i

    M7_V = 108, 1, read_v, write_v
    M7_A = 109, 1, read_i, write_i
    M7_OVP = 110, 1, read_v, partial(write_v, off=2)
    M7_OCP = 111, 1, read_i, write_i

    M8_V = 112, 1, read_v, write_v
    M8_A = 113, 1, read_i, write_i
    M8_OVP = 114, 1, read_v, partial(write_v, off=2)
    M8_OCP = 115, 1, read_i, write_i

    M9_V = 116, 1, read_v, write_v
    M9_A = 117, 1, read_i, write_i
    M9_OVP = 118, 1, read_v, partial(write_v, off=2)
    M9_OCP = 119, 1, read_i, write_i

    addr: int
    count: int
    read: ValueMap
    write: RegMap

    def __new__(cls, addr: int, count: int, read: ValueMap, write: RegMap):
        obj = object.__new__(cls)
        obj._value_ = addr
        obj.addr = addr
        obj.count = count
        obj.read = read
        obj.write = write
        return obj

    @override
    @classmethod
    def _missing_(cls, value: object) -> Field | None:
        if isinstance(value, str):
            return cls.__members__.get(value.upper())
        return None

    @property
    def label(self) -> str:
        return self.name.lower()

    @override
    def __str__(self) -> str:
        return self.label

    @property
    def is_readable(self):
        return self.read is not None

    @property
    def is_writable(self):
        return self.write is not None


def flatten_fields(
    fields: Sequence[str | Field | Sequence[str | Field]],
) -> Iterator[Field]:
    for field in fields:
        if isinstance(field, Field):
            yield field
        elif isinstance(field, str):
            yield Field(field)
        elif isinstance(field, Sequence):
            yield from flatten_fields(field)
        else:
            raise TypeError(
                f"expected field name or sequence, got {type(field).__name__}"
            )
