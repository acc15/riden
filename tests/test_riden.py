"""Tests for the Riden client on top of a fake session."""

from typing import Any

import pytest

from riden.field import Field
from riden.model import Model
from riden.riden import Riden
from riden.transport.transport import Op, Tx
from tests.conftest import MemorySession, MemoryTransport


@pytest.fixture
def session() -> MemorySession:
    return MemorySession()


@pytest.fixture
def transport(session: MemorySession) -> MemoryTransport:
    return MemoryTransport(session)


def test_open_reads_identity_in_one_transaction(
    transport: MemoryTransport, session: MemorySession
) -> None:
    rd = Riden(transport).open()
    state = rd.require_state()
    assert (state.session, state.id, state.sn, state.fw, state.model) == (
        session, 60065, 7, 12.34, Model.RD6006P
    )
    assert set(state.layout.registers) == set(Field)
    assert [tx for tx in session.transactions] == [Tx.read(0, 4)]


def test_open_is_idempotent(transport: MemoryTransport) -> None:
    rd = Riden(transport)
    assert rd.open() is rd
    assert rd.open() is rd
    assert transport.opens == 1


def test_read_single_field(transport: MemoryTransport) -> None:
    with Riden(transport) as rd:
        values = rd.read(Field.V_SET)
    assert values == {"v_set": 12.5}
    assert values[Field.V_SET] == 12.5


def test_read_uses_one_contiguous_transaction(
    transport: MemoryTransport, session: MemorySession
) -> None:
    with Riden(transport) as rd:
        rd.read(Field.V, Field.I)
    assert session.transactions[-1] == Tx.read(10, 2)


def test_read_calibration_block_in_one_transaction(
    transport: MemoryTransport, session: MemorySession
) -> None:
    # The vendor app reads 55-64 as one block; the 12 A pair (63/64) is part
    # of it, not a separate read.
    with Riden(transport) as rd:
        rd.read(Field.CAL_V_ZERO, Field.CAL_I12_SCALE)
    assert session.transactions[-1] == Tx.read(55, 10)


def test_read_accepts_names_and_sequences(transport: MemoryTransport) -> None:
    with Riden(transport) as rd:
        values = rd.read("v_set", ["sn", Field.EN])
    assert values == {Field.V_SET: 12.5, Field.SN: 7, Field.EN: True}


def test_read_accepts_generator_expression(
    transport: MemoryTransport, session: MemorySession
) -> None:
    with Riden(transport) as rd:
        values = rd.read(f for f in (Field.V, Field.I))
    assert values == {Field.V: 12.0, Field.I: 0.5}
    assert session.transactions[-1] == Tx.read(10, 2)


def test_read_accepts_mixed_iterables(transport: MemoryTransport) -> None:
    with Riden(transport) as rd:
        values = rd.read(
            "v_set", (name for name in ["sn"]), iter([Field.EN]), ("v_set",)
        )
    assert values == {Field.V_SET: 12.5, Field.SN: 7, Field.EN: True}


def test_read_empty_generator_does_no_io(
    transport: MemoryTransport, session: MemorySession
) -> None:
    with Riden(transport) as rd:
        assert rd.read(f for f in Field if False) == {}
    assert session.transactions == [Tx.read(0, 4)]


def test_read_all_readable_fields_via_generator(transport: MemoryTransport) -> None:
    with Riden(transport) as rd:
        layout = rd.require_state().layout
        readable = [field for field in Field if layout.registers[field].read is not None]
        values = rd.read(field for field in readable)
    assert list(values) == readable


def test_read_deduplicates_fields(transport: MemoryTransport) -> None:
    with Riden(transport) as rd:
        values = rd.read(Field.V, "v", Field.V)
    assert list(values) == [Field.V]


def test_read_nothing_does_no_io(
    transport: MemoryTransport, session: MemorySession
) -> None:
    with Riden(transport) as rd:
        assert rd.read() == {}
    assert session.transactions == [Tx.read(0, 4)]


def test_read_rejects_write_only_field(transport: MemoryTransport) -> None:
    with Riden(transport) as rd, pytest.raises(ValueError, match="not readable"):
        rd.read(Field.CAL_COMMIT)


def test_read_before_open_fails(transport: MemoryTransport) -> None:
    with pytest.raises(RuntimeError, match="not initialized"):
        Riden(transport).read(Field.V)


