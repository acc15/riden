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


def test_find_falls_back_to_first_model() -> None:
    assert Model.find(1) is Model.RD6006


def test_scales_and_limits() -> None:
    assert (Model.RD6006P.v_scale, Model.RD6006P.i_scale) == (1000, 10000)
    assert (Model.RD6006.v_scale, Model.RD6006.i_scale) == (100, 1000)
    assert Model.RD6006P.v_max == 60
    assert Model.RD6006P.i_max == 6


def test_voltage_clamp() -> None:
    assert Model.RD6006P.v_clamp(12.5) == 12500
    assert Model.RD6006P.v_clamp(-1) == 0
    assert Model.RD6006P.v_clamp(100) == 60000
    assert Model.RD6006P.v_clamp(61.5, off=2) == 61500
    assert Model.RD6006P.v_clamp(100, off=2) == 62000


def test_current_clamp() -> None:
    assert Model.RD6006P.i_clamp(1.0) == 10000
    assert Model.RD6006P.i_clamp(-1) == 0
    assert Model.RD6006P.i_clamp(100) == 60000
    assert Model.RD6018.i_clamp(19, off=2) == 1900
    assert Model.RD6018.i_clamp(100, off=2) == 2000
