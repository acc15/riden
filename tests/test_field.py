"""Tests for the field names.

The register map is per model and lives in :mod:`riden.spec`; these tests only
cover the names themselves.
"""

from typing import Any, cast

import pytest

from riden.field import Field, FieldRef, flatten_fields, merge_fields
from riden.preset import PresetField, PresetParam


def test_field_str() -> None:
    assert str(Field.V_SET) == "v_set"
    assert f"{Field.V_SET}" == "v_set"
    assert Field.V_SET.value == "v_set"


def test_field_lookup_is_case_insensitive() -> None:
    assert Field("v_set") is Field.V_SET
    assert Field("V_SET") is Field.V_SET
    assert Field("V_Set") is Field.V_SET


def test_field_lookup_rejects_unknown_names() -> None:
    with pytest.raises(ValueError):
        Field("nope")


def test_field_is_only_a_name() -> None:
    """Addresses and codecs belong to the model, not to the field."""
    assert not hasattr(Field.V_SET, "addr")
    assert not hasattr(Field.V_SET, "read")
    assert not hasattr(Field.V_SET, "write")


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


def test_merge_fields_normalizes_keys_and_later_mappings_win() -> None:
    merged = merge_fields({"v_set": 1.0}, {Field.V_SET: 2.0, Field.I: 0.5})
    assert merged == {Field.V_SET: 2.0, Field.I: 0.5}
    assert all(isinstance(field, FieldRef) for field in merged)


def test_merge_fields_without_mappings_is_empty() -> None:
    assert merge_fields() == {}


def test_field_ref_parses_global_and_preset_names() -> None:
    assert FieldRef("v_set").target is Field.V_SET
    assert FieldRef("m1_i_range").target == PresetField(1, PresetParam.I_RANGE)
    assert FieldRef(Field.V) == Field.V
    assert FieldRef(PresetField(1, PresetParam.V)) == "m1_v"

    ref = FieldRef(Field.V)
    assert FieldRef(ref) is ref


def test_field_ref_rejects_bare_preset_param() -> None:
    with pytest.raises(TypeError, match="must be indexed"):
        FieldRef(cast(Any, PresetParam.V))


def test_flatten_fields_accepts_field_refs() -> None:
    ref = FieldRef(Field.V)
    assert list(flatten_fields([ref, [ref]])) == [ref, ref]


def test_merge_fields_accepts_field_ref_keys() -> None:
    ref = FieldRef(Field.V)
    merged = merge_fields({ref: 1.0})
    assert merged[ref] == 1.0
    assert next(iter(merged)) is ref