def test_write_merges_adjacent_fields(
    transport: MemoryTransport, session: MemorySession
) -> None:
    with Riden(transport) as rd:
        rd.write({Field.V_SET: 12.5, Field.I_SET: 1.0})
    assert session.transactions[-1] == Tx.write(8, [12500, 10000])


def test_write_accepts_field_keyed_mapping(
    transport: MemoryTransport, session: MemorySession
) -> None:
    # A Field-keyed dict keeps the keys checked by the type checker.
    values: dict[Field, Any] = {Field.V_SET: 12.5}
    with Riden(transport) as rd:
        rd.write(values)
    assert session.registers[8] == 12500


def test_write_kwargs_override_mappings(
    transport: MemoryTransport, session: MemorySession
) -> None:
    with Riden(transport) as rd:
        rd.write({Field.V_SET: 5.0}, v_set=12.5)
    assert session.registers[8] == 12500


def test_write_separate_fields_use_separate_blocks(
    transport: MemoryTransport, session: MemorySession
) -> None:
    with Riden(transport) as rd:
        rd.write({Field.V_SET: 12.5})
        rd.write({Field.EN: True})
    writes = [tx for tx in session.transactions if tx.op is Op.WRITE]
    assert writes == [Tx.write(8, [12500]), Tx.write(18, [1])]


def test_write_updates_registers(
    transport: MemoryTransport, session: MemorySession
) -> None:
    with Riden(transport) as rd:
        rd.write({Field.V_SET: 5.0})
    assert session.registers[8] == 5000


def test_write_accepts_device_voltage_limit(
    transport: MemoryTransport, session: MemorySession
) -> None:
    with Riden(transport) as rd:
        rd.write({Field.V_SET: 61.0})
    assert session.registers[8] == 61000


def test_write_rejects_out_of_range_before_any_io(
    transport: MemoryTransport, session: MemorySession
) -> None:
    with Riden(transport) as rd:
        before = list(session.transactions)
        with pytest.raises(ValueError, match="field i_set: 15.0 is out of range 0..6.1"):
            rd.write(v_set=5.0, i_set=15.0)
        assert session.transactions == before
    assert session.registers[8] == 12500


def test_write_ovp_gets_two_volt_margin(
    transport: MemoryTransport, session: MemorySession
) -> None:
    with Riden(transport) as rd:
        rd.write({Field.M0_OVP: 62.0})
    assert session.registers[82] == 62000


def test_write_leaves_bus_untouched_on_validation_error(
    transport: MemoryTransport, session: MemorySession
) -> None:
    with Riden(transport) as rd, pytest.raises(
        ValueError, match="fields are not writable: v, i"
    ):
        rd.write({Field.V_SET: 12.5, Field.V: 1.0, Field.I: 1.0})
    assert [tx for tx in session.transactions if tx.op is Op.WRITE] == []


def test_write_rejects_out_of_range_registers(
    transport: MemoryTransport, session: MemorySession
) -> None:
    with Riden(transport) as rd, pytest.raises(ValueError, match="out-of-range"):
        rd.write({Field.LANG: 70000})
    assert [tx for tx in session.transactions if tx.op is Op.WRITE] == []


def test_write_nothing_does_no_io(
    transport: MemoryTransport, session: MemorySession
) -> None:
    with Riden(transport) as rd:
        rd.write()
    assert [tx for tx in session.transactions if tx.op is Op.WRITE] == []


def test_write_before_open_fails(transport: MemoryTransport) -> None:
    with pytest.raises(RuntimeError, match="not initialized"):
        Riden(transport).write({Field.V_SET: 12.5})


def test_close_closes_session_and_is_idempotent(
    transport: MemoryTransport, session: MemorySession
) -> None:
    rd = Riden(transport).open()
    rd.close()
    rd.close()
    assert rd.state is None
    with pytest.raises(RuntimeError, match="not initialized"):
        _ = rd.require_state()
    assert session.closed


def test_open_failure_closes_session(
    transport: MemoryTransport, session: MemorySession
) -> None:
    session.fail_with = RuntimeError("boom")
    rd = Riden(transport)
    with pytest.raises(RuntimeError, match="boom"):
        rd.open()
    assert rd.state is None
    with pytest.raises(RuntimeError, match="not initialized"):
        _ = rd.require_state()
    assert session.closed


def test_open_unknown_model_fails_and_closes_session(
    transport: MemoryTransport, session: MemorySession
) -> None:
    session.registers[0] = 1
    rd = Riden(transport)
    with pytest.raises(LookupError, match="unknown Riden model code: 1"):
        rd.open()
    assert rd.state is None
    assert session.closed


