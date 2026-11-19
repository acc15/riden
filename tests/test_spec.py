"""Tests for the model register maps and the layout that plans I/O.

The maps belong to models and are built by :func:`riden.spec.riden_spec`; a
:class:`riden.layout.Layout` wraps one and decides what the client reads and
writes.
"""

from types import MappingProxyType
from typing import Any, cast

import pytest

from riden.enums import Mode, Protection
from riden.field import Field, FieldRef
from riden.layout import Layout
from riden.model import Model
from riden.preset import PresetField, PresetParam
from riden.register import Register
from riden.spec import (
    clamp,
    read_centi,
    read_dw,
    read_milli_dw,
    read_single,
    read_temp,
    write_int,
)
from tests.conftest import reader, writer

BASE_LAYOUT = Model.RD6006P.value.layout()
BASE = BASE_LAYOUT.registers
RD6006 = Model.RD6006.value.layout().registers
RD6012 = Model.RD6012.value.layout().registers
RD6012P_LAYOUT = Model.RD6012P.value.layout()
RD6012P = RD6012P_LAYOUT.registers

PRESETS = {
    PresetField(num, param)
    for num in range(10)
    for param in PresetParam
}

RANGE_6A = {Field.I_MAX: 6, Field.I_SCALE: 10000, Field.I_TOLERANCE: 0.1}
RANGE_12A = {Field.I_MAX: 12, Field.I_SCALE: 1000, Field.I_TOLERANCE: 0.1}
SELECT_6A = {Field.I_RANGE: 0}
SELECT_12A = {Field.I_RANGE: 1}

BASE_V = {Field.V_SCALE: 1000}
BASE_V_WRITE = {
    Field.V_MAX: 60,
    Field.V_SCALE: 1000,
    Field.V_TOLERANCE: 1.0,
}
BASE_OVP_WRITE = {
    Field.V_MAX: 60,
    Field.V_SCALE: 1000,
    Field.V_TOLERANCE: 2.0,
}
BASE_I = {Field.I_SCALE: 10000}
BASE_I_WRITE = {
    Field.I_MAX: 6,
    Field.I_SCALE: 10000,
    Field.I_TOLERANCE: 0.1,
}
BASE_OCP_WRITE = {
    Field.I_MAX: 6,
    Field.I_SCALE: 10000,
    Field.I_TOLERANCE: 0.2,
}
BASE_P = {Field.P_SCALE: 1000}


def layout_of(registers: dict[Field, Register]) -> Layout:
    """Wrap a test map the same way a model factory does."""
    return Layout(MappingProxyType(registers))


# Register maps


def test_every_model_covers_every_field() -> None:
    expected = {FieldRef(field) for field in (*Field, *PRESETS)}
    for model in Model:
        assert set(model.value.layout().fields()) == expected


def test_register_metadata() -> None:
    assert (BASE[Field.V_SET].addr, BASE[Field.V_SET].size) == (8, 1)
    assert (BASE[Field.P].addr, BASE[Field.P].size) == (12, 2)
    assert BASE[Field.SN].size == 2


def test_base_presets_take_four_registers() -> None:
    for n in range(10):
        base = 80 + 4 * n
        assert BASE_LAYOUT.addr(FieldRef(PresetField(n, PresetParam.V))) == base
        assert BASE_LAYOUT.addr(FieldRef(PresetField(n, PresetParam.OCP))) == base + 3


def test_rd6012p_presets_take_five_registers() -> None:
    parts = (
        PresetParam.V,
        PresetParam.I,
        PresetParam.OVP,
        PresetParam.OCP,
        PresetParam.I_RANGE,
    )

    def addresses(num: int) -> list[int]:
        return [RD6012P_LAYOUT.addr(FieldRef(PresetField(num, part))) for part in parts]

    assert addresses(0) == [80, 81, 82, 83, 84]
    assert addresses(9) == [125, 126, 127, 128, 129]


def test_calibration_block_is_contiguous() -> None:
    block = [
        Field.CAL_V_ZERO,
        Field.CAL_V_SCALE,
        Field.CAL_BV_ZERO,
        Field.CAL_BV_SCALE,
        Field.CAL_I_ZERO,
        Field.CAL_I_SCALE,
        Field.CAL_BI_ZERO,
        Field.CAL_BI_SCALE,
        Field.CAL_I12_ZERO,
        Field.CAL_I12_SCALE,
    ]
    assert [BASE[field].addr for field in block] == list(range(55, 65))
    assert all(BASE[field].is_readable and BASE[field].is_writable for field in block)


