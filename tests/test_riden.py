"""Tests for the Riden client on top of a fake session."""

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
    assert (rd.id, rd.sn, rd.fw) == (60065, 7, 12.34)
    assert rd.model is Model.RD6006P
    assert [tx for tx in session.transactions] == [Tx.read(0, 4)]


def test_open_is_idempotent(transport: MemoryTransport) -> None:
    rd = Riden(transport)
    assert rd.open() is rd
    assert rd.open() is rd
    assert transport.opens == 1


def test_read_single_field(transport: MemoryTransport) -> None:
    with Riden(transport) as rd:
        assert rd.read(Field.V_SET) == {Field.V_SET: 12.5}


def test_read_uses_one_contiguous_transaction(
    transport: MemoryTransport, session: MemorySession
) -> None:
    with Riden(transport) as rd:
        rd.read(Field.V, Field.I)
    assert session.transactions[-1] == Tx.read(10, 2)


def test_read_accepts_names_and_sequences(transport: MemoryTransport) -> None:
    with Riden(transport) as rd:
        values = rd.read("v_set", ["sn", Field.EN])
    assert values == {Field.V_SET: 12.5, Field.SN: 7, Field.EN: True}


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
    with pytest.raises(RuntimeError, match="not open"):
        Riden(transport).read(Field.V)


def test_write_merges_adjacent_fields(
    transport: MemoryTransport, session: MemorySession
) -> None:
    with Riden(transport) as rd:
        rd.write({Field.V_SET: 12.5, Field.I_SET: 1.0})
    assert session.transactions[-1] == Tx.write(8, [12500, 10000])


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


def test_write_clamps_to_model_limits(
    transport: MemoryTransport, session: MemorySession
) -> None:
    with Riden(transport) as rd:
        rd.write({Field.V_SET: 100.0})
    assert session.registers[8] == 60000


def test_write_ovp_gets_two_volt_margin(
    transport: MemoryTransport, session: MemorySession
) -> None:
    with Riden(transport) as rd:
        rd.write({Field.M0_OVP: 62.0})
    assert session.registers[82] == 62000


def test_write_leaves_bus_untouched_on_validation_error(
    transport: MemoryTransport, session: MemorySession
) -> None:
    with Riden(transport) as rd, pytest.raises(ValueError, match="not writable"):
        rd.write({Field.V_SET: 12.5, Field.V: 1.0})
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
    with pytest.raises(RuntimeError, match="not open"):
        Riden(transport).write({Field.V_SET: 12.5})


def test_close_closes_session_and_is_idempotent(
    transport: MemoryTransport, session: MemorySession
) -> None:
    rd = Riden(transport).open()
    rd.close()
    rd.close()
    assert rd.session is None
    assert session.closed


def test_open_failure_closes_session(
    transport: MemoryTransport, session: MemorySession
) -> None:
    session.fail_with = RuntimeError("boom")
    rd = Riden(transport)
    with pytest.raises(RuntimeError, match="boom"):
        rd.open()
    assert rd.session is None
    assert session.closed


def test_context_manager_closes_session(
    transport: MemoryTransport, session: MemorySession
) -> None:
    with Riden(transport) as rd:
        assert rd.session is not None
    assert rd.session is None
    assert session.closed


def test_identity(transport: MemoryTransport) -> None:
    with Riden(transport) as rd:
        assert rd.identity() == (
            "model=Model.RD6006P type=60065 sn=00000007 fw=12.34 "
            "input=24.00V vscale=1000 iscale=10000"
        )


def test_status(transport: MemoryTransport) -> None:
    with Riden(transport) as rd:
        status = rd.status()
    assert "model=Model.RD6006P type=60065 sn=00000007 fw=12.34" in status
    assert "set:      12.500 V, 1.000 A" in status
    assert "output:   12.000 V, 0.500 A, 60.000 W" in status
    assert "enabled:  True" in status