def test_context_manager_closes_session(
    transport: MemoryTransport, session: MemorySession
) -> None:
    with Riden(transport) as rd:
        assert rd.state is not None
    assert rd.state is None
    assert session.closed


def test_identity(transport: MemoryTransport) -> None:
    with Riden(transport) as rd:
        assert rd.identity() == (
            "model=Model.RD6006P type=60065 sn=00000007 fw=12.34 input=24.00V"
        )


def test_status(transport: MemoryTransport) -> None:
    with Riden(transport) as rd:
        status = rd.status()
    assert "model=Model.RD6006P type=60065 sn=00000007 fw=12.34" in status
    assert "set:      12.500 V, 1.000 A" in status
    assert "output:   12.000 V, 0.500 A, 60.000 W" in status
    assert "enabled:  True" in status


# RD6012P: current is scaled by the selected range, per output and per preset.


def rd6012p() -> tuple[Riden, MemorySession]:
    """Return an opened RD6012P client on a zeroed register file."""
    session = MemorySession([0] * 160)
    session.registers[0] = 60125
    rd = Riden(MemoryTransport(session)).open()
    session.transactions.clear()
    return rd, session


def test_rd6012p_read_uses_selected_range() -> None:
    rd, session = rd6012p()
    session.registers[11] = 1234

    session.registers[20] = 0
    assert rd.read(Field.I)[Field.I] == pytest.approx(0.1234)

    session.registers[20] = 1
    assert rd.read(Field.I)[Field.I] == pytest.approx(1.234)


def test_rd6012p_read_returns_only_requested_fields() -> None:
    rd, session = rd6012p()
    session.registers[11] = 5000  # I = 0.5 A in the 6 A range
    session.registers[20] = 0

    values = rd.read("i")

    # I_RANGE is read as a dependency to scale I, but is not returned.
    assert session.transactions == [Tx.read(11, 10)]
    assert list(values) == [Field.I]
    assert values["i"] == pytest.approx(0.5)
    assert values[Field.I] == pytest.approx(0.5)


def test_rd6012p_reads_range_and_current_in_one_transaction() -> None:
    rd, session = rd6012p()
    rd.read(Field.I)
    assert session.transactions == [Tx.read(11, 10)]


def test_rd6012p_write_reads_missing_range_first() -> None:
    rd, session = rd6012p()
    rd.write(i_set=1.0)
    assert session.transactions == [Tx.read(20, 1), Tx.write(9, [10000])]


def test_rd6012p_write_uses_supplied_range_without_reading() -> None:
    rd, session = rd6012p()
    rd.write(i_set=1.0, i_range=1)
    assert session.transactions == [Tx.write(20, [1]), Tx.write(9, [1000])]


def test_rd6012p_full_preset_is_one_transaction() -> None:
    rd, session = rd6012p()
    rd.write(m1_v=1, m1_i=1, m1_ovp=60, m1_ocp=5, m1_i_range=0)
    assert session.transactions == [Tx.write(85, [1000, 10000, 60000, 50000, 0])]


def test_rd6012p_preset_reads_its_own_range() -> None:
    rd, session = rd6012p()
    rd.write(m1_i=1.0)
    assert session.transactions == [Tx.read(89, 1), Tx.write(86, [10000])]


def test_rd6012p_rejects_value_invalid_for_measured_range_before_writing() -> None:
    rd, session = rd6012p()
    session.registers[20] = 0
    with pytest.raises(ValueError, match="out of range 0..6.1"):
        rd.write(i_set=12.0)
    assert [tx for tx in session.transactions if tx.op is Op.WRITE] == []


# Virtual fields on models without a selectable current range.


def test_base_preset_range_is_virtual(
    transport: MemoryTransport, session: MemorySession
) -> None:
    with Riden(transport) as rd:
        before = list(session.transactions)
        assert rd.read(Field.M1_I_RANGE) == {Field.M1_I_RANGE: False}
        assert session.transactions == before

        rd.write(m1_i_range=1)
        assert [tx for tx in session.transactions if tx.op is Op.WRITE] == []


def test_base_preset_ignores_virtual_range(
    transport: MemoryTransport, session: MemorySession
) -> None:
    with Riden(transport) as rd:
        rd.write(m1_i=1.0, m1_i_range=1)
    assert session.transactions[-1] == Tx.write(85, [10000])