def test_cal_i12_is_readable_and_writable() -> None:
    assert (BASE[Field.CAL_I12_ZERO].addr, BASE[Field.CAL_I12_SCALE].addr) == (63, 64)
    assert reader(BASE, Field.CAL_I12_SCALE)((1234,), {}) == 1234
    assert writer(BASE, Field.CAL_I12_SCALE)(1234, {}) == (1234,)


def test_readable_and_writable_flags() -> None:
    assert BASE[Field.V].is_readable
    assert not BASE[Field.V].is_writable
    assert BASE[Field.CAL_COMMIT].is_writable
    assert not BASE[Field.CAL_COMMIT].is_readable
    assert BASE[Field.V_SET].is_readable
    assert BASE[Field.V_SET].is_writable


# Dependencies


def test_rd6012p_current_deps_are_aliased() -> None:
    assert RD6012P[Field.I_SET].deps == {
        Field.I_MAX: Field.I_MAX,
        Field.I_SCALE: Field.I_SCALE,
        Field.I_TOLERANCE: Field.I_TOLERANCE,
    }
    # Measured current only needs the scale; the max is a write-side concern.
    assert RD6012P[Field.I].deps == {Field.I_SCALE: Field.I_SCALE}
    assert RD6012P_LAYOUT.deps(FieldRef(PresetField(1, PresetParam.I))) == {
        Field.I_MAX: FieldRef(PresetField(1, PresetParam.I_MAX)),
        Field.I_SCALE: FieldRef(PresetField(1, PresetParam.I_SCALE)),
        Field.I_TOLERANCE: FieldRef(Field.I_TOLERANCE),
    }
    assert RD6012P_LAYOUT.deps(FieldRef(PresetField(1, PresetParam.OCP))) == {
        Field.I_MAX: FieldRef(PresetField(1, PresetParam.I_MAX)),
        Field.I_SCALE: FieldRef(PresetField(1, PresetParam.I_SCALE)),
        Field.I_TOLERANCE: FieldRef(Field.OCP_TOLERANCE),
    }
    assert RD6012P_LAYOUT.dependencies(FieldRef(PresetField(1, PresetParam.I))) == frozenset(
        {
            FieldRef(PresetField(1, PresetParam.I_MAX)),
            FieldRef(PresetField(1, PresetParam.I_SCALE)),
            FieldRef(Field.I_TOLERANCE),
        }
    )


def test_base_currents_depend_on_virtual_metadata() -> None:
    assert BASE[Field.I_SET].deps == {
        Field.I_MAX: Field.I_MAX,
        Field.I_SCALE: Field.I_SCALE,
        Field.I_TOLERANCE: Field.I_TOLERANCE,
    }
    assert BASE[Field.I].deps == {Field.I_SCALE: Field.I_SCALE}
    assert BASE_LAYOUT.deps(FieldRef(PresetField(1, PresetParam.I))) == {
        Field.I_MAX: FieldRef(PresetField(1, PresetParam.I_MAX)),
        Field.I_SCALE: FieldRef(PresetField(1, PresetParam.I_SCALE)),
        Field.I_TOLERANCE: FieldRef(Field.I_TOLERANCE),
    }
    assert BASE_LAYOUT.dependencies(FieldRef(PresetField(1, PresetParam.I))) == frozenset(
        {
            FieldRef(PresetField(1, PresetParam.I_MAX)),
            FieldRef(PresetField(1, PresetParam.I_SCALE)),
            FieldRef(Field.I_TOLERANCE),
        }
    )


def test_model_deps_are_read_only() -> None:
    # The maps are built once by the factory and shipped; a stray assignment
    # must not change how currents are scaled.
    presets = RD6012P_LAYOUT.presets
    assert presets is not None
    deps = presets.template[PresetParam.I].deps
    assert isinstance(deps, MappingProxyType)
    with pytest.raises(TypeError):
        cast(Any, deps)[Field.I_MAX] = Field.I


