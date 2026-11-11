"""Composition root: the default Riden transport stack."""

from collections.abc import Callable

from .delayed import Delayed
from .errors import is_link_error as default_is_link_error
from .keepalive import KeepAlive
from .modbus import Modbus, Port
from .reconnectable import Reconnectable
from .transport import Transport


def build_transport(
    port: Port,
    address: int = 1,
    *,
    delay: float = 0.02,
    keepalive: float | None = 5.0,
    retry_attempts: int = 1,
    retry_delay: float = 0.2,
    is_link_error: Callable[[BaseException], bool] = default_is_link_error,
) -> Transport:
    """Build the default stack: Modbus -> Delayed -> KeepAlive -> Reconnectable.

    Reconnectable is outermost: only a real operation reconnects the link.
    KeepAlive never heals anything; it only detects that a ping failed and
    stops pinging until a real operation proves the link works again.

    ``keepalive=None`` disables idle pings (and the background thread they
    need).  ``is_link_error`` is shared: Reconnectable retries these errors,
    and KeepAlive does not treat a logical error (one that is not a link
    error) as a reason to stop pinging.
    """
    transport: Transport = Modbus(port, address)
    if delay > 0:
        transport = Delayed(transport, delay)
    if keepalive is not None:
        transport = KeepAlive(transport, keepalive, is_link_error)
    if retry_attempts > 0:
        transport = Reconnectable(transport, retry_attempts, retry_delay, is_link_error)
    return transport
