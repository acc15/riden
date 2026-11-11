"""Transaction pacing transport and its session."""

import time
from typing import override

from .transport import Session, Transport, Tx


class DelayedSession(Session):
    """Session that sleeps before each transaction."""

    def __init__(self, inner: Session, delay: float):
        self.inner = inner
        self.delay = delay

    @override
    def execute(self, tx: Tx) -> tuple[int, ...]:
        if self.delay > 0:
            time.sleep(self.delay)
        return self.inner.execute(tx)

    @override
    def close(self) -> None:
        self.inner.close()


class Delayed(Transport):
    """Wrap another transport and pace each transaction.

    open() returns a DelayedSession around the inner session; closing it
    closes the inner session.
    """

    def __init__(
        self,
        inner: Transport,
        delay: float = 0.02,
    ):
        if delay < 0:
            raise ValueError("delay must be >= 0")
        self.inner = inner
        self.delay = delay

    @override
    def open(self) -> DelayedSession:
        return DelayedSession(self.inner.open(), self.delay)