def test_make_deps_exposes_declared_fields_under_aliases() -> None:
    values = {
        FieldRef(PresetField(1, PresetParam.I_MAX)): 6,
        FieldRef(PresetField(1, PresetParam.I_SCALE)): 10000,
        FieldRef(Field.I_TOLERANCE): 0.1,
        FieldRef(Field.I_RANGE): False,
    }
    assert RD6012P_LAYOUT.make_deps(FieldRef(PresetField(1, PresetParam.I)), values) == {
        Field.I_MAX: 6,
        Field.I_SCALE: 10000,
        Field.I_TOLERANCE: 0.1,
    }
    assert BASE_LAYOUT.make_deps(
        FieldRef(Field.V_SET),
        {
            FieldRef(Field.V_MAX): 60,
            FieldRef(Field.V_SCALE): 1000,
            FieldRef(Field.V_TOLERANCE): 1.0,
        },
    ) == BASE_V_WRITE


def test_make_deps_requires_the_real_field_to_be_decoded() -> None:
    with pytest.raises(KeyError):
        RD6012P_LAYOUT.make_deps(
            FieldRef(PresetField(1, PresetParam.I)),
            {FieldRef(PresetField(1, PresetParam.I_MAX)): 6},
        )


def test_register_keeps_the_deps_mapping_as_given() -> None:
    deps = {Field.I_RANGE: Field.I_RANGE}
    register = Register(0, 1, deps=deps)
    assert register.deps is deps
    assert frozenset(register.deps.values()) == frozenset({Field.I_RANGE})


# Virtual fields


def test_base_preset_range_is_virtual() -> None:
    for num in range(10):
        located = BASE_LAYOUT.resolve(FieldRef(PresetField(num, PresetParam.I_RANGE)))
        assert located is not None
        register = located.reg
        assert register.size == 0
        assert register.read is not None
        assert register.read((), {}) is False
        assert register.write is not None
        assert register.write(1, {}) == ()


def test_rd6012p_ranges_are_real_flags() -> None:
    for field in (Field.I_RANGE, *(PresetField(num, PresetParam.I_RANGE) for num in range(10))):
        located = RD6012P_LAYOUT.resolve(FieldRef(field))
        assert located is not None
        register = located.reg
        assert register.size == 1
        assert register.is_readable
        assert register.is_writable


# Model metadata


def test_metadata_fields_are_virtual_and_read_only() -> None:
    fields = [
        Field.V_MAX,
        Field.V_SCALE,
        Field.V_TOLERANCE,
        Field.OVP_TOLERANCE,
        Field.I_MAX,
        Field.I_SCALE,
        Field.I_TOLERANCE,
        Field.OCP_TOLERANCE,
        Field.P_MAX,
        Field.P_SCALE,
        *(PresetField(num, PresetParam.I_MAX) for num in range(10)),
        *(PresetField(num, PresetParam.I_SCALE) for num in range(10)),
    ]
    for field in fields:
        located = BASE_LAYOUT.resolve(FieldRef(field))
        assert located is not None
        register = located.reg
        assert register.size == 0
        assert register.is_readable
        assert not register.is_writable


@pytest.mark.parametrize(
    ("model", "v_max", "v_scale", "i_max", "i_scale", "p_max", "p_scale"),
    [
        (Model.RD6006P, 60, 1000, 6, 10000, 360, 1000),
        (Model.RD6012, 60, 100, 12, 100, 720, 100),
        (Model.RK4206H, 42, 100, 6, 1000, 252, 100),
        (Model.RK8009, 80, 100, 9, 1000, 720, 100),
    ],
)
def test_metadata_values_follow_model(
    model: Model,
    v_max: int,
    v_scale: int,
    i_max: int,
    i_scale: int,
    p_max: int,
    p_scale: int,
) -> None:
    layout = model.value.layout().registers

    assert reader(layout, Field.V_MAX)((), {}) == v_max
    assert reader(layout, Field.V_SCALE)((), {}) == v_scale
    assert reader(layout, Field.V_TOLERANCE)((), {}) == 1.0
    assert reader(layout, Field.OVP_TOLERANCE)((), {}) == 2.0
    assert reader(layout, Field.P_MAX)((), {}) == p_max
    assert reader(layout, Field.P_SCALE)((), {}) == p_scale
    assert reader(layout, Field.I_MAX)((), SELECT_6A) == i_max
    assert reader(layout, Field.I_SCALE)((), SELECT_6A) == i_scale
    assert reader(layout, Field.I_TOLERANCE)((), {}) == 0.1
    assert reader(layout, Field.OCP_TOLERANCE)((), {}) == 0.2


