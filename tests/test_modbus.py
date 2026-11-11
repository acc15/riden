"""Tests for the Modbus transport and its session."""

from typing import Any, cast

import pytest

from riden.transport.modbus import Modbus
from riden.transport.transport import Tx
from tests.conftest import FakeInstrument, FakePort, as_port


def test_open_returns_self_and_opens_the_port(
    fake_instrument: type[FakeInstrument],
) -> None:
    port = FakePort()
    modbus = Modbus(as_port(port))
    assert modbus.open() is modbus
    assert port.opens == 1
    assert port.is_open
    assert len(fake_instrument.instances) == 1


def test_open_sets_instrument_options(
    fake_instrument: type[FakeInstrument],
) -> None:
    modbus = Modbus(as_port(FakePort()), address=3).open()
    instrument = cast(FakeInstrument, modbus.instrument)
    assert instrument.address == 3
    assert instrument.clear_buffers_before_each_transaction is True


def test_open_is_idempotent(fake_instrument: type[FakeInstrument]) -> None:
    port = FakePort()
    modbus = Modbus(as_port(port))
    first = modbus.open()
    second = modbus.open()
    assert first is second
    assert port.opens == 1
    assert len(fake_instrument.instances) == 1


def test_execute_reads_and_writes(fake_instrument: type[FakeInstrument]) -> None:
    modbus = Modbus(as_port(FakePort())).open()
    assert modbus.execute(Tx.read(8, 1)) == [12500]
    assert modbus.execute(Tx.write(8, [5000])) == []
    assert modbus.execute(Tx.read(8, 1)) == [5000]


def test_execute_before_open_fails(fake_instrument: type[FakeInstrument]) -> None:
    modbus = Modbus(as_port(FakePort()))
    with pytest.raises(RuntimeError, match="not open"):
        modbus.execute(Tx.read(0, 1))


def test_execute_after_close_fails(
    fake_instrument: type[FakeInstrument],
) -> None:
    modbus = Modbus(as_port(FakePort())).open()
    modbus.close()
    with pytest.raises(RuntimeError, match="not open"):
        modbus.execute(Tx.read(0, 1))


def test_close_closes_owned_port(fake_instrument: type[FakeInstrument]) -> None:
    port = FakePort()
    modbus = Modbus(as_port(port)).open()
    modbus.close()
    assert port.closes == 1
    assert not port.is_open


def test_instrument_is_reused_across_open_close(
    fake_instrument: type[FakeInstrument],
) -> None:
    port = FakePort()
    modbus = Modbus(as_port(port)).open()
    instrument = modbus.instrument
    modbus.close()
    modbus.open()
    assert modbus.instrument is instrument
    assert len(fake_instrument.instances) == 1
    assert port.opens == 2


def test_external_open_port_is_not_owned(
    fake_instrument: type[FakeInstrument],
) -> None:
    port = FakePort()
    port.open()
    modbus = Modbus(as_port(port)).open()
    modbus.close()
    assert port.opens == 1
    assert port.closes == 0
    assert port.is_open


def test_external_closed_port_is_owned(
    fake_instrument: type[FakeInstrument],
) -> None:
    port = FakePort()
    modbus = Modbus(as_port(port)).open()
    assert port.opens == 1
    modbus.close()
    assert port.closes == 1


def test_port_open_failure_is_not_cleaned_up(
    fake_instrument: type[FakeInstrument],
) -> None:
    port = FakePort()
    port.open_error = OSError("cannot open")
    with pytest.raises(OSError, match="cannot open"):
        Modbus(as_port(port)).open()
    assert port.closes == 0


def test_instrument_failure_closes_owned_port(
    fake_instrument: type[FakeInstrument],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Boom:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("instrument boom")

    port = FakePort()
    monkeypatch.setattr("minimalmodbus.Instrument", Boom)
    with pytest.raises(RuntimeError, match="instrument boom"):
        Modbus(as_port(port)).open()
    assert port.opens == 1
    assert port.closes == 1
    assert not port.is_open
