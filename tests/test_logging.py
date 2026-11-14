"""Tests for the logging transport."""

import logging
from typing import override

import pytest

from riden.transport.logging import Logging, LoggingSession
from riden.transport.transport import Registers, Tx
from tests.conftest import RecordingSession, RecordingTransport


class TargetedSession(RecordingSession):
    """Recording session with a readable target for log assertions."""

    def __init__(
        self,
        result: Registers | None = None,
        target: str = "fake address=1",
    ):
        super().__init__(result)
        self.target = target

    @override
    def __str__(self) -> str:
        return self.target


def make(
    logger: logging.Logger,
    level: int = logging.DEBUG,
) -> tuple[Logging, TargetedSession]:
    inner = TargetedSession()
    return Logging(RecordingTransport(inner), logger, level), inner


@pytest.fixture
def logger() -> logging.Logger:
    return logging.getLogger("riden.test.logging")


def test_open_logs_target_and_returns_session(
    caplog: pytest.LogCaptureFixture,
    logger: logging.Logger,
) -> None:
    caplog.set_level(logging.DEBUG, logger=logger.name)
    transport, _ = make(logger)

    session = transport.open()

    assert isinstance(session, LoggingSession)
    assert caplog.messages == ["fake address=1 open"]


def test_read_logs_request_and_response_with_same_id(
    caplog: pytest.LogCaptureFixture,
    logger: logging.Logger,
) -> None:
    caplog.set_level(logging.DEBUG, logger=logger.name)
    transport, inner = make(logger)
    inner.result = (10, 20)
    session = transport.open()
    caplog.clear()

    assert session.execute(Tx.read(5, 2)) == (10, 20)

    assert caplog.messages == [
        "fake address=1 request #1: READ start=5 count=2",
        "fake address=1 response #1: READ data=[10, 20]",
    ]


def test_write_logs_only_the_request(
    caplog: pytest.LogCaptureFixture,
    logger: logging.Logger,
) -> None:
    caplog.set_level(logging.DEBUG, logger=logger.name)
    transport, _ = make(logger)
    session = transport.open()
    caplog.clear()

    assert session.execute(Tx.write(8, [12500])) == ()

    assert caplog.messages == [
        "fake address=1 request #1: WRITE start=8 count=1 data=[12500]",
    ]


def test_transaction_ids_increase(
    caplog: pytest.LogCaptureFixture,
    logger: logging.Logger,
) -> None:
    caplog.set_level(logging.DEBUG, logger=logger.name)
    transport, _ = make(logger)
    session = transport.open()

    session.execute(Tx.read(0, 1))
    session.execute(Tx.read(1, 1))

    assert any("#1:" in message for message in caplog.messages)
    assert any("#2:" in message for message in caplog.messages)


def test_close_logs_and_closes_inner(
    caplog: pytest.LogCaptureFixture,
    logger: logging.Logger,
) -> None:
    caplog.set_level(logging.DEBUG, logger=logger.name)
    transport, inner = make(logger)
    session = transport.open()
    caplog.clear()

    session.close()

    assert inner.closed
    assert caplog.messages == ["fake address=1 close"]


def test_custom_level_is_used(
    caplog: pytest.LogCaptureFixture,
    logger: logging.Logger,
) -> None:
    caplog.set_level(logging.DEBUG, logger=logger.name)
    transport, _ = make(logger, logging.WARNING)

    session = transport.open()
    session.execute(Tx.read(0, 1))
    session.close()

    assert caplog.messages
    assert {record.levelno for record in caplog.records} == {logging.WARNING}


def test_request_is_logged_when_inner_call_fails(
    caplog: pytest.LogCaptureFixture,
    logger: logging.Logger,
) -> None:
    caplog.set_level(logging.DEBUG, logger=logger.name)
    transport, inner = make(logger)
    session = transport.open()
    inner.fail_with = RuntimeError("boom")
    caplog.clear()

    with pytest.raises(RuntimeError, match="boom"):
        session.execute(Tx.read(0, 1))

    assert caplog.messages == [
        "fake address=1 request #1: READ start=0 count=1",
    ]
