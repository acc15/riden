"""Tests for the device register map and its value mappers."""

from functools import partial
from typing import Any, cast

import pytest

from riden.enums import Mode, Protection
from riden.field import *
from riden.model import Model

MODEL = Model.RD6006P

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
    assert read_v((12500,), Model.RD6006) == 125.0
    assert read_div(100, (1234,), MODEL) == 12.34
    assert div(100, 6000, MODEL) == 60.0


def test_compose_chains_mappers() -> None:
    RegRead = compose(read_dw, partial(div, 100))
    assert RegRead((0, 6000), MODEL) == 60.0


def test_scalar_RegWrites_always_return_register_tuples() -> None:
    assert write_int(7, MODEL) == (7,)
    assert write_int(True, MODEL) == (1,)
    assert write_v(12.5, MODEL) == (12500,)
    assert write_i(1.0, MODEL) == (10000,)
    assert write_v(62.0, MODEL, off=2) == (62000,)


def test_RegWrites_clamp_to_model_limits() -> None:
    assert write_v(-5.0, MODEL) == (0,)
    assert write_v(100.0, MODEL) == (60000,)
    assert write_i(100.0, MODEL) == (60000,)


def test_field_RegReads() -> None:
    assert RegRead_of(Field.V_SET)((12500,), MODEL) == 12.5
    assert RegRead_of(Field.FW)((1234,), MODEL) == 12.34
    assert RegRead_of(Field.P)((0, 6000), MODEL) == 60.0
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
