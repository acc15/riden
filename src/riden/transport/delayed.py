"""Transaction pacing transport and its proxy."""

import time
from collections.abc import Callable

import minimalmodbus

from .proxy import Proxy
from .transport import Transport


class DelayedProxy(Proxy[minimalmodbus.Instrument]):
    """Proxy that sleeps before each callable attribute access."""

    transport: Delayed

    def __init__(self, target: minimalmodbus.Instrument, transport: Delayed):
        super().__init__(target)
        object.__setattr__(self, "transport", transport)

    def _wrap_callable(self, _: str, func: Callable) -> Callable:
        if self.transport.delay <= 0:
            return func

        def hooked(*args, **kwargs):
            time.sleep(self.transport.delay)
            return func(*args, **kwargs)

        return hooked


class Delayed(Transport[minimalmodbus.Instrument]):
    """Wrap another Modbus transport and pace each transaction.

    open() returns the inner client, optionally wrapped in DelayedProxy.
    close(obj) unwraps it and lets the inner transport close its own resource.
    """

    def __init__(
        self,
        inner: Transport[minimalmodbus.Instrument],
        delay: float = 0.02,
    ):
        if delay < 0:
            raise ValueError("delay must be >= 0")
        self.inner = inner
        self.delay = delay

    def open(self) -> minimalmodbus.Instrument:
        return DelayedProxy(self.inner.open(), self)

    def close(self, obj: minimalmodbus.Instrument) -> None:
        self.inner.close(obj.target)