def test_tolerance_deps_are_aliased() -> None:
    assert RD6012P[Field.V_SET].deps[Field.V_TOLERANCE] is Field.V_TOLERANCE
    assert RD6012P_LAYOUT.deps(FieldRef(PresetField(1, PresetParam.OVP)))[Field.V_TOLERANCE] == Field.OVP_TOLERANCE
    assert RD6012P[Field.I_SET].deps[Field.I_TOLERANCE] is Field.I_TOLERANCE
    assert RD6012P_LAYOUT.deps(FieldRef(PresetField(1, PresetParam.I)))[Field.I_TOLERANCE] == Field.I_TOLERANCE
    assert RD6012P_LAYOUT.deps(FieldRef(PresetField(1, PresetParam.OCP)))[Field.I_TOLERANCE] == Field.OCP_TOLERANCE


def test_rd6012p_metadata_follows_selected_range() -> None:
    assert reader(RD6012P, Field.I_MAX)((), SELECT_6A) == 6
    assert reader(RD6012P, Field.I_MAX)((), SELECT_12A) == 12
    assert reader(RD6012P, Field.I_SCALE)((), SELECT_6A) == 10000
    assert reader(RD6012P, Field.I_SCALE)((), SELECT_12A) == 1000


def test_rd6012p_preset_metadata_follows_its_range() -> None:
    field = PresetField(1, PresetParam.I_MAX)
    assert reader(RD6012P_LAYOUT, field)((), SELECT_6A) == 6
    assert reader(RD6012P_LAYOUT, field)((), SELECT_12A) == 12
    scale = PresetField(1, PresetParam.I_SCALE)
    assert reader(RD6012P_LAYOUT, scale)((), SELECT_6A) == 10000
    assert reader(RD6012P_LAYOUT, scale)((), SELECT_12A) == 1000


def test_metadata_deps_follow_range_registers() -> None:
    assert RD6012P[Field.I_MAX].deps == {Field.I_RANGE: Field.I_RANGE}
    assert RD6012P[Field.I_SCALE].deps == {Field.I_RANGE: Field.I_RANGE}
    assert RD6012P_LAYOUT.deps(FieldRef(PresetField(1, PresetParam.I_MAX))) == {
        Field.I_RANGE: FieldRef(PresetField(1, PresetParam.I_RANGE))
    }
    assert RD6012P_LAYOUT.deps(FieldRef(PresetField(1, PresetParam.I_SCALE))) == {
        Field.I_RANGE: FieldRef(PresetField(1, PresetParam.I_RANGE))
    }
    assert BASE[Field.I_MAX].deps == {}
    assert BASE_LAYOUT.deps(FieldRef(PresetField(1, PresetParam.I_MAX))) == {}


def test_base_preset_metadata_is_constant() -> None:
    assert reader(BASE_LAYOUT, PresetField(1, PresetParam.I_MAX))((), {}) == 6
    assert reader(BASE_LAYOUT, PresetField(1, PresetParam.I_SCALE))((), {}) == 10000


# Codecs


def test_scalar_readers() -> None:
    assert read_single(bool)((0,), {}) is False
    assert read_single(bool)((1,), {}) is True
    assert read_single(int)((42,), {}) == 42
    assert read_single(Protection)((0,), {}) is Protection.NONE
    assert read_single(Protection)((2,), {}) is Protection.OCP
    assert read_single(Mode)((0,), {}) is Mode.CV
    assert read_single(Mode)((1,), {}) is Mode.CC


def test_multiregister_readers() -> None:
    assert read_dw((0x0001, 0x0002), {}) == 0x10002
    assert read_temp((0, 25), {}) == 25
    assert read_temp((1, 25), {}) == -25


def test_scaled_readers_use_model_scales() -> None:
    assert reader(BASE, Field.V_SET)((12500,), BASE_V) == 12.5
    assert reader(BASE, Field.I_SET)((10000,), BASE_I) == 1.0
    assert reader(RD6006, Field.V_SET)((12500,), {Field.V_SCALE: 100}) == 125.0
    assert read_centi((1234,), {}) == 12.34
    assert read_milli_dw((1, 0), {}) == 65.536


