"""Tests for the model table and its clamps."""

import pytest

from riden.model import Model


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
        (Model.RD6012P, 1000, 1000, 1000, 60, 12),
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
def test_scales_follow_id_register_table(
    model: Model,
    v_scale: int,
    i_scale: int,
    p_scale: int,
    v_max: int,
    i_max: int,
) -> None:
    """Scales are 10**decimal places from the vendor's model table."""
    spec = model.value
    assert (spec.v_scale, spec.i_scale, spec.p_scale) == (v_scale, i_scale, p_scale)
    assert (spec.v_max, spec.i_max) == (v_max, i_max)


def test_rd6012p_uses_12a_range() -> None:
    assert (Model.RD6012P.value.i_scale, Model.RD6012P.value.i_max) == (1000, 12)
    assert Model.RD6012P.value.i_clamp(12, 0) == 12000


def test_voltage_clamp() -> None:
    spec = Model.RD6006P.value
    assert spec.v_clamp(12.5, 0) == 12500
    assert spec.v_clamp(0, 0) == 0
    assert spec.v_clamp(60, 0) == 60000
    assert spec.v_clamp(62, 2) == 62000
    for v, off in ((-1, 0), (60.001, 0), (62.001, 2)):
        with pytest.raises(ValueError, match="out of range"):
            spec.v_clamp(v, off)


def test_current_clamp() -> None:
    assert Model.RD6006P.value.i_clamp(1.0, 0) == 10000
    assert Model.RD6006P.value.i_clamp(6.2, 0.2) == 62000
    assert Model.RD6018.value.i_clamp(18.2, 0.2) == 1820
    for spec, v, off in ((Model.RD6006P.value, -1, 0), (Model.RD6006P.value, 6.0001, 0), (Model.RD6018.value, 18.21, 0.2)):
        with pytest.raises(ValueError, match="out of range"):
            spec.i_clamp(v, off)


def test_clamp_accepts_float_sums_at_limit() -> None:
    # 6 + 0.2 and 12 + 0.1 are not exact in binary; the raw check must still pass.
    assert Model.RK6006.value.i_clamp(6.2, 0.2) == 6200
    assert Model.RD6012.value.i_clamp(12.1, 0.1) == 1210
