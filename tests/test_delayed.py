"""Tests for the pacing transport."""

import pytest

from riden.transport.delayed import Delayed, DelayedSession
from riden.transport.transport import Tx
from tests.conftest import RecordingSession, RecordingTransport


def test_open_returns_delayed_session() -> None:
    session = Delayed(RecordingTransport()).open()
    assert isinstance(session, DelayedSession)


def test_execute_sleeps_before_the_inner_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slept: list[float] = []
    monkeypatch.setattr("time.sleep", slept.append)
    inner = RecordingSession((1, 2))
    session = Delayed(RecordingTransport(inner), delay=0.25).open()

    assert session.execute(Tx.read(0, 2)) == (1, 2)
    assert slept == [0.25]
    assert inner.transactions == [Tx.read(0, 2)]


def test_zero_delay_does_not_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr("time.sleep", slept.append)
    session = Delayed(RecordingTransport(), delay=0).open()

    session.execute(Tx.read(0, 1))
    assert slept == []


def test_close_closes_the_inner_session() -> None:
    inner = RecordingSession()
    session = Delayed(RecordingTransport(inner)).open()
    session.close()
    assert inner.closed


def test_negative_delay_is_rejected() -> None:
    with pytest.raises(ValueError, match="delay"):
        Delayed(RecordingTransport(), delay=-1)
