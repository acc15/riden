"""Tests for the model table and the scaling each model uses."""

import pytest

from riden.field import Field
from riden.model import Model
from tests.conftest import reader, writer

RANGE_6A = {Field.I_RANGE: 0}


@pytest.mark.parametrize(
    ("code", "model"),
    [
        (60061, Model.RD6006),
        (60062, Model.RD6006),
        (60065, Model.RD6006P),
        (60066, Model.RK6006),
        (60067, Model.RK6006H),
        (60068, Model.RD6006_MAX),
        (60121, Model.RD6012),
        (60122, Model.RK6012),
        (60125, Model.RD6012P),
        (60126, Model.RD6012H),
        (60181, Model.RD6018),
        (60182, Model.RK6018),
        (60185, Model.RD6018P),
        (60241, Model.RD6024),
        (60301, Model.RD6030),
        (42061, Model.RK4206H),
        (61091, Model.RK8009),
    ],
)
def test_find_maps_type_code_to_model(code: int, model: Model) -> None:
    assert Model.find(code) is model


@pytest.mark.parametrize(
    "code",
    [
        60060,
        60063,
        60064,
        60120,
        60123,
        60124,
        60127,
        60180,
        60183,
        60186,
        60190,
        60242,
        60300,
        42060,
        42062,
        61090,
        61092,
    ],
)
def test_find_rejects_neighbouring_codes(code: int) -> None:
    """The table is exact: adjacent IDs are other products, not this model.

    A range-based table used to map 60060 to RD6006 and 60185 to RD6018, which
    scaled every reading of the device at the edge by a factor of ten.
    """
    with pytest.raises(LookupError):
        Model.find(code)


def test_codes_are_disjoint() -> None:
    seen: dict[int, Model] = {}
    for model in Model:
        for code in model.value.codes:
            assert code not in seen, f"{code} claimed by {seen.get(code)} and {model}"
            seen[code] = model


def test_find_rejects_unknown_code() -> None:
    with pytest.raises(LookupError, match="unknown Riden model code: 1"):
        Model.find(1)


@pytest.mark.parametrize(
    ("model", "v_scale", "i_scale", "p_scale", "v_max", "i_max"),
    [
        (Model.RD6006, 100, 1000, 100, 60, 6),
        (Model.RD6006P, 1000, 10000, 1000, 60, 6),
        (Model.RD6006_MAX, 100, 1000, 100, 60, 6),
        (Model.RD6012, 100, 100, 100, 60, 12),
        # RD6012P in its first (6 A) range; the 12 A range is tested separately.
        (Model.RD6012P, 1000, 10000, 1000, 60, 6),
        (Model.RD6012H, 100, 1000, 100, 60, 12),
        (Model.RD6018, 100, 100, 100, 60, 18),
        (Model.RD6018P, 1000, 1000, 1000, 60, 18),
        (Model.RD6024, 100, 100, 100, 60, 24),
        (Model.RD6030, 100, 100, 100, 60, 30),
        (Model.RK6006, 100, 1000, 100, 60, 6),
        (Model.RK6006H, 100, 1000, 100, 60, 6),
        (Model.RK6012, 100, 100, 100, 60, 12),
        (Model.RK6018, 100, 100, 100, 60, 18),
        (Model.RK4206H, 100, 1000, 100, 42, 6),
        (Model.RK8009, 100, 1000, 100, 80, 9),
    ],
)
def test_scaling_follows_id_register_table(
    model: Model,
    v_scale: int,
    i_scale: int,
    p_scale: int,
    v_max: int,
    i_max: int,
) -> None:
    """Scales are 10**decimal places from the vendor's model table."""
    layout = model.value.layout().registers

    assert reader(layout, Field.V)((1000,), {}) == 1000 / v_scale
    assert reader(layout, Field.I)((1000,), RANGE_6A) == 1000 / i_scale
    assert reader(layout, Field.P)((0, 1000), {}) == 1000 / p_scale

    # Setpoints allow v_max + 1 V and i_max + 0.1 A.
    assert writer(layout, Field.V_SET)(v_max + 1, {}) == (
        round((v_max + 1) * v_scale),
    )
    assert writer(layout, Field.I_SET)(i_max + 0.1, RANGE_6A) == (
        round((i_max + 0.1) * i_scale),
    )


def test_rd6012p_has_two_current_ranges() -> None:
    layout = Model.RD6012P.value.layout().registers

    assert reader(layout, Field.I)((1000,), {Field.I_RANGE: 0}) == 0.1
    assert reader(layout, Field.I)((1000,), {Field.I_RANGE: 1}) == 1.0
    assert writer(layout, Field.I_SET)(12.1, {Field.I_RANGE: 1}) == (12100,)
    with pytest.raises(ValueError, match="out of range 0..6.1"):
        writer(layout, Field.I_SET)(12.1, {Field.I_RANGE: 0})
