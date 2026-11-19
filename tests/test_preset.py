"""Tests for the preset convenience object."""

from typing import Any, cast

import pytest

from riden import Field, Preset, PresetField, PresetParam, Riden
from tests.conftest import FakeClient


def test_preset_iterates_all_fields() -> None:
    assert list(Preset(1)) == [PresetField(1, param) for param in PresetParam]


def test_preset_only_selects_params() -> None:
    assert Preset(1).only("v", PresetParam.I) == (
        PresetField(1, PresetParam.V),
        PresetField(1, PresetParam.I),
    )
    assert Preset(2).only() == tuple(
        PresetField(2, param) for param in PresetParam
    )


def test_preset_params_maps_names_and_merges() -> None:
    preset = Preset(1)

    assert preset.params({"v": 1.0, "i": 2.0}, ocp=3.0) == {
        PresetField(1, PresetParam.V): 1.0,
        PresetField(1, PresetParam.I): 2.0,
        PresetField(1, PresetParam.OCP): 3.0,
    }


def test_preset_params_accepts_enum_keys_and_later_values_win() -> None:
    preset = Preset(2)

    assert preset.params({PresetParam.V: 1.0}, {PresetParam.V: 2.0}) == {
        PresetField(2, PresetParam.V): 2.0,
    }


def test_preset_params_rejects_unknown_names() -> None:
    with pytest.raises(ValueError):
        Preset(1).params(nope=1.0)


def test_preset_params_rejects_concrete_field() -> None:
    with pytest.raises(TypeError, match="already concrete"):
        Preset(1).params(cast(Any, {PresetField(5, "v"): 2.0}))


def test_preset_params_rejects_global_field() -> None:
    with pytest.raises(TypeError, match="global Field"):
        Preset(1).params(cast(Any, {Field.V: 1.0}))


async def test_read_preset_reads_all_fields() -> None:
    async with Riden(FakeClient()) as rd:
        values = await rd.read(Preset(1))

    assert set(values) == {f"m1_{param.value}" for param in PresetParam}


async def test_read_preset_can_select_fields() -> None:
    async with Riden(FakeClient()) as rd:
        values = await rd.read(Preset(1).only("v", "i"))

    assert set(values) == {"m1_v", "m1_i"}


async def test_write_preset_params() -> None:
    client = FakeClient()
    async with Riden(client) as rd:
        await rd.write(Preset(1).params(v=1.0, i=0.5, ocp=1.0))

    assert client.registers[84] == 1000
    assert client.registers[85] == 5000
    assert client.registers[87] == 10000
