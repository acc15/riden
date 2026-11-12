"""Reconnectable transport and its session."""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable
from typing import override

from .errors import is_link_error
from .transport import Session, Transport, Tx


class ReconnectableSession(Session):
    """Session that retries one whole Modbus transaction.

    One retry is exactly one reconnect attempt followed by one operation
    attempt.  If the reconnect itself fails, that still consumes a retry.

    The retry budget belongs to one transaction, not to the whole session: a
    long-lived client must be able to reconnect again after the link drops
    later.  Per-session state (the current inner session) lives here, not in
    Reconnectable.
    """

    def __init__(self, transport: Reconnectable, session: Session):
        self.transport = transport
        self.session = session

    @override
    def execute(self, tx: Tx) -> tuple[int, ...]:
        attempts = 0

        def can_retry() -> bool:
            return attempts < self.transport.attempts

        def on_retry() -> None:
            nonlocal attempts
            attempts += 1
            self.reconnect()

        return self.transport.retry(
            lambda: self.session.execute(tx),
            can_retry,
            on_retry,
        )

    def reconnect(self) -> None:
        with contextlib.suppress(Exception):
            self.session.close()
        self.session = self.transport.inner.open()

    @override
    def close(self) -> None:
        self.session.close()


class Reconnectable(Transport):
    """Wrap another transport and reconnect on retryable transaction errors.

    The transport only stores configuration; the state (the current inner
    session) belongs to the session returned by open().

    Each retry performs exactly one reconnect attempt and, if it succeeds,
    one retry of the failed operation.  A failed reconnect consumes a retry.
    """

    def __init__(
        self,
        inner: Transport,
        attempts: int = 1,
        delay: float = 0.2,
        is_link_error: Callable[[BaseException], bool] = is_link_error,
    ):
        if attempts < 0:
            raise ValueError("retries must be >= 0")
        if delay < 0:
            raise ValueError("retry_delay must be >= 0")
        self.inner = inner
        self.attempts = attempts
        self.delay = delay
        self.is_retryable = is_link_error

    @override
    def open(self) -> ReconnectableSession:
        open_attempts = 0

        def can_retry() -> bool:
            return open_attempts < self.attempts

        def on_retry() -> None:
            nonlocal open_attempts
            open_attempts += 1

        session = self.retry(self.inner.open, can_retry, on_retry)
        return ReconnectableSession(self, session)

    def retry[T](
        self,
        fn: Callable[[], T],
        can_retry: Callable[[], bool],
        on_retry: Callable[[], None],
    ) -> T:
        while True:
            try:
                return fn()
            except Exception as exc:
                if not can_retry() or not self.is_retryable(exc):
                    raise
            if self.delay > 0:
                time.sleep(self.delay)
            try:
                on_retry()
            except Exception as exc:
                if not can_retry() or not self.is_retryable(exc):
                    raise
