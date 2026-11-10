"""Idle keepalive transport and its proxy.

One background thread serves every open KeepAlive session in the process.
A session is an opened proxy: it carries the target, the transaction lock,
the interval and the current deadline.  User transactions reset the deadline;
when the deadline expires the thread reads the device ID register to keep the
link from being closed by the peer's idle timeout.
"""

import logging
import threading
import time
from functools import wraps

import minimalmodbus

from .errors import is_link_error
from .proxy import Proxy
from .transport import Transport

log = logging.getLogger(__name__)


class KeepAliveProxy(Proxy[minimalmodbus.Instrument]):
    """Proxy that marks activity and serializes target transactions."""

    interval: float
    lock: threading.RLock

    def __init__(self, target: minimalmodbus.Instrument, interval: float):
        super().__init__(target)
        object.__setattr__(self, "interval", interval)
        object.__setattr__(self, "lock", threading.RLock())

    def _wrap_callable(self, name: str, func):
        @wraps(func)
        def wrapped(*args, **kwargs):
            with self.lock:
                try:
                    return func(*args, **kwargs)
                finally:
                    _scheduler.touch(self)

        return wrapped


class _Scheduler:
    def __init__(self):
        self._cond = threading.Condition()
        self._deadlines: dict[KeepAliveProxy, float] = {}
        self._thread: threading.Thread | None = None

    def register(self, proxy: KeepAliveProxy) -> None:
        with self._cond:
            self._deadlines[proxy] = time.monotonic() + proxy.interval
            self._ensure_thread_locked()
            self._cond.notify()

    def unregister(self, proxy: KeepAliveProxy) -> None:
        with self._cond:
            self._deadlines.pop(proxy, None)
            self._cond.notify()

    def touch(self, proxy: KeepAliveProxy) -> None:
        with self._cond:
            if proxy not in self._deadlines:
                return

            self._deadlines[proxy] = time.monotonic() + proxy.interval
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
                    proxy for proxy, deadline in self._deadlines.items()
                    if deadline <= now
                ]

            for proxy in due:
                self._ping(proxy)

    def _ping(self, proxy: KeepAliveProxy) -> None:
        with proxy.lock:
            with self._cond:
                deadline = self._deadlines.get(proxy)
                if deadline is None or deadline > time.monotonic():
                    return
            try:
                proxy.target.read_register(0)
            except Exception as exc:
                log.debug("keepalive ping failed", exc_info=True)
                if is_link_error(exc):
                    with self._cond:
                        self._deadlines.pop(proxy, None)
                    return

            with self._cond:
                if proxy in self._deadlines:
                    self._deadlines[proxy] = time.monotonic() + proxy.interval


_scheduler = _Scheduler()


class KeepAlive(Transport[minimalmodbus.Instrument]):
    """Keep the link alive by reading the ID register while it is idle."""

    inner: Transport[minimalmodbus.Instrument]
    interval: float

    def __init__(
        self,
        inner: Transport[minimalmodbus.Instrument],
        interval: float = 5.0,
    ):
        if interval <= 0:
            raise ValueError("interval must be > 0")
        self.inner = inner
        self.interval = interval

    def open(self) -> minimalmodbus.Instrument:
        target = self.inner.open()
        proxy = KeepAliveProxy(target, self.interval)
        try:
            _scheduler.register(proxy)
        except BaseException:
            self.inner.close(target)
            raise
        return proxy

    def close(self, proxy: KeepAliveProxy) -> None:
        with proxy.lock:
            _scheduler.unregister(proxy)
            self.inner.close(proxy.target)
