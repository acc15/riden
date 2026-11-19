"""Tests for the async Riden client on top of a fake tmodbus client."""

import asyncio
from typing import Any, cast

import pytest
from bleak.backends.device import BLEDevice
from tmodbus import AsyncModbusClient

from riden.ble import BleTransport
from riden.field import Field, PresetField, PresetParam
from riden.model import Model
from riden.riden import ModbusClient, Riden
from tests.conftest import FakeClient, Op, Tx


async def test_open_reads_identity_in_one_transaction() -> None:
    client = FakeClient()
    rd = Riden(client)
    assert await rd.open() is rd
    state = rd.state
    assert (state.client, state.id, state.sn, state.fw, state.model) == (
        client,
        60065,
        7,
        12.34,
        Model.RD6006P,
    )
    assert set(state.layout.registers) == set(Field)
    assert client.transactions == [Tx.read(0, 4)]


async def test_open_is_idempotent() -> None:
    client = FakeClient()
    rd = Riden(client)
    assert await rd.open() is rd
    assert await rd.open() is rd
    assert client.transactions == [Tx.read(0, 4)]


async def test_read_single_field() -> None:
    async with Riden(FakeClient()) as rd:
        values = await rd.read(Field.V_SET)
    assert values == {"v_set": 12.5}
    assert values[Field.V_SET] == 12.5


async def test_read_uses_one_contiguous_transaction() -> None:
    client = FakeClient()
    async with Riden(client) as rd:
        await rd.read(Field.V, Field.I)
    assert client.transactions[-1] == Tx.read(10, 2)


async def test_read_calibration_block_in_one_transaction() -> None:
    # The vendor app reads 55-64 as one block; the 12 A pair (63/64) is part
    # of it, not a separate read.
    client = FakeClient()
    async with Riden(client) as rd:
        await rd.read(Field.CAL_V_ZERO, Field.CAL_I12_SCALE)
    assert client.transactions[-1] == Tx.read(55, 10)


async def test_read_accepts_names_and_sequences() -> None:
    async with Riden(FakeClient()) as rd:
        values = await rd.read("v_set", ["sn", Field.EN])
    assert values == {Field.V_SET: 12.5, Field.SN: 7, Field.EN: True}


async def test_read_accepts_generator_expression() -> None:
    client = FakeClient()
    async with Riden(client) as rd:
        values = await rd.read(f for f in (Field.V, Field.I))
    assert values == {Field.V: 12.0, Field.I: 0.5}
    assert client.transactions[-1] == Tx.read(10, 2)


async def test_read_accepts_mixed_iterables() -> None:
    async with Riden(FakeClient()) as rd:
        values = await rd.read(
            "v_set", (name for name in ["sn"]), iter([Field.EN]), ("v_set",)
        )
    assert values == {Field.V_SET: 12.5, Field.SN: 7, Field.EN: True}


async def test_read_accepts_field_string_and_preset_field() -> None:
    preset = PresetField(1, PresetParam.V)
    async with Riden(FakeClient()) as rd:
        values = await rd.read(Field.V_SET, "en", preset)
    assert values == {Field.V_SET: 12.5, Field.EN: True, preset: 0.0}


async def test_read_empty_generator_does_no_io() -> None:
    client = FakeClient()
    async with Riden(client) as rd:
        assert await rd.read(f for f in Field if False) == {}
    assert client.transactions == [Tx.read(0, 4)]


async def test_read_all_readable_fields_via_generator() -> None:
    async with Riden(FakeClient()) as rd:
        layout = rd.state.layout
        readable = [
            field for field in Field if layout.registers[field].read is not None
        ]
        values = await rd.read(field for field in readable)
    assert list(values) == readable


async def test_read_deduplicates_fields() -> None:
    async with Riden(FakeClient()) as rd:
        values = await rd.read(Field.V, "v", Field.V)
    assert list(values) == [Field.V]


