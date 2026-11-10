"""Reconnectable transport and its proxy."""

import contextlib
import time
from collections.abc import Callable

import minimalmodbus

from .errors import is_link_error
from .proxy import Proxy
from .transport import Transport


class ReconnectableProxy(Proxy[minimalmodbus.Instrument]):
    """Proxy that retries one whole Modbus transaction.

    One retry is exactly one reconnect attempt followed by one operation
    attempt.  If the reconnect itself fails, that still consumes a retry.

    Per-session state (the current target and the reconnect count) lives
    here, not in ReconnectableTransport.
    """

    transport: Reconnectable
    attempts: int

    def __init__(
        self,
        target: minimalmodbus.Instrument,
        transport: Reconnectable,
        attempts: int = 0
    ):
        super().__init__(target)
        object.__setattr__(self, "transport", transport)
        object.__setattr__(self, "attempts", attempts)

    def can_retry(self):
        return self.attempts < self.transport.attempts

    def on_retry(self):
        self.attempts += 1
        with contextlib.suppress(Exception):
            self.transport.inner.close(self.target)
        self.target = self.transport.inner.open()

    def _wrap_callable(self, name: str, func: Callable) -> Callable:
        if self.attempts >= self.transport.attempts:
            return func

        def wrapped(*args, **kwargs):
            return self.transport.retry(
                lambda: getattr(self._get_target(), name)(*args, **kwargs),
                self.can_retry,
                self.on_retry,
            )

        return wrapped


class Reconnectable(Transport[minimalmodbus.Instrument]):
    """Wrap another transport and reconnect on retryable transaction errors.

    The transport is an immutable factory: open() and close() do not change
    it.  Per-session state (current target, reconnect count) belongs to the
    proxy returned by open().

    Each retry performs exactly one reconnect attempt and, if it succeeds,
    one retry of the failed operation.  A failed reconnect consumes a retry.
    """

    def __init__(
        self,
        inner: Transport[minimalmodbus.Instrument],
        attempts: int = 1,
        delay: float = 0.2,
        is_retryable: Callable[[BaseException], bool] = is_link_error,
    ):
        if attempts < 0:
            raise ValueError("retries must be >= 0")
        if delay < 0:
            raise ValueError("retry_delay must be >= 0")
        self.inner = inner
        self.attempts = attempts
        self.delay = delay
        self.is_retryable = is_retryable

    def open(self) -> minimalmodbus.Instrument:
        open_attempts = 0
        
        def on_retry():
            nonlocal open_attempts
            open_attempts += 1

        target = self.retry(lambda: self.inner.open(), lambda: open_attempts < self.attempts, on_retry)
        return ReconnectableProxy(target, self, open_attempts)

    def close(self, proxy: minimalmodbus.Instrument):
        self.inner.close(proxy.target)

    def retry[T](self, fn: Callable[[], T], can_retry: Callable[[], bool], on_retry: Callable) -> T:
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

