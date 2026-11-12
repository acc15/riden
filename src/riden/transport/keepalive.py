"""Idle keepalive transport and its session.

One background thread serves every open KeepAlive session in the process.
A session carries the inner session, the transaction lock, the interval and
the current deadline.  User transactions reset the deadline; when the deadline
expires the thread reads the device ID register to keep the link from being
closed by the peer's idle timeout.

KeepAlive never reconnects.  A link error or a failed ping removes the session
from the scheduler; a later successful operation (or a logical operation
error, which proves the link is alive) registers it again.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import override

from .errors import is_link_error as default_is_link_error
from .transport import Session, Transport, Tx

log = logging.getLogger(__name__)


class KeepAliveSession(Session):
    """Session that marks activity and serializes inner transactions."""

    def __init__(self, transport: KeepAlive, inner: Session):
        self.transport = transport
        self.inner = inner
        self.lock = threading.RLock()

    @override
    def execute(self, tx: Tx) -> tuple[int, ...]:
        with self.lock:
            try:
                result = self.inner.execute(tx)
            except Exception as exc:
                if self.transport.is_link_error(exc):
                    # Reconnectable will close and reopen this session just
                    # after us.  Do it here too, because a stack without
                    # Reconnectable has nobody else to unschedule it.
                    _scheduler.unschedule(self)
                else:
                    # A logical error proves the link works.
                    _scheduler.schedule(self)
                raise

            _scheduler.schedule(self)
            return result

    @override
    def close(self) -> None:
        with self.lock:
            _scheduler.unschedule(self)
            self.inner.close()


class _Scheduler:
    def __init__(self):
        self._cond = threading.Condition()
        self._deadlines: dict[KeepAliveSession, float] = {}
        self._thread: threading.Thread | None = None

    def schedule(self, session: KeepAliveSession) -> None:
        """Register the session, or push its next ping forward."""
        with self._cond:
            self._deadlines[session] = (
                time.monotonic() + session.transport.interval
            )
            self._ensure_thread_locked()
            self._cond.notify()

    def unschedule(self, session: KeepAliveSession) -> None:
        with self._cond:
            self._deadlines.pop(session, None)
            self._cond.notify()

    def _ensure_thread_locked(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(
                target=self._run,
                name="riden-keepalive",
                daemon=True,
            )
            self._thread.start()

    def _run(self) -> None:
        while True:
            with self._cond:
                if not self._deadlines:
                    self._thread = None
                    return

                now = time.monotonic()
                deadline = min(self._deadlines.values())
                if now < deadline:
                    self._cond.wait(deadline - now)
                    continue

                due = [
                    session for session, deadline in self._deadlines.items()
                    if deadline <= now
                ]

            for session in due:
                self._ping(session)

    def _ping(self, session: KeepAliveSession) -> None:
        with session.lock:
            with self._cond:
                deadline = self._deadlines.get(session)
                if deadline is None or deadline > time.monotonic():
                    return
            try:
                # Ping the inner session directly: going through execute()
                # would reschedule from inside the ping.
                session.inner.execute(Tx.read(0, 1))
            except Exception:
                # Any failed ping means the link is not usable: stop pinging
                # and leave it alone.  Only a real operation can revive it.
                log.debug("keepalive ping failed", exc_info=True)
                self.unschedule(session)
                return

            self.schedule(session)


_scheduler = _Scheduler()


class KeepAlive(Transport):
    """Keep the link alive by reading the ID register while it is idle."""

    inner: Transport
    interval: float
    is_link_error: Callable[[BaseException], bool]

    def __init__(
        self,
        inner: Transport,
        interval: float = 5.0,
        is_link_error: Callable[[BaseException], bool] = default_is_link_error,
    ):
        if interval <= 0:
            raise ValueError("interval must be > 0")
        self.inner = inner
        self.interval = interval
        self.is_link_error = is_link_error

    @override
    def open(self) -> KeepAliveSession:
        session = KeepAliveSession(self, self.inner.open())
        try:
            _scheduler.schedule(session)
        except BaseException:
            session.close()
            raise
        return session