async def test_read_nothing_does_no_io() -> None:
    client = FakeClient()
    async with Riden(client) as rd:
        assert await rd.read() == {}
    assert client.transactions == [Tx.read(0, 4)]


async def test_read_rejects_write_only_field() -> None:
    async with Riden(FakeClient()) as rd:
        with pytest.raises(ValueError, match="not readable"):
            await rd.read(Field.CAL_COMMIT)


async def test_read_before_open_fails() -> None:
    rd = Riden(FakeClient())
    with pytest.raises(RuntimeError, match="not initialized"):
        await rd.read(Field.V)


async def test_write_merges_adjacent_fields() -> None:
    client = FakeClient()
    async with Riden(client) as rd:
        await rd.write({Field.V_SET: 12.5, Field.I_SET: 1.0})
    assert client.transactions[-1] == Tx.write(8, [12500, 10000])


async def test_write_accepts_field_keyed_mapping() -> None:
    # A Field-keyed dict keeps the keys checked by the type checker.
    values: dict[Field, Any] = {Field.V_SET: 12.5}
    client = FakeClient()
    async with Riden(client) as rd:
        await rd.write(values)
    assert client.registers[8] == 12500


async def test_write_kwargs_override_mappings() -> None:
    client = FakeClient()
    async with Riden(client) as rd:
        await rd.write({Field.V_SET: 5.0}, v_set=12.5)
    assert client.registers[8] == 12500


async def test_write_separate_fields_use_separate_blocks() -> None:
    client = FakeClient()
    async with Riden(client) as rd:
        await rd.write({Field.V_SET: 12.5})
        await rd.write({Field.EN: True})
    writes = [tx for tx in client.transactions if tx.op is Op.WRITE]
    assert writes == [Tx.write(8, [12500]), Tx.write(18, [1])]


async def test_write_updates_registers() -> None:
    client = FakeClient()
    async with Riden(client) as rd:
        await rd.write({Field.V_SET: 5.0})
    assert client.registers[8] == 5000


async def test_write_accepts_device_voltage_limit() -> None:
    client = FakeClient()
    async with Riden(client) as rd:
        await rd.write({Field.V_SET: 61.0})
    assert client.registers[8] == 61000


async def test_write_rejects_out_of_range_before_any_io() -> None:
    client = FakeClient()
    async with Riden(client) as rd:
        before = list(client.transactions)
        with pytest.raises(
            ValueError, match="field i_set: 15.0 is out of range 0..6.1"
        ):
            await rd.write(v_set=5.0, i_set=15.0)
        assert client.transactions == before
    assert client.registers[8] == 12500


async def test_write_ovp_gets_two_volt_margin() -> None:
    client = FakeClient()
    async with Riden(client) as rd:
        await rd.write({PresetField(0, PresetParam.OVP): 62.0})
    assert client.registers[82] == 62000


async def test_write_leaves_bus_untouched_on_validation_error() -> None:
    client = FakeClient()
    async with Riden(client) as rd:
        with pytest.raises(ValueError, match="fields are not writable: v, i"):
            await rd.write({Field.V_SET: 12.5, Field.V: 1.0, Field.I: 1.0})
    assert [tx for tx in client.transactions if tx.op is Op.WRITE] == []


async def test_write_rejects_out_of_range_registers() -> None:
    client = FakeClient()
    async with Riden(client) as rd:
        with pytest.raises(ValueError, match="out-of-range"):
            await rd.write({Field.LANG: 70000})
    assert [tx for tx in client.transactions if tx.op is Op.WRITE] == []


async def test_write_nothing_does_no_io() -> None:
    client = FakeClient()
    async with Riden(client) as rd:
        await rd.write()
    assert [tx for tx in client.transactions if tx.op is Op.WRITE] == []


async def test_write_before_open_fails() -> None:
    rd = Riden(FakeClient())
    with pytest.raises(RuntimeError, match="not initialized"):
        await rd.write({Field.V_SET: 12.5})


async def test_is_open_reflects_lifecycle() -> None:
    rd = Riden(FakeClient())
    assert not rd.is_open

    await rd.open()
    assert rd.is_open

    await rd.close()
    assert not rd.is_open


