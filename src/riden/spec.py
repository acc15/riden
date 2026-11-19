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
from .field import Field, PresetParam
from .layout import Layout, PresetLayout
from .register import DepTarget, Register, Registers, RegRead

# The device accepts a setpoint slightly above the nominal limit and silently
# keeps the old value beyond it; these margins are part of the register map,
# exposed as the read-only V_TOLERANCE/OVP_TOLERANCE/I_TOLERANCE/OCP_TOLERANCE
# fields.
V_TOLERANCE = 1.0
OVP_TOLERANCE = 2.0
I_TOLERANCE = 0.1
OCP_TOLERANCE = 0.2


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


def read_single(convert: Callable[[int], Any]) -> RegRead:
    """Return a codec for a one-register field converted with ``convert``."""
    return lambda r, _: convert(r[0])


def read_const(value: Any) -> RegRead:
    """Return a codec for a virtual read-only field with a fixed value."""
    return lambda _r, _deps: value


def write_off(_: Any, __: Mapping[Field, Any]) -> Registers:
    """Virtual selector: a write is accepted but changes nothing on the device."""
    return ()


def write_int(v, _: Mapping[Field, Any]) -> Registers:
    return (int(v),)


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

    The same values are exposed as virtual read-only fields: ``V_MAX``,
    ``V_SCALE``, ``I_MAX``, ``I_SCALE``, ``P_MAX``, ``P_SCALE`` and, per
    preset, ``m*_i_max``/``m*_i_scale``.  The write margins are fields too:
    ``V_TOLERANCE``/``OVP_TOLERANCE`` and ``I_TOLERANCE``/``OCP_TOLERANCE``.
    They cost no I/O; the current ones follow the selected range, and
    ``P_MAX`` is the nominal ``v_max * max(i_max)``.

    ``i_max``/``i_scale`` may be sequences, one entry per selectable current
    range.  Then every current is decoded against the selected range, which
    the codec receives as ``Field.I_RANGE``: 0 picks the first entry, any
    non-zero value the second.  Such models report the per-preset range in
    ``m*_i_range`` and reserve a fifth register in each preset for it.
    """
    i_maxes = (i_max,) if isinstance(i_max, int) else tuple(i_max)
    i_scales = (i_scale,) if isinstance(i_scale, int) else tuple(i_scale)
    if len(i_maxes) != len(i_scales):
        raise ValueError("i_max and i_scale must have the same length")
    switched = len(i_maxes) > 1

    def i_range(deps: Mapping[Field, Any]) -> int:
        """Select the current range: 0 is the first, anything else the second."""
        return 1 if switched and deps[Field.I_RANGE] else 0

    def read_v(r: Registers, deps: Mapping[Field, Any]):
        return r[0] / deps[Field.V_SCALE]

    def write_voltage(v, deps: Mapping[Field, Any]) -> Registers:
        """Voltage setpoint or OVP, allowing the field's tolerance."""
        return (
            clamp(
                deps[Field.V_MAX],
                deps[Field.V_SCALE],
                v,
                deps[Field.V_TOLERANCE],
            ),
        )

    def read_i(r: Registers, deps: Mapping[Field, Any]):
        return r[0] / deps[Field.I_SCALE]

    def write_current(v, deps: Mapping[Field, Any]) -> Registers:
        """Current setpoint or OCP, allowing the field's tolerance."""
        return (
            clamp(
                deps[Field.I_MAX],
                deps[Field.I_SCALE],
                v,
                deps[Field.I_TOLERANCE],
            ),
        )

    def read_i_max(_: Registers, deps: Mapping[Field, Any]) -> int:
        """The maximum of the selected current range."""
        return i_maxes[i_range(deps)]

    def read_i_scale(_: Registers, deps: Mapping[Field, Any]) -> int:
        """Raw units per ampere of the selected current range."""
        return i_scales[i_range(deps)]

    def read_p(r: Registers, deps: Mapping[Field, Any]):
        return read_dw(r, deps) / deps[Field.P_SCALE]

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
        voltage_scale_deps = MappingProxyType({Field.V_SCALE: Field.V_SCALE})
        voltage_deps = MappingProxyType({
            Field.V_MAX: Field.V_MAX,
            Field.V_SCALE: Field.V_SCALE,
            Field.V_TOLERANCE: Field.V_TOLERANCE,
        })
        ovp_deps = MappingProxyType({
            Field.V_MAX: Field.V_MAX,
            Field.V_SCALE: Field.V_SCALE,
            Field.V_TOLERANCE: Field.OVP_TOLERANCE,
        })
        current_scale_deps = MappingProxyType({Field.I_SCALE: Field.I_SCALE})
        current_deps = MappingProxyType({
            Field.I_MAX: Field.I_MAX,
            Field.I_SCALE: Field.I_SCALE,
            Field.I_TOLERANCE: Field.I_TOLERANCE,
        })
        range_deps = MappingProxyType({Field.I_RANGE: Field.I_RANGE} if switched else {})
        p_scale_deps = MappingProxyType({Field.P_SCALE: Field.P_SCALE})
        fields = {
            Field.ID: Register(0, 1, read_single(int)),
            Field.SN: Register(1, 2, read_dw),
            Field.FW: Register(3, 1, read_centi),
            Field.TEMP_C: Register(4, 2, read_temp),
            Field.TEMP_F: Register(6, 2, read_temp),
            Field.V_SET: Register(8, 1, read_v, write_voltage, deps=voltage_deps),
            Field.I_SET: Register(9, 1, read_i, write_current, deps=current_deps),
            Field.V: Register(10, 1, read_v, deps=voltage_scale_deps),
            Field.I: Register(11, 1, read_i, deps=current_scale_deps),
            Field.P: Register(12, 2, read_p, deps=p_scale_deps),
            Field.V_IN: Register(14, 1, read_centi),
            Field.LOCK: Register(15, 1, read_single(bool), write_int),
            Field.PROTECTION: Register(16, 1, read_single(Protection)),
            Field.MODE: Register(17, 1, read_single(Mode)),
            Field.EN: Register(18, 1, read_single(bool), write_int),
            Field.PRESET: Register(19, 1, read_single(int), write_int),
            # RD6012P current range: 0 is the 6 A range, otherwise 12 A.
            # Other models report 0.
            Field.I_RANGE: Register(20, 1, read_single(bool), write_int),
            # Model metadata is virtual and read-only: size 0 means neither
            # codec touches a register, and a missing write codec rejects
            # attempts to write it.
            Field.V_MAX: Register(0, 0, read_const(v_max)),
            Field.V_SCALE: Register(0, 0, read_const(v_scale)),
            Field.V_TOLERANCE: Register(0, 0, read_const(V_TOLERANCE)),
            Field.OVP_TOLERANCE: Register(0, 0, read_const(OVP_TOLERANCE)),
            Field.I_MAX: Register(0, 0, read_i_max, deps=range_deps),
            Field.I_SCALE: Register(0, 0, read_i_scale, deps=range_deps),
            Field.I_TOLERANCE: Register(0, 0, read_const(I_TOLERANCE)),
            Field.OCP_TOLERANCE: Register(0, 0, read_const(OCP_TOLERANCE)),
            Field.P_MAX: Register(0, 0, read_const(v_max * max(i_maxes))),
            Field.P_SCALE: Register(0, 0, read_const(p_scale)),
            Field.BAT_EN: Register(32, 1, read_single(bool)),
            Field.BAT_V: Register(33, 1, read_v, deps=voltage_scale_deps),
            Field.EXT_TEMP_C: Register(34, 2, read_temp),
            Field.EXT_TEMP_F: Register(36, 2, read_temp),
            Field.AH: Register(38, 2, read_milli_dw),
            Field.WH: Register(40, 2, read_milli_dw),
            Field.YEAR: Register(48, 1, read_single(int), write_int),
            Field.MONTH: Register(49, 1, read_single(int), write_int),
            Field.DAY: Register(50, 1, read_single(int), write_int),
            Field.HOUR: Register(51, 1, read_single(int), write_int),
            Field.MINUTE: Register(52, 1, read_single(int), write_int),
            Field.SECOND: Register(53, 1, read_single(int), write_int),
            # Register 54 is a command register, not calibration data:
            # writing 5377 (0x1501) commits the calibration registers 55-64 to
            # NVRAM.  It is not readable because it carries no meaningful
            # state.
            Field.CAL_COMMIT: Register(54, 1, None, write_int),
            Field.CAL_V_ZERO: Register(55, 1, read_single(int), write_int),
            Field.CAL_V_SCALE: Register(56, 1, read_single(int), write_int),
            Field.CAL_BV_ZERO: Register(57, 1, read_single(int), write_int),
            Field.CAL_BV_SCALE: Register(58, 1, read_single(int), write_int),
            Field.CAL_I_ZERO: Register(59, 1, read_single(int), write_int),
            Field.CAL_I_SCALE: Register(60, 1, read_single(int), write_int),
            Field.CAL_BI_ZERO: Register(61, 1, read_single(int), write_int),
            Field.CAL_BI_SCALE: Register(62, 1, read_single(int), write_int),
            # RD6012P only: a second output-current calibration pair for the
            # 12 A range.  The vendor app reads registers 55-64 as one block
            # and shows these two only for model code 60125; on other models
            # read them but do not treat them as meaningful.
            Field.CAL_I12_ZERO: Register(63, 1, read_single(int), write_int),
            Field.CAL_I12_SCALE: Register(64, 1, read_single(int), write_int),
            Field.TAKE_OK: Register(66, 1, read_single(bool), write_int),
            Field.TAKE_OUT: Register(67, 1, read_single(bool), write_int),
            Field.BOOT_EN: Register(68, 1, read_single(bool), write_int),
            Field.VOLUME: Register(69, 1, read_single(bool), write_int),
            Field.LOGO: Register(70, 1, read_single(bool), write_int),
            Field.LANG: Register(71, 1, read_single(int), write_int),
            Field.BACKLIGHT: Register(72, 1, read_single(int), write_int),
        }

        # One template serves every preset.  A PresetParam in deps means "the
        # same preset's parameter"; Layout resolves it to a PresetField before
        # a codec sees it.
        preset_current_deps = MappingProxyType({
            Field.I_MAX: PresetParam.I_MAX,
            Field.I_SCALE: PresetParam.I_SCALE,
            Field.I_TOLERANCE: Field.I_TOLERANCE,
        })
        preset_ocp_deps = MappingProxyType({
            Field.I_MAX: PresetParam.I_MAX,
            Field.I_SCALE: PresetParam.I_SCALE,
            Field.I_TOLERANCE: Field.OCP_TOLERANCE,
        })
        preset_range_deps = MappingProxyType(
            {Field.I_RANGE: PresetParam.I_RANGE} if switched else {}
        )
        preset_template = {
            PresetParam.V: Register(0, 1, read_v, write_voltage, deps=voltage_deps),
            PresetParam.I: Register(1, 1, read_i, write_current, deps=preset_current_deps),
            PresetParam.OVP: Register(2, 1, read_v, write_voltage, deps=ovp_deps),
            PresetParam.OCP: Register(3, 1, read_i, write_current, deps=preset_ocp_deps),
            PresetParam.I_RANGE: (
                Register(4, 1, read_single(bool), write_int)
                if switched
                # The model has no switchable range, but callers should not
                # need a per-model code path: a zero-size field is virtual, so
                # its codecs touch no register.
                else Register(0, 0, read_const(False), write_off)
            ),
            PresetParam.I_MAX: Register(0, 0, read_i_max, deps=preset_range_deps),
            PresetParam.I_SCALE: Register(0, 0, read_i_scale, deps=preset_range_deps),
        }

        # A dependency the map cannot decode would otherwise fail at the first
        # read of that field; catch it when the map is built instead.
        for field, register in fields.items():
            unsupported = [dep for dep in register.deps.values() if dep not in fields]
            if unsupported:
                names = ", ".join(sorted(str(dep) for dep in unsupported))
                raise ValueError(f"field {field.value} depends on unsupported fields: {names}")

        for param, register in preset_template.items():
            unsupported: list[DepTarget] = []
            for dep in register.deps.values():
                if isinstance(dep, PresetParam):
                    if dep not in preset_template:
                        unsupported.append(dep)
                elif dep not in fields:
                    unsupported.append(dep)
            if unsupported:
                names = ", ".join(sorted(str(dep) for dep in unsupported))
                raise ValueError(
                    f"preset field {param.value} depends on unsupported fields: {names}"
                )

        return Layout(
            MappingProxyType(fields),
            PresetLayout(
                base=80,
                count=10,
                stride=PresetLayout.compute_stride(preset_template),
                template=MappingProxyType(preset_template),
            ),
        )

    return layout