def test_register_readers() -> None:
    assert reader(BASE, Field.FW)((1234,), {}) == 12.34
    assert reader(BASE, Field.P)((0, 60000), BASE_P) == 60.0
    assert reader(RD6006, Field.P)((0, 6000), {Field.P_SCALE: 100}) == 60.0
    assert reader(RD6012, Field.P)((1, 0), {Field.P_SCALE: 100}) == 655.36
    assert reader(BASE, Field.TEMP_C)((1, 5), {}) == -5
    assert reader(BASE, Field.PROTECTION)((2,), {}) is Protection.OCP


def test_scalar_writers_always_return_register_tuples() -> None:
    assert write_int(7, {}) == (7,)
    assert write_int(True, {}) == (1,)
    assert writer(BASE, Field.V_SET)(12.5, BASE_V_WRITE) == (12500,)
    assert writer(BASE, Field.I_SET)(1.0, BASE_I_WRITE) == (10000,)
    assert writer(BASE_LAYOUT, PresetField(0, PresetParam.OVP))(62.0, BASE_OVP_WRITE) == (62000,)
    assert writer(BASE_LAYOUT, PresetField(0, PresetParam.OCP))(6.2, BASE_OCP_WRITE) == (62000,)
    assert writer(BASE, Field.EN)(True, {}) == (1,)


def test_writers_accept_device_limits() -> None:
    # RD6006P: setpoints up to v_max + 1 V and i_max + 0.1 A.
    assert writer(BASE, Field.V_SET)(61.0, BASE_V_WRITE) == (61000,)
    assert writer(BASE, Field.I_SET)(6.1, BASE_I_WRITE) == (61000,)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (Field.V_SET, -5.0),
        (Field.V_SET, 61.001),
        (Field.V_SET, 100.0),
        (Field.I_SET, -0.1),
        (Field.I_SET, 6.1001),
        (Field.I_SET, 100.0),
    ],
)
def test_writers_reject_out_of_range(field: Field, value: float) -> None:
    deps = BASE_V_WRITE if field is Field.V_SET else BASE_I_WRITE
    with pytest.raises(ValueError, match="out of range"):
        writer(BASE, field)(value, deps)


@pytest.mark.parametrize(
    ("model", "i_max", "i_scale"), [(Model.RK6006, 6, 1000), (Model.RD6012, 12, 100)]
)
def test_preset_ocp_allows_device_limit(model: Model, i_max: int, i_scale: int) -> None:
    # Factory presets store OCP = i_max + 0.2 A.
    layout = model.value.layout()
    field = PresetField(9, PresetParam.OCP)
    write = writer(layout, field)
    deps = layout.make_deps(FieldRef(field), {
        FieldRef(PresetField(9, PresetParam.I_MAX)): i_max,
        FieldRef(PresetField(9, PresetParam.I_SCALE)): i_scale,
        FieldRef(Field.OCP_TOLERANCE): 0.2,
    })
    assert write(i_max + 0.2, deps) == (round((i_max + 0.2) * i_scale),)
    with pytest.raises(ValueError, match="out of range"):
        write(i_max + 0.3, deps)


def test_rd6012p_current_reads_follow_selected_range() -> None:
    read = reader(RD6012P, Field.I)
    assert read((1000,), RANGE_6A) == 0.1
    assert read((1000,), RANGE_12A) == 1.0


def test_rd6012p_current_writes_follow_selected_range() -> None:
    write = writer(RD6012P, Field.I_SET)
    assert write(1.0, RANGE_6A) == (10000,)
    assert write(1.0, RANGE_12A) == (1000,)
    assert write(12.0, RANGE_12A) == (12000,)
    with pytest.raises(ValueError, match="out of range 0..6.1"):
        write(12.0, RANGE_6A)