async def test_close_closes_client_and_is_idempotent() -> None:
    client = FakeClient()
    rd = Riden(client)
    await rd.open()
    await rd.close()
    await rd.close()
    assert rd._state is None
    with pytest.raises(RuntimeError, match="not initialized"):
        _ = rd.state
    assert client.closed


async def test_open_failure_closes_client() -> None:
    client = FakeClient()
    client.fail_with = RuntimeError("boom")
    rd = Riden(client)
    with pytest.raises(RuntimeError, match="boom"):
        await rd.open()
    assert rd._state is None
    with pytest.raises(RuntimeError, match="not initialized"):
        _ = rd.state
    assert client.closed


async def test_open_unknown_model_fails_and_closes_client() -> None:
    client = FakeClient([0] * 160)
    client.registers[0] = 1
    rd = Riden(client)
    with pytest.raises(LookupError, match="unknown Riden model code: 1"):
        await rd.open()
    assert rd._state is None
    assert client.closed


async def test_context_manager_closes_client() -> None:
    client = FakeClient()
    async with Riden(client) as rd:
        assert rd._state is not None
    assert rd._state is None
    assert client.closed


async def test_identity() -> None:
    async with Riden(FakeClient()) as rd:
        assert rd.identity() == (
            "model=Model.RD6006P type=60065 sn=00000007 fw=12.34"
        )


async def test_status() -> None:
    async with Riden(FakeClient()) as rd:
        status = await rd.status()
    assert "model=Model.RD6006P type=60065 sn=00000007 fw=12.34" in status
    assert "input:      24.00V" in status
    assert "set:        12.500 V, 1.000 A" in status
    assert "output:     12.000 V, 0.500 A, 60.000 W" in status
    assert "enabled:    True" in status
    assert "mode:       0" in status
    assert "protection: 0" in status
    assert "temp:       0 C" in status


# RD6012P: current is scaled by the selected range, per output and per preset.


async def rd6012p() -> tuple[Riden, FakeClient]:
    """Return an opened RD6012P client on a zeroed register file."""
    client = FakeClient([0] * 160)
    client.registers[0] = 60125
    rd = Riden(client)
    await rd.open()
    client.transactions.clear()
    return rd, client


async def test_rd6012p_read_uses_selected_range() -> None:
    rd, client = await rd6012p()
    client.registers[11] = 1234

    client.registers[20] = 0
    assert (await rd.read(Field.I))[Field.I] == pytest.approx(0.1234)

    client.registers[20] = 1
    assert (await rd.read(Field.I))[Field.I] == pytest.approx(1.234)


async def test_rd6012p_read_returns_only_requested_fields() -> None:
    rd, client = await rd6012p()
    client.registers[11] = 5000  # I = 0.5 A in the 6 A range
    client.registers[20] = 0

    values = await rd.read("i")

    # I_RANGE is read as a dependency to scale I, but is not returned.
    assert client.transactions == [Tx.read(11, 10)]
    assert list(values) == [Field.I]
    assert values["i"] == pytest.approx(0.5)
    assert values[Field.I] == pytest.approx(0.5)


async def test_rd6012p_reads_range_and_current_in_one_transaction() -> None:
    rd, client = await rd6012p()
    await rd.read(Field.I)
    assert client.transactions == [Tx.read(11, 10)]


# Supplying known dependencies with deps=.


async def test_read_deps_use_known_current_range_without_reading_it() -> None:
    rd, client = await rd6012p()
    client.registers[11] = 5000
    client.registers[20] = 1  # the device is on the 12 A range

    values = await rd.read("i", deps={"i_range": 0})

    assert values["i"] == pytest.approx(0.5)  # decoded with the 6 A scale
    assert client.transactions == [Tx.read(11, 1)]


