"""Model register maps.

A :class:`Spec` names a model: the ID codes it reports and a factory for its
register map.  The map is kept out of :class:`~riden.field.Field`, because the
same field can have a different address, size or encoding on different models.

:func:`riden_spec` is the single place that defines registers: every model
layout comes from it, so a register change is made once.  Its closures capture
the scaling factors and output limits of the model, so there is no separate
scaling table to keep in sync with the map.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from .enums import Mode, Protection
from .field import Field
from .layout import Layout
from .register import Register, Registers


def clamp(maximum: float, scale: int, v: float, off: float) -> int:
    """Encode ``v`` as a raw register value, checking it against the limit.

    The device acknowledges an out-of-range write but silently keeps the old
    value, so the range ``0..maximum + off`` is enforced here instead.  The
    check uses raw units, so float rounding cannot reject the limit itself.
    """
    raw = round(v * scale)
    limit = round((maximum + off) * scale)
    if not 0 <= raw <= limit:
        raise ValueError(f"{v} is out of range 0..{limit / scale}")
    return raw


@dataclass(frozen=True, slots=True, eq=False)
class Spec:
    """One device model: its ID codes and the factory of its register map.

    ``layout`` is called once, when the client connects, and the produced
    :class:`riden.layout.Layout` is kept by the client.  A factory rather than
    a ready map avoids building sixteen identical maps at import time and lets
    a model's map be built from its scaling parameters on first use.
    """

    codes: frozenset[int]
    layout: Callable[[], Layout]


def read_flag(r: Registers, _: Mapping[Field, Any]):
    return bool(r[0])


def read_int(r: Registers, _: Mapping[Field, Any]):
    return r[0]


def read_off(_: Registers, __: Mapping[Field, Any]):
    """Virtual selector: the model has no such switch, so it is always off."""
    return False


def write_off(_: Any, __: Mapping[Field, Any]) -> Registers:
    """Virtual selector: a write is accepted but changes nothing on the device."""
    return ()


def write_int(v, _: Mapping[Field, Any]) -> Registers:
    return (int(v),)


def read_protection(r: Registers, _: Mapping[Field, Any]):
    return Protection(r[0])


def read_mode(r: Registers, _: Mapping[Field, Any]):
    return Mode(r[0])


def read_dw(r: Registers, _: Mapping[Field, Any]):
    return r[0] << 16 | r[1]


def read_centi(r: Registers, _: Mapping[Field, Any]):
    """One register in hundredths: firmware version, input voltage."""
    return r[0] / 100


def read_milli_dw(r: Registers, deps: Mapping[Field, Any]):
    """Two registers in thousandths: Ah, Wh."""
    return read_dw(r, deps) / 1000


def read_temp(r: Registers, _: Mapping[Field, Any]):
    return (-1 if r[0] else 1) * r[1]


def riden_spec(
    *,
    v_max: int,
    v_scale: int,
    i_max: int | Sequence[int],
    i_scale: int | Sequence[int],
    p_scale: int,
) -> Callable[[], Layout]:
    """Return the register layout factory of one model.

    ``v_max``/``i_max`` are the nominal limits in volts and amperes; the
    device accepts setpoints up to ``v_max + 1`` and ``i_max + 0.1``, OVP up
    to ``v_max + 2`` and OCP up to ``i_max + 0.2``.  Raw register values are
    divided by ``*_scale`` on read and multiplied on write.

    ``i_max``/``i_scale`` may be sequences, one entry per selectable current
    range.  Then every current is decoded against the selected range, which
    the codec receives as ``Field.I_RANGE``: 0 picks the first entry, any
    non-zero value the second.  Such models report the per-preset range in
    ``M*_I_RANGE`` and reserve a fifth register in each preset for it.
    """
    i_maxes = (i_max,) if isinstance(i_max, int) else tuple(i_max)
    i_scales = (i_scale,) if isinstance(i_scale, int) else tuple(i_scale)
    if len(i_maxes) != len(i_scales):
        raise ValueError("i_max and i_scale must have the same length")
    switched = len(i_maxes) > 1

    def i_range(deps: Mapping[Field, Any]) -> int:
        """Select the current range: 0 is the first, anything else the second."""
        return 1 if switched and deps[Field.I_RANGE] else 0

    def read_v(r: Registers, _: Mapping[Field, Any]):
        return r[0] / v_scale

    def write_v(v, _: Mapping[Field, Any]) -> Registers:
        """Voltage setpoint: the device accepts up to v_max + 1 V."""
        return (clamp(v_max, v_scale, v, 1),)

    def write_ovp(v, _: Mapping[Field, Any]) -> Registers:
        """Over-voltage protection: the device accepts up to v_max + 2 V."""
        return (clamp(v_max, v_scale, v, 2),)

    def read_i(r: Registers, deps: Mapping[Field, Any]):
        return r[0] / i_scales[i_range(deps)]

    def write_i(v, deps: Mapping[Field, Any]) -> Registers:
        """Current setpoint: the device accepts up to i_max + 0.1 A."""
        index = i_range(deps)
        return (clamp(i_maxes[index], i_scales[index], v, 0.1),)

    def write_ocp(v, deps: Mapping[Field, Any]) -> Registers:
        """Over-current protection: the device accepts up to i_max + 0.2 A."""
        index = i_range(deps)
        return (clamp(i_maxes[index], i_scales[index], v, 0.2),)

    def read_p(r: Registers, deps: Mapping[Field, Any]):
        return read_dw(r, deps) / p_scale

    def layout() -> Layout:
        """Return the register map of the model.

        The map is wrapped in ``MappingProxyType`` and then in a
        :class:`riden.layout.Layout`, so the client keeps exactly what the
        factory returned and no caller can modify the map in place.

        Presets M0..M9 occupy four consecutive registers each, starting at
        register 80.  Models with selectable current ranges add a fifth
        register to each preset, so their presets are five registers apart.
        """
        # The output and each preset scale current by their own range selector.
        # The maps are read-only, like the layout's register map, so a shipped
        # map cannot be changed by accident.
        output_deps = MappingProxyType({Field.I_RANGE: Field.I_RANGE} if switched else {})
        fields = {
            Field.ID: Register(0, 1, read_int),
            Field.SN: Register(1, 2, read_dw),
            Field.FW: Register(3, 1, read_centi),
            Field.TEMP_C: Register(4, 2, read_temp),
            Field.TEMP_F: Register(6, 2, read_temp),
            Field.V_SET: Register(8, 1, read_v, write_v),
            Field.I_SET: Register(9, 1, read_i, write_i, deps=output_deps),
            Field.V: Register(10, 1, read_v),
            Field.I: Register(11, 1, read_i, deps=output_deps),
            Field.P: Register(12, 2, read_p),
            Field.V_IN: Register(14, 1, read_centi),
            Field.LOCK: Register(15, 1, read_flag, write_int),
            Field.PROTECTION: Register(16, 1, read_protection),
            Field.MODE: Register(17, 1, read_mode),
            Field.EN: Register(18, 1, read_flag, write_int),
            Field.PRESET: Register(19, 1, read_int, write_int),
            # RD6012P current range: 0 is the 6 A range, otherwise 12 A.
            # Other models report 0.
            Field.I_RANGE: Register(20, 1, read_flag, write_int),
            Field.BAT_EN: Register(32, 1, read_flag),
            Field.BAT_V: Register(33, 1, read_v),
            Field.EXT_TEMP_C: Register(34, 2, read_temp),
            Field.EXT_TEMP_F: Register(36, 2, read_temp),
            Field.AH: Register(38, 2, read_milli_dw),
            Field.WH: Register(40, 2, read_milli_dw),
            Field.YEAR: Register(48, 1, read_int, write_int),
            Field.MONTH: Register(49, 1, read_int, write_int),
            Field.DAY: Register(50, 1, read_int, write_int),
            Field.HOUR: Register(51, 1, read_int, write_int),
            Field.MINUTE: Register(52, 1, read_int, write_int),
            Field.SECOND: Register(53, 1, read_int, write_int),
            # Register 54 is a command register, not calibration data:
            # writing 5377 (0x1501) commits the calibration registers 55-64 to
            # NVRAM.  It is not readable because it carries no meaningful
            # state.
            Field.CAL_COMMIT: Register(54, 1, None, write_int),
            Field.CAL_V_ZERO: Register(55, 1, read_int, write_int),
            Field.CAL_V_SCALE: Register(56, 1, read_int, write_int),
            Field.CAL_BV_ZERO: Register(57, 1, read_int, write_int),
            Field.CAL_BV_SCALE: Register(58, 1, read_int, write_int),
            Field.CAL_I_ZERO: Register(59, 1, read_int, write_int),
            Field.CAL_I_SCALE: Register(60, 1, read_int, write_int),
            Field.CAL_BI_ZERO: Register(61, 1, read_int, write_int),
            Field.CAL_BI_SCALE: Register(62, 1, read_int, write_int),
            # RD6012P only: a second output-current calibration pair for the
            # 12 A range.  The vendor app reads registers 55-64 as one block
            # and shows these two only for model code 60125; on other models
            # read them but do not treat them as meaningful.
            Field.CAL_I12_ZERO: Register(63, 1, read_int, write_int),
            Field.CAL_I12_SCALE: Register(64, 1, read_int, write_int),
            Field.TAKE_OK: Register(66, 1, read_flag, write_int),
            Field.TAKE_OUT: Register(67, 1, read_flag, write_int),
            Field.BOOT_EN: Register(68, 1, read_flag, write_int),
            Field.VOLUME: Register(69, 1, read_flag, write_int),
            Field.LOGO: Register(70, 1, read_flag, write_int),
            Field.LANG: Register(71, 1, read_int, write_int),
            Field.BACKLIGHT: Register(72, 1, read_int, write_int),
        }

        stride = 5 if switched else 4
        for n in range(10):
            base = 80 + stride * n
            # One current codec serves every preset: it asks for I_RANGE and
            # the map aliases it to this preset's own range register.
            preset_deps = MappingProxyType({Field.I_RANGE: Field(f"m{n}_i_range")} if switched else {})
            fields[Field(f"m{n}_v")] = Register(base, 1, read_v, write_v)
            fields[Field(f"m{n}_i")] = Register(base + 1, 1, read_i, write_i, deps=preset_deps)
            fields[Field(f"m{n}_ovp")] = Register(base + 2, 1, read_v, write_ovp)
            fields[Field(f"m{n}_ocp")] = Register(base + 3, 1, read_i, write_ocp, deps=preset_deps)
            if switched:
                fields[Field(f"m{n}_i_range")] = Register(base + 4, 1, read_flag, write_int)
            else:
                # The model has no switchable range, but callers should not
                # need a per-model code path: a zero-size field is virtual, so
                # its codecs touch no register.
                fields[Field(f"m{n}_i_range")] = Register(0, 0, read_off, write_off)

        # A dependency the map cannot decode would otherwise fail at the first
        # read of that field; catch it when the map is built instead.
        for field, register in fields.items():
            unsupported = register.dependencies - fields.keys()
            if unsupported:
                names = ", ".join(dep.value for dep in sorted(unsupported))
                raise ValueError(f"field {field.value} depends on unsupported fields: {names}")

        return Layout(MappingProxyType(fields))

    return layout