def test_rd6012p_ocp_follows_selected_range() -> None:
    field = PresetField(1, PresetParam.OCP)
    write = writer(RD6012P_LAYOUT, field)
    range_6a = RD6012P_LAYOUT.make_deps(FieldRef(field), {
        FieldRef(PresetField(1, PresetParam.I_MAX)): 6,
        FieldRef(PresetField(1, PresetParam.I_SCALE)): 10000,
        FieldRef(Field.OCP_TOLERANCE): 0.2,
    })
    range_12a = RD6012P_LAYOUT.make_deps(FieldRef(field), {
        FieldRef(PresetField(1, PresetParam.I_MAX)): 12,
        FieldRef(PresetField(1, PresetParam.I_SCALE)): 1000,
        FieldRef(Field.OCP_TOLERANCE): 0.2,
    })
    assert write(6.2, range_6a) == (62000,)
    assert write(12.2, range_12a) == (12200,)
    with pytest.raises(ValueError, match="out of range 0..6.2"):
        write(12.2, range_6a)


def test_clamp_encodes_and_checks_in_raw_units() -> None:
    assert clamp(60, 1000, 12.5, 0) == 12500
    assert clamp(60, 1000, 0, 0) == 0
    assert clamp(60, 1000, 60, 0) == 60000
    assert clamp(60, 1000, 62, 2) == 62000
    for v, off in ((-1, 0), (60.001, 0), (62.001, 2)):
        with pytest.raises(ValueError, match="out of range"):
            clamp(60, 1000, v, off)


def test_clamp_accepts_float_sums_at_limit() -> None:
    # 6 + 0.2, 12 + 0.1 and 6 + 0.1 are not exact in binary.
    assert clamp(6, 1000, 6.2, 0.2) == 6200
    assert clamp(12, 100, 12.1, 0.1) == 1210
    assert clamp(6, 10000, 6.1, 0.1) == 61000


# Planning helpers


CHAIN = layout_of({
    Field.V: Register(10, 1, read_single(int), deps={Field.I: Field.I}),
    Field.I: Register(11, 1, read_single(int), deps={Field.I_RANGE: Field.I_RANGE}),
    Field.I_RANGE: Register(20, 1, read_single(bool)),
})


def test_layout_exposes_the_register_map() -> None:
    registers = MappingProxyType({Field.V: Register(10, 1, read_single(int))})
    layout = Layout(registers)
    assert layout.registers is registers


def test_dependency_order_returns_dependencies_first() -> None:
    assert CHAIN.dependency_order([FieldRef(Field.V)]) == [Field.I_RANGE, Field.I, Field.V]
    assert CHAIN.dependency_order([]) == []


def test_dependency_order_supplied_fields_are_used_as_is() -> None:
    assert CHAIN.dependency_order(
        [FieldRef(Field.V)], supplied=frozenset({FieldRef(Field.I)})
    ) == [Field.V]
    assert CHAIN.dependency_order(
        [FieldRef(Field.V)],
        supplied=frozenset({FieldRef(Field.V), FieldRef(Field.I)}),
    ) == []
    # A supplied root still contributes its own direct dependencies.
    assert CHAIN.dependency_order(
        [FieldRef(Field.V)], supplied=frozenset({FieldRef(Field.V)})
    ) == [Field.I_RANGE, Field.I]


def test_dependency_order_rejects_unknown_fields() -> None:
    with pytest.raises(ValueError, match="field v is not supported"):
        layout_of({}).dependency_order([FieldRef(Field.V)])


def test_dependency_order_rejects_unknown_dependency() -> None:
    layout = layout_of({Field.V: Register(10, 1, read_single(int), deps={Field.I: Field.I})})
    with pytest.raises(ValueError, match=r"field i is not supported \(required by v\)"):
        layout.dependency_order([FieldRef(Field.V)])


def test_dependency_order_rejects_cycles() -> None:
    layout = layout_of({
        Field.V: Register(10, 1, read_single(int), deps={Field.I: Field.I}),
        Field.I: Register(11, 1, read_single(int), deps={Field.V: Field.V}),
    })
    with pytest.raises(ValueError, match="cyclic field dependencies: v -> i -> v"):
        layout.dependency_order([FieldRef(Field.V)])


def test_write_blocks_report_a_cycle_between_blocks() -> None:
    # V and I share a block; P depends on I and V depends on P.  The fields
    # are acyclic, but the merged blocks are not: one frame cannot hold V and
    # I while V has to follow P and P has to follow I.
    layout = layout_of({
        Field.V: Register(1, 1, deps={Field.P: Field.P}),
        Field.I: Register(2, 1),
        Field.P: Register(10, 1, deps={Field.I: Field.I}),
    })
    encoded = {
        FieldRef(Field.V): (1,),
        FieldRef(Field.I): (2,),
        FieldRef(Field.P): (10,),
    }
    with pytest.raises(ValueError, match="cyclic field dependencies: block@1 -> block@10"):
        layout.write_blocks(encoded)


