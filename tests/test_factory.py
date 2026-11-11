"""Tests for the default transport stack."""

from typing import cast

from riden.transport import Delayed, KeepAlive, Modbus, Reconnectable, build_transport
from riden.transport.transport import Tx
from tests.conftest import FakeInstrument, FakePort, as_port


def test_stack_without_keepalive(fake_instrument: type[FakeInstrument]) -> None:
    stack = build_transport(as_port(FakePort()), keepalive=None, delay=0)
    assert isinstance(stack, Reconnectable)
    delayed = cast(Delayed, stack.inner)
    assert isinstance(delayed, Delayed)
    assert isinstance(delayed.inner, Modbus)


def test_stack_with_keepalive(fake_instrument: type[FakeInstrument]) -> None:
    stack = build_transport(as_port(FakePort()), keepalive=5.0, delay=0)
    assert isinstance(stack, Reconnectable)
    keepalive = cast(KeepAlive, stack.inner)
    assert isinstance(keepalive, KeepAlive)
    delayed = cast(Delayed, keepalive.inner)
    assert isinstance(delayed, Delayed)
    assert isinstance(delayed.inner, Modbus)


def test_stack_end_to_end(fake_instrument: type[FakeInstrument]) -> None:
    port = FakePort()
    stack = build_transport(as_port(port), keepalive=None, delay=0)

    session = stack.open()
    assert session.execute(Tx.read(0, 3)) == [60065, 0, 7]
    assert session.execute(Tx.write(8, [5000])) == []
    assert session.execute(Tx.read(8, 1)) == [5000]
    session.close()

    assert port.opens == 1
    assert port.closes == 1
    assert not port.is_open
