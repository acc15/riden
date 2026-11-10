
from collections.abc import Callable, Iterator, Sequence
from enum import StrEnum
from functools import partial
from typing import Any

from .enums import Mode, Protection
from .model import Model

type ValueMap = Callable[[list[int] | int, Model], Any] | None
type RegMap = Callable[[Any, Model], list[int] | int] | None

def compose(*funcs):
    def composed_fn(arg: Any, *others):
        for fn in funcs:
            arg = fn(arg, *others)
        return arg
    return composed_fn

def flag(v, _: Model):
    return bool(v)

def number(v, _: Model):
    return int(v)

def protection(v, _: Model):
    return Protection(v)

def mode(v, _: Model):
    return Mode(v)

def div(d, x, _: Model):
    return x / d

def read_dw(r: list[int], _: Model):
    return r[0] << 16 | r[1]

def read_temp(r: list[int], _: Model):
    return (-1 if r[0] else 1) * r[1]

def read_v(v, m: Model):
    return v / m.v_scale

def write_v(v, m: Model, off = 0):
    return m.v_clamp(v, off)

def read_i(v, m: Model):
    return v / m.i_scale

def write_i(v, m: Model, off = 0):
    return m.i_clamp(v, off)

class Field(StrEnum):
    ID = "id", 0, 1, number, None
    SN = "sn", 1, 2, read_dw, None
    FW = "fw", 3, 1, partial(div, 100), None
    TEMP_C = "temp_c", 4, 2, read_temp, None
    TEMP_F = "temp_f", 6, 2, read_temp, None
    V_SET = "v_set", 8, 1, read_v, write_v
    I_SET = "i_set", 9, 1, read_i, write_i
    V = "v", 10, 1, read_v, None
    I = "i", 11, 1, read_i, None
    P = "p", 12, 2, compose(read_dw, partial(div, 100)), None
    V_IN = "v_in", 14, 1, partial(div, 100), None
    LOCK = "lock", 15, 1, flag, number
    PROTECTION = "protection", 16, 1, protection, None
    MODE = "mode", 17, 1, mode, None
    EN = "en", 18, 1, flag, number
    PRESET = "preset", 19, 1, number, number

    BAT_EN = "bat_en", 32, 1, flag, None
    BAT_V = "bat_v", 33, 1, read_v, None
    EXT_TEMP_C = "ext_temp_c", 34, 2, read_temp, None
    EXT_TEMP_F = "ext_temp_f", 36, 2, read_temp, None
    AH = "ah", 38, 2, compose(read_dw, partial(div, 1000)), None
    WH = "wh", 40, 2, compose(read_dw, partial(div, 1000)), None

    YEAR = "year", 48, 1, number, number
    MONTH = "month", 49, 1, number, number
    DAY = "day", 50, 1, number, number
    HOUR = "hour", 51, 1, number, number
    MINUTE = "minute", 52, 1, number, number
    SECOND = "second", 53, 1, number, number

    # Calibration values are raw register values; writing CAL_DATE commits
    # the calibration registers to NVRAM (the documented magic value is 5377).
    CAL_DATE = "cal_date", 54, 1, None, number
    CAL_V_ZERO = "cal_v_zero", 55, 1, number, number
    CAL_V_SCALE = "cal_v_scale", 56, 1, number, number
    CAL_BV_ZERO = "cal_bv_zero", 57, 1, number, number
    CAL_BV_SCALE = "cal_bv_scale", 58, 1, number, number
    CAL_I_ZERO = "cal_i_zero", 59, 1, number, number
    CAL_I_SCALE = "cal_i_scale", 60, 1, number, number
    CAL_BI_ZERO = "cal_bi_zero", 61, 1, number, number
    CAL_BI_SCALE = "cal_bi_scale", 62, 1, number, number

    TAKE_OK = "take_ok", 66, 1, flag, number
    TAKE_OUT = "take_out", 67, 1, flag, number
    BOOT_EN = "boot_en", 68, 1, flag, number
    VOLUME = "volume", 69, 1, flag, number
    LOGO = "logo", 70, 1, flag, number
    LANG = "lang", 71, 1, number, number
    BACKLIGHT = "backlight", 72, 1, number, number

    M0_V = "m0_v", 80, 1, read_v, write_v
    M0_A = "m0_a", 81, 1, read_i, write_i
    M0_OVP = "m0_ovp", 82, 1, read_v, partial(write_v, off=2)
    M0_OCP = "m0_ocp", 83, 1, read_i, write_i

    M1_V = "m1_v", 84, 1, read_v, write_v
    M1_A = "m1_a", 85, 1, read_i, write_i
    M1_OVP = "m1_ovp", 86, 1, read_v, partial(write_v, off=2)
    M1_OCP = "m1_ocp", 87, 1, read_i, write_i

    M2_V = "m2_v", 88, 1, read_v, write_v
    M2_A = "m2_a", 89, 1, read_i, write_i
    M2_OVP = "m2_ovp", 90, 1, read_v, partial(write_v, off=2)
    M2_OCP = "m2_ocp", 91, 1, read_i, write_i

    M3_V = "m3_v", 92, 1, read_v, write_v
    M3_A = "m3_a", 93, 1, read_i, write_i
    M3_OVP = "m3_ovp", 94, 1, read_v, partial(write_v, off=2)
    M3_OCP = "m3_ocp", 95, 1, read_i, write_i

    M4_V = "m4_v", 96, 1, read_v, write_v
    M4_A = "m4_a", 97, 1, read_i, write_i
    M4_OVP = "m4_ovp", 98, 1, read_v, partial(write_v, off=2)
    M4_OCP = "m4_ocp", 99, 1, read_i, write_i

    M5_V = "m5_v", 100, 1, read_v, write_v
    M5_A = "m5_a", 101, 1, read_i, write_i
    M5_OVP = "m5_ovp", 102, 1, read_v, partial(write_v, off=2)
    M5_OCP = "m5_ocp", 103, 1, read_i, write_i

    M6_V = "m6_v", 104, 1, read_v, write_v
    M6_A = "m6_a", 105, 1, read_i, write_i
    M6_OVP = "m6_ovp", 106, 1, read_v, partial(write_v, off=2)
    M6_OCP = "m6_ocp", 107, 1, read_i, write_i

    M7_V = "m7_v", 108, 1, read_v, write_v
    M7_A = "m7_a", 109, 1, read_i, write_i
    M7_OVP = "m7_ovp", 110, 1, read_v, partial(write_v, off=2)
    M7_OCP = "m7_ocp", 111, 1, read_i, write_i

    M8_V = "m8_v", 112, 1, read_v, write_v
    M8_A = "m8_a", 113, 1, read_i, write_i
    M8_OVP = "m8_ovp", 114, 1, read_v, partial(write_v, off=2)
    M8_OCP = "m8_ocp", 115, 1, read_i, write_i

    M9_V = "m9_v", 116, 1, read_v, write_v
    M9_A = "m9_a", 117, 1, read_i, write_i
    M9_OVP = "m9_ovp", 118, 1, read_v, partial(write_v, off=2)
    M9_OCP = "m9_ocp", 119, 1, read_i, write_i

    addr: int
    count: int
    read: ValueMap
    write: RegMap

    def __new__(cls, value: str, addr: int, count: int, read: ValueMap, write: RegMap):
        obj = str.__new__(cls, value)
        obj._value_ = value
        obj.addr = addr
        obj.count = count
        obj.read = read
        obj.write = write
        return obj

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
        if isinstance(field, str):
            yield Field(field)
        elif isinstance(field, Sequence):
            yield from flatten_fields(field)
        else:
            raise TypeError(
                f"expected field name or sequence, got {type(field).__name__}"
            )