def test_register_span_covers_gaps() -> None:
    layout = layout_of({
        Field.V: Register(10, 1, read_single(int)),
        Field.P: Register(12, 2, read_single(int)),
    })
    assert layout.register_span([FieldRef(Field.P), FieldRef(Field.V)]) == (10, 4)


def test_register_span_ignores_virtual_fields() -> None:
    layout = layout_of({
        Field.V: Register(10, 1, read_single(int)),
        Field.V_MAX: Register(0, 0, read_single(bool)),
    })
    assert layout.register_span([FieldRef(Field.V_MAX), FieldRef(Field.V)]) == (10, 1)


def test_register_span_of_only_virtual_fields_is_none() -> None:
    layout = layout_of({Field.V_MAX: Register(0, 0, read_single(bool))})
    assert layout.register_span([FieldRef(Field.V_MAX)]) is None


def test_write_blocks_merge_adjacent_registers() -> None:
    layout = layout_of({
        Field.V_SET: Register(8, 1),
        Field.I_SET: Register(9, 1),
        Field.EN: Register(18, 1),
    })
    encoded = {
        FieldRef(Field.V_SET): (12500,),
        FieldRef(Field.I_SET): (10000,),
        FieldRef(Field.EN): (1,),
    }
    assert layout.write_blocks(encoded) == [(8, (12500, 10000)), (18, (1,))]


def test_write_blocks_write_the_selector_first() -> None:
    layout = layout_of({
        Field.I_SET: Register(9, 1, deps={Field.I_RANGE: Field.I_RANGE}),
        Field.I_RANGE: Register(20, 1),
    })
    encoded = {FieldRef(Field.I_SET): (10000,), FieldRef(Field.I_RANGE): (0,)}
    assert layout.write_blocks(encoded) == [(20, (0,)), (9, (10000,))]


def test_write_blocks_order_through_virtual_dependencies() -> None:
    # A current's scale is virtual, but it still depends on the written range.
    # The chain has two virtual hops to make sure the walk is transitive.
    layout = layout_of({
        Field.I_SET: Register(9, 1, deps={Field.I_MAX: Field.I_MAX}),
        Field.I_MAX: Register(0, 0, deps={Field.I_SCALE: Field.I_SCALE}),
        Field.I_SCALE: Register(0, 0, deps={Field.I_RANGE: Field.I_RANGE}),
        Field.I_RANGE: Register(20, 1),
    })
    encoded = {FieldRef(Field.I_SET): (10000,), FieldRef(Field.I_RANGE): (0,)}
    assert layout.write_blocks(encoded) == [(20, (0,)), (9, (10000,))]


def test_write_blocks_ignore_virtual_chains_without_written_sources() -> None:
    layout = layout_of({
        Field.I_SET: Register(9, 1, deps={Field.I_MAX: Field.I_MAX}),
        Field.I_MAX: Register(0, 0, deps={Field.I_RANGE: Field.I_RANGE}),
        Field.I_RANGE: Register(20, 1),
    })
    assert layout.write_blocks({FieldRef(Field.I_SET): (10000,)}) == [(9, (10000,))]


def test_write_blocks_terminate_on_a_virtual_cycle() -> None:
    layout = layout_of({
        Field.I_SET: Register(9, 1, deps={Field.I_MAX: Field.I_MAX}),
        Field.I_MAX: Register(0, 0, deps={Field.I_SCALE: Field.I_SCALE}),
        Field.I_SCALE: Register(0, 0, deps={Field.I_MAX: Field.I_MAX}),
    })
    assert layout.write_blocks({FieldRef(Field.I_SET): (10000,)}) == [(9, (10000,))]


def test_write_blocks_keep_independent_fields_in_address_order() -> None:
    layout = layout_of({
        Field.EN: Register(18, 1),
        Field.V_SET: Register(8, 1),
    })
    encoded = {FieldRef(Field.EN): (1,), FieldRef(Field.V_SET): (12500,)}
    assert layout.write_blocks(encoded) == [(8, (12500,)), (18, (1,))]