async def test_read_deps_accept_field_keys() -> None:
    rd, client = await rd6012p()
    client.registers[11] = 5000
    client.registers[20] = 0

    values = await rd.read("i", deps={Field.I_RANGE: 1})

    assert values["i"] == pytest.approx(5.0)  # decoded with the 12 A scale
    assert client.transactions == [Tx.read(11, 1)]


async def test_read_deps_accept_mixed_key_forms() -> None:
    rd, client = await rd6012p()
    client.registers[11] = 5000
    client.registers[86] = 5000
    client.registers[20] = 1
    client.registers[89] = 1

    values = await rd.read(
        "i", "m1_i", deps={"i_range": 0, PresetField(1, PresetParam.I_RANGE): 0}
    )

    assert values["i"] == pytest.approx(0.5)
    assert values["m1_i"] == pytest.approx(0.5)
    assert client.transactions == [Tx.read(11, 76)]


async def test_read_deps_keep_the_same_result_shape() -> None:
    rd, client = await rd6012p()
    client.registers[9] = 10000
    client.registers[11] = 5000

    full = await rd.read("i_set", "i", "i_range")
    assert client.transactions == [Tx.read(9, 12)]

    known = await rd.read(
        "i_set", "i", "i_range", deps={"i_range": full["i_range"]}
    )
    assert client.transactions == [Tx.read(9, 12), Tx.read(9, 3)]
    assert list(known) == list(full) == ["i_set", "i", "i_range"]
    assert known == full


async def test_read_deps_can_supply_requested_fields() -> None:
    rd, client = await rd6012p()

    values = await rd.read("i_range", deps={"i_range": 1})

    assert values == {"i_range": 1}
    assert client.transactions == []


async def test_read_deps_can_supply_a_field_that_is_not_readable() -> None:
    # deps are known values, not device reads: readability is irrelevant.
    async with Riden(FakeClient()) as rd:
        values = await rd.read("cal_commit", deps={"cal_commit": 5377})
    assert values == {"cal_commit": 5377}


async def test_read_deps_ignore_values_that_are_not_needed() -> None:
    client = FakeClient()
    async with Riden(client) as rd:
        values = await rd.read("v", deps={"i_range": 1})
    assert values == {"v": 12.0}
    assert client.transactions[-1] == Tx.read(10, 1)


async def test_read_deps_reject_unknown_field_names() -> None:
    async with Riden(FakeClient()) as rd:
        with pytest.raises(ValueError, match="not a valid Field"):
            await rd.read("v", deps={"i_rage": 0})


# Read-only model metadata.


async def test_read_metadata_does_not_touch_the_bus() -> None:
    client = FakeClient()
    async with Riden(client) as rd:
        before = list(client.transactions)
        values = await rd.read(
            "v_max",
            "v_scale",
            "v_tolerance",
            "ovp_tolerance",
            "i_max",
            "i_scale",
            "i_tolerance",
            "ocp_tolerance",
            "p_max",
            "p_scale",
        )
        assert client.transactions == before
    assert values == {
        "v_max": 60,
        "v_scale": 1000,
        "v_tolerance": 1.0,
        "ovp_tolerance": 2.0,
        "i_max": 6,
        "i_scale": 10000,
        "i_tolerance": 0.1,
        "ocp_tolerance": 0.2,
        "p_max": 360,
        "p_scale": 1000,
    }


async def test_rd6012p_reads_metadata_with_one_range_read() -> None:
    rd, client = await rd6012p()

    values = await rd.read("i_max", "i_scale")

    assert client.transactions == [Tx.read(20, 1)]
    assert values == {"i_max": 6, "i_scale": 10000}


async def test_rd6012p_preset_metadata_follows_preset_range() -> None:
    rd, client = await rd6012p()
    client.registers[89] = 1  # M1 in the 12 A range

    values = await rd.read("m1_i_max", "m1_i_scale")

    assert client.transactions == [Tx.read(89, 1)]
    assert values == {"m1_i_max": 12, "m1_i_scale": 1000}


