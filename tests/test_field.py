"""Tests for the device register map and its value mappers."""

from typing import Any, cast

import pytest

from riden.enums import Mode, Protection
from riden.field import *
from riden.model import Model

MODEL = Model.RD6006P.value

def RegRead_of(field: Field) -> RegRead:
    RegRead = field.read
    assert RegRead is not None
    return RegRead


def RegWrite_of(field: Field) -> RegWrite:
    RegWrite = field.write
    assert RegWrite is not None
    return RegWrite


def test_field_metadata() -> None:
    assert Field.V_SET.addr == 8
    assert Field.V_SET.count == 1
    assert Field.P.addr == 12
    assert Field.P.count == 2
    assert Field.SN.count == 2


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
    assert [field.addr for field in block] == list(range(55, 65))
    assert all(field.is_readable and field.is_writable for field in block)


def test_cal_i12_is_readable_and_writable() -> None:
    assert (Field.CAL_I12_ZERO.addr, Field.CAL_I12_SCALE.addr) == (63, 64)
    assert RegRead_of(Field.CAL_I12_SCALE)((1234,), MODEL) == 1234
    assert RegWrite_of(Field.CAL_I12_SCALE)(1234, MODEL) == (1234,)


def test_field_label_and_str() -> None:
    assert Field.V_SET.label == "v_set"
    assert str(Field.V_SET) == "v_set"


def test_field_lookup_by_name_and_address() -> None:
    assert Field("v_set") is Field.V_SET
    assert Field("V_SET") is Field.V_SET
    assert Field(8) is Field.V_SET


def test_field_lookup_rejects_unknown_values() -> None:
    with pytest.raises(ValueError):
        Field("nope")
    with pytest.raises(ValueError):
        Field(9999)


def test_readable_and_writable_flags() -> None:
    assert Field.V.is_readable
    assert not Field.V.is_writable
    assert Field.CAL_COMMIT.is_writable
    assert not Field.CAL_COMMIT.is_readable
    assert Field.V_SET.is_readable
    assert Field.V_SET.is_writable


def test_scalar_RegReads() -> None:
    assert read_flag((0,), MODEL) is False
    assert read_flag((1,), MODEL) is True
    assert read_int((42,), MODEL) == 42
    assert read_protection((0,), MODEL) is Protection.NONE
    assert read_protection((2,), MODEL) is Protection.OCP
    assert read_mode((0,), MODEL) is Mode.CV
    assert read_mode((1,), MODEL) is Mode.CC


def test_multiregister_RegReads() -> None:
    assert read_dw((0x0001, 0x0002), MODEL) == 0x10002
    assert read_temp((0, 25), MODEL) == 25
    assert read_temp((1, 25), MODEL) == -25


def test_scaled_RegReads_use_model_scales() -> None:
    assert read_v((12500,), MODEL) == 12.5
    assert read_i((10000,), MODEL) == 1.0
    assert read_v((12500,), Model.RD6006.value) == 125.0
    assert read_centi((1234,), MODEL) == 12.34
    assert read_milli_dw((1, 0), MODEL) == 65.536


def test_scalar_RegWrites_always_return_register_tuples() -> None:
    assert write_int(7, MODEL) == (7,)
    assert write_int(True, MODEL) == (1,)
    assert write_v(12.5, MODEL) == (12500,)
    assert write_i(1.0, MODEL) == (10000,)
    assert write_ovp(62.0, MODEL) == (62000,)
    assert write_ocp(6.2, MODEL) == (62000,)


def test_RegWrites_accept_device_limits() -> None:
    # RD6006P: setpoints up to v_max + 1 V and i_max + 0.1 A.
    assert write_v(61.0, MODEL) == (61000,)
    assert write_i(6.1, MODEL) == (61000,)


@pytest.mark.parametrize(
    ("writer", "value"),
    [(write_v, -5.0), (write_v, 61.001), (write_v, 100.0), (write_i, -0.1), (write_i, 6.1001), (write_i, 100.0)],
)
def test_RegWrites_reject_out_of_range(writer: RegWrite, value: float) -> None:
    with pytest.raises(ValueError, match="out of range"):
        writer(value, MODEL)


def test_field_RegReads() -> None:
    assert RegRead_of(Field.V_SET)((12500,), MODEL) == 12.5
    assert RegRead_of(Field.FW)((1234,), MODEL) == 12.34
    assert RegRead_of(Field.P)((0, 60000), MODEL) == 60.0
    assert RegRead_of(Field.P)((0, 6000), Model.RD6006.value) == 60.0
    assert RegRead_of(Field.P)((1, 0), Model.RD6012.value) == 655.36
    assert RegRead_of(Field.TEMP_C)((1, 5), MODEL) == -5
    assert RegRead_of(Field.PROTECTION)((2,), MODEL) is Protection.OCP


def test_field_RegWrites() -> None:
    assert RegWrite_of(Field.V_SET)(12.5, MODEL) == (12500,)
    assert RegWrite_of(Field.EN)(True, MODEL) == (1,)
    assert RegWrite_of(Field.M0_OVP)(62.0, MODEL) == (62000,)


def test_flatten_fields_preserves_order_and_flattens() -> None:
    fields = flatten_fields([Field.V, ["v_set", Field.I], Field.V])
    assert list(fields) == [Field.V, Field.V_SET, Field.I, Field.V]


def test_flatten_fields_accepts_any_iterable() -> None:
    nested = (f for f in ["v_set", Field.I])
    fields = flatten_fields((Field.V, nested, {"sn"}, ("en",)))
    assert list(fields) == [Field.V, Field.V_SET, Field.I, Field.SN, Field.EN]


def test_flatten_fields_rejects_other_types() -> None:
    with pytest.raises(TypeError):
        list(flatten_fields([cast(Any, 1)]))


@pytest.mark.parametrize("model", [Model.RK6006, Model.RD6012])
def test_preset_ocp_allows_device_limit(model: Model) -> None:
    # Factory presets store OCP = i_max + 0.2 A (6.2 A on RK6006, 12.2 A on RK6012).
    spec = model.value
    write = Field.M9_OCP.write
    assert write is not None
    assert write(spec.i_max + 0.2, spec) == (round((spec.i_max + 0.2) * spec.i_scale),)
    with pytest.raises(ValueError, match="out of range"):
        write(spec.i_max + 0.3, spec)
