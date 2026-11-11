"""Tests for the idle keepalive transport and its scheduler."""

import pytest

from riden.transport import keepalive
from riden.transport.keepalive import KeepAlive, KeepAliveSession
from riden.transport.transport import Tx
from tests.conftest import RecordingSession, RecordingTransport


class LinkError(Exception):
    pass


class LogicError(Exception):
    pass


def is_link_error(exc: BaseException) -> bool:
    return isinstance(exc, LinkError)


def make(interval: float = 10.0) -> tuple[KeepAlive, RecordingSession]:
    inner = RecordingSession()
    transport = KeepAlive(
        RecordingTransport(inner), interval, is_link_error=is_link_error
    )
    return transport, inner


def scheduled(session: KeepAliveSession) -> bool:
    return session in keepalive._scheduler._deadlines


def test_open_returns_scheduled_session() -> None:
    transport, _ = make()
    session = transport.open()
    assert isinstance(session, KeepAliveSession)
    assert scheduled(session)


def test_execute_returns_inner_result_and_pushes_deadline() -> None:
    transport, inner = make()
    inner.result = (7,)
    session = transport.open()
    before = keepalive._scheduler._deadlines[session]

    assert session.execute(Tx.read(8, 1)) == (7,)
    assert inner.transactions == [Tx.read(8, 1)]
    assert keepalive._scheduler._deadlines[session] >= before


def test_link_error_unschedules_and_reraises() -> None:
    transport, inner = make()
    session = transport.open()
    inner.fail_with = LinkError("down")

    with pytest.raises(LinkError, match="down"):
        session.execute(Tx.read(0, 1))
    assert not scheduled(session)


def test_logical_error_keeps_session_scheduled() -> None:
    transport, inner = make()
    session = transport.open()
    keepalive._scheduler.unschedule(session)
    inner.fail_with = LogicError("device said no")

    with pytest.raises(LogicError, match="device said no"):
        session.execute(Tx.read(0, 1))
    assert scheduled(session)


def test_success_after_failure_reschedules() -> None:
    transport, _ = make()
    session = transport.open()
    keepalive._scheduler.unschedule(session)

    session.execute(Tx.read(0, 1))
    assert scheduled(session)


def test_close_unschedules_and_closes_inner() -> None:
    transport, inner = make()
    session = transport.open()
    session.close()
    assert not scheduled(session)
    assert inner.closed


def test_ping_reads_register_zero() -> None:
    transport, inner = make()
    session = transport.open()
    keepalive._scheduler._deadlines[session] = 0.0

    keepalive._scheduler._ping(session)
    assert inner.transactions == [Tx.read(0, 1)]
    assert scheduled(session)
    assert keepalive._scheduler._deadlines[session] > 0.0


def test_ping_skips_sessions_that_were_rescheduled() -> None:
    transport, inner = make()
    session = transport.open()

    keepalive._scheduler._ping(session)
    assert inner.transactions == []


def test_failed_ping_unschedules() -> None:
    transport, inner = make()
    session = transport.open()
    keepalive._scheduler._deadlines[session] = 0.0
    inner.fail_with = LinkError("dead")

    keepalive._scheduler._ping(session)
    assert not scheduled(session)


def test_interval_must_be_positive() -> None:
    with pytest.raises(ValueError, match="interval"):
        KeepAlive(RecordingTransport(), interval=0)