async def test_read_i_with_known_scale_skips_range() -> None:
    rd, client = await rd6012p()
    client.registers[11] = 5000

    values = await rd.read("i", deps={"i_scale": 1000})

    assert values["i"] == pytest.approx(5.0)
    assert client.transactions == [Tx.read(11, 1)]


async def test_rd6012p_write_reads_missing_range_first() -> None:
    rd, client = await rd6012p()
    await rd.write(i_set=1.0)
    assert client.transactions == [Tx.read(20, 1), Tx.write(9, [10000])]


async def test_rd6012p_write_uses_supplied_range_without_reading() -> None:
    rd, client = await rd6012p()
    await rd.write(i_set=1.0, i_range=1)
    assert client.transactions == [Tx.write(20, [1]), Tx.write(9, [1000])]


async def test_rd6012p_full_preset_is_one_transaction() -> None:
    rd, client = await rd6012p()
    await rd.write(m1_v=1, m1_i=1, m1_ovp=60, m1_ocp=5, m1_i_range=0)
    assert client.transactions == [Tx.write(85, [1000, 10000, 60000, 50000, 0])]


async def test_rd6012p_preset_reads_its_own_range() -> None:
    rd, client = await rd6012p()
    await rd.write(m1_i=1.0)
    assert client.transactions == [Tx.read(89, 1), Tx.write(86, [10000])]


async def test_rd6012p_rejects_value_invalid_for_measured_range_before_writing() -> None:
    rd, client = await rd6012p()
    client.registers[20] = 0
    with pytest.raises(ValueError, match="out of range 0..6.1"):
        await rd.write(i_set=12.0)
    assert [tx for tx in client.transactions if tx.op is Op.WRITE] == []


# write() with known dependencies.


async def test_write_deps_use_known_range_without_reading_or_writing_it() -> None:
    rd, client = await rd6012p()
    client.registers[20] = 1  # the device is on the 12 A range

    await rd.write(i_set=1.0, deps={"i_range": 0})

    assert client.transactions == [Tx.write(9, [10000])]
    assert client.registers[20] == 1


async def test_write_deps_accept_field_keys() -> None:
    rd, client = await rd6012p()

    await rd.write(i_set=1.0, deps={Field.I_RANGE: 1})

    assert client.transactions == [Tx.write(9, [1000])]


async def test_write_deps_are_overridden_by_written_fields() -> None:
    rd, client = await rd6012p()

    await rd.write(i_set=1.0, i_range=1, deps={"i_range": 0})

    assert client.transactions == [Tx.write(20, [1]), Tx.write(9, [1000])]


async def test_write_deps_ignore_values_that_are_not_needed() -> None:
    client = FakeClient()
    async with Riden(client) as rd:
        await rd.write(v_set=5.0, deps={"i_range": 0})
    assert client.transactions[-1] == Tx.write(8, [5000])
    assert [tx for tx in client.transactions if tx.op is Op.READ] == [Tx.read(0, 4)]


async def test_write_deps_reject_unknown_field_names() -> None:
    client = FakeClient()
    async with Riden(client) as rd:
        with pytest.raises(ValueError, match="not a valid Field"):
            await rd.write(v_set=5.0, deps={"i_rage": 0})
    assert [tx for tx in client.transactions if tx.op is Op.WRITE] == []


async def test_write_deps_supply_current_scale_and_max() -> None:
    rd, client = await rd6012p()

    await rd.write(
        i_set=1.0,
        deps={"i_scale": 1000, "i_max": 12, "i_tolerance": 0.1},
    )

    assert client.transactions == [Tx.write(9, [1000])]


async def test_write_deps_read_only_missing_current_max() -> None:
    rd, client = await rd6012p()
    client.registers[20] = 1  # the 12 A range is needed only for the max

    await rd.write(i_set=1.0, deps={"i_scale": 10000})

    assert client.transactions == [Tx.read(20, 1), Tx.write(9, [10000])]


async def test_write_deps_resolve_missing_max_from_written_range() -> None:
    rd, client = await rd6012p()

    await rd.write(i_set=1.0, i_range=1, deps={"i_scale": 10000})

    assert client.transactions == [Tx.write(20, [1]), Tx.write(9, [10000])]


