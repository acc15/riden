"""Tests for the reconnecting transport and its retry budget."""

import pytest

from riden.transport.reconnectable import Reconnectable, ReconnectableSession
from riden.transport.transport import Registers, Tx


class LinkError(Exception):
    pass


class LogicError(Exception):
    pass


def is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, LinkError)


class FlakySession:
    def __init__(self, transport: FlakyTransport, kind: str = "normal") -> None:
        self.transport = transport
        self.kind = kind
        self.closed = False

    def execute(self, tx: Tx) -> Registers:
        if self.kind == "logic":
            raise LogicError("device said no")
        if self.closed or self.transport.failures:
            if self.transport.failures:
                self.transport.failures -= 1
            raise LinkError("link down")
        return (42,)

    def close(self) -> None:
        self.closed = True


class FlakyTransport:
    def __init__(self, failures: int = 0, kind: str = "normal") -> None:
        self.failures = failures
        self.kind = kind
        self.opens = 0
        self.open_failures = 0
        self.sessions: list[FlakySession] = []

    def open(self) -> FlakySession:
        if self.open_failures:
            self.open_failures -= 1
            raise LinkError("cannot reconnect")
        self.opens += 1
        session = FlakySession(self, self.kind)
        self.sessions.append(session)
        return session


def make(inner: FlakyTransport, attempts: int = 1) -> Reconnectable:
    return Reconnectable(inner, attempts, 0, is_link_error=is_retryable)


def test_open_returns_reconnectable_session() -> None:
    session = make(FlakyTransport()).open()
    assert isinstance(session, ReconnectableSession)


def test_happy_path() -> None:
    inner = FlakyTransport()
    session = make(inner).open()
    assert session.execute(Tx.read(0, 1)) == (42,)
    assert inner.opens == 1


def test_link_error_reconnects_and_retries() -> None:
    inner = FlakyTransport(failures=1)
    session = make(inner).open()

    assert session.execute(Tx.read(0, 1)) == (42,)
    assert inner.opens == 2
    assert inner.sessions[0].closed
    assert not inner.sessions[1].closed


def test_retry_budget_is_exhausted() -> None:
    inner = FlakyTransport(failures=5)
    session = make(inner, attempts=1).open()

    with pytest.raises(LinkError, match="link down"):
        session.execute(Tx.read(0, 1))
    assert inner.opens == 2


def test_retry_budget_resets_for_each_transaction() -> None:
    inner = FlakyTransport(failures=1)
    session = make(inner, attempts=1).open()

    assert session.execute(Tx.read(0, 1)) == (42,)
    inner.failures = 1
    assert session.execute(Tx.read(0, 1)) == (42,)
    assert inner.opens == 3


def test_non_retryable_error_does_not_reconnect() -> None:
    inner = FlakyTransport(kind="logic")
    session = make(inner).open()

    with pytest.raises(LogicError, match="device said no"):
        session.execute(Tx.read(0, 1))
    assert inner.opens == 1


def test_close_closes_the_current_session() -> None:
    inner = FlakyTransport(failures=1)
    session = make(inner).open()
    session.execute(Tx.read(0, 1))

    session.close()
    assert inner.sessions[-1].closed


def test_failed_reconnect_surfaces_the_error() -> None:
    inner = FlakyTransport(failures=1)
    session = make(inner, attempts=1).open()
    inner.open_failures = 1

    with pytest.raises(LinkError, match="cannot reconnect"):
        session.execute(Tx.read(0, 1))


def test_open_retries_inner_transport() -> None:
    inner = FlakyTransport()
    inner.open_failures = 1

    session = make(inner, attempts=1).open()
    assert isinstance(session, ReconnectableSession)
    assert inner.opens == 1


def test_negative_attempts_are_rejected() -> None:
    with pytest.raises(ValueError, match="retries"):
        Reconnectable(FlakyTransport(), attempts=-1)


def test_negative_delay_is_rejected() -> None:
    with pytest.raises(ValueError, match="retry_delay"):
        Reconnectable(FlakyTransport(), delay=-1)
