"""Tests for the model table and its clamps."""

import pytest

from riden.model import Model


@pytest.mark.parametrize(
    ("code", "model"),
    [
        (60060, Model.RD6006),
        (60064, Model.RD6006),
        (60065, Model.RD6006P),
        (60066, Model.RK6006),
        (60120, Model.RD6012),
        (60125, Model.RD6012P),
        (60180, Model.RD6018),
        (60241, Model.RD6024),
    ],
)
def test_find_maps_type_code_to_model(code: int, model: Model) -> None:
    assert Model.find(code) is model


def test_find_rejects_unknown_code() -> None:
    with pytest.raises(LookupError, match="unknown Riden model code: 1"):
        Model.find(1)


def test_rd6012p_uses_12a_range() -> None:
    assert (Model.RD6012P.value.i_scale, Model.RD6012P.value.i_max) == (1000, 12)
    assert Model.RD6012P.value.i_clamp(12, 0) == 12000


def test_power_scales() -> None:
    assert Model.RD6006P.value.p_scale == 1000
    assert Model.RD6012P.value.p_scale == 1000
    assert Model.RD6006.value.p_scale == 100
    assert Model.RD6012.value.p_scale == 100


def test_scales_and_limits() -> None:
    assert (Model.RD6006P.value.v_scale, Model.RD6006P.value.i_scale) == (1000, 10000)
    assert (Model.RD6006.value.v_scale, Model.RD6006.value.i_scale) == (100, 1000)
    assert Model.RD6006P.value.v_max == 60
    assert Model.RD6006P.value.i_max == 6


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