async def test_write_deps_can_override_tolerance() -> None:
    client = FakeClient()
    async with Riden(client) as rd:
        await rd.write(v_set=62.0, deps={"v_tolerance": 2.0})
    assert client.registers[8] == 62000
    assert [tx for tx in client.transactions if tx.op is Op.WRITE] == [
        Tx.write(8, [62000])
    ]


async def test_metadata_fields_are_read_only() -> None:
    async with Riden(FakeClient()) as rd:
        with pytest.raises(ValueError, match="fields are not writable: v_max"):
            await rd.write(v_max=61)


# Virtual fields on models without a selectable current range.


async def test_base_preset_range_is_virtual() -> None:
    client = FakeClient()
    async with Riden(client) as rd:
        before = list(client.transactions)
        assert await rd.read(PresetField(1, PresetParam.I_RANGE)) == {PresetField(1, PresetParam.I_RANGE): False}
        assert client.transactions == before

        await rd.write(m1_i_range=1)
        assert [tx for tx in client.transactions if tx.op is Op.WRITE] == []


async def test_base_preset_ignores_virtual_range() -> None:
    client = FakeClient()
    async with Riden(client) as rd:
        await rd.write(m1_i=1.0, m1_i_range=1)
    assert client.transactions[-1] == Tx.write(85, [10000])


async def test_connect_accepts_a_prebuilt_client() -> None:
    client = FakeClient()
    async with Riden.connect(client) as rd:
        assert rd.state.client is client


async def test_multiple_clients_can_run_concurrently() -> None:
    master, follower1, follower2 = FakeClient(), FakeClient(), FakeClient()
    async with (
        Riden(master) as rd1,
        Riden(follower1) as rd2,
        Riden(follower2) as rd3,
    ):
        values = await rd1.read("v", "i")
        await asyncio.gather(
            rd2.write({"v_set": values["v"], "i_set": values["i"]}),
            rd3.write({"v_set": values["v"], "i_set": values["i"]}),
        )

    assert follower1.registers[8] == 12000
    assert follower1.registers[9] == 5000
    assert follower2.registers[8] == 12000
    assert follower2.registers[9] == 5000


async def test_connect_failure_disconnects_client() -> None:
    client = FakeClient()
    client.connect_error = RuntimeError("no link")
    rd = Riden(client)
    with pytest.raises(RuntimeError, match="no link"):
        await rd.open()
    assert rd._state is None
    assert client.closed


async def test_reopen_after_close() -> None:
    client = FakeClient()
    rd = Riden(client)
    await rd.open()
    await rd.close()
    assert not client.connected
    await rd.open()
    values = await rd.read("v")
    assert client.connected
    assert values["v"] == 12.0


def test_connect_returns_a_prebuilt_client() -> None:
    fake = cast(ModbusClient, object())
    assert Riden.connect(fake)._client is fake


def test_connect_builds_ble_without_io() -> None:
    client = Riden.connect("bt://AA:BB:CC:DD:EE:FF", timeout=0.5)._client
    assert isinstance(client, AsyncModbusClient)


def test_connect_builds_serial_without_io() -> None:
    client = Riden.connect("/dev/ttyUSB0", baudrate=9600, timeout=0.5)._client
    assert isinstance(client, AsyncModbusClient)


def test_connect_accepts_a_bledevice() -> None:
    device = BLEDevice(
        "AA:BB:CC:DD:EE:FF",
        "RK6006",
        {"path": "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF", "props": {}},
    )
    client = Riden.connect(device, timeout=0.5, connect_timeout=3)._client
    assert isinstance(client, AsyncModbusClient)


def test_connect_wraps_a_prebuilt_ble_transport() -> None:
    transport = BleTransport("AA:BB:CC:DD:EE:FF", timeout=0.5)
    client = Riden.connect(transport)._client
    assert isinstance(client, AsyncModbusClient)
