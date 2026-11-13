"""Composition root: the default Riden transport stack."""

import logging
from collections.abc import Callable

from .delayed import Delayed
from .errors import is_link_error as default_is_link_error
from .keepalive import KeepAlive
from .logging import Logging
from .modbus import Modbus, Port
from .reconnectable import Reconnectable
from .transport import Transport

log = logging.getLogger("riden")


def build_transport(
    port: Port,
    address: int = 1,
    *,
    delay: float = 0.02,
    keepalive: float | None = None,
    retry_attempts: int = 1,
    retry_delay: float = 0.2,
    is_link_error: Callable[[BaseException], bool] = default_is_link_error,
    logger: logging.Logger | None = log,
    log_level: int = logging.DEBUG,
) -> Transport:
    """Build the default stack: Modbus -> Logging -> Delayed -> KeepAlive -> Reconnectable.

    Reconnectable is outermost: only a real operation reconnects the link.
    KeepAlive never heals anything; it only detects that a ping failed and
    stops pinging until a real operation proves the link works again.

    ``keepalive=None`` (the default) disables idle pings (and the background thread they
    need).  ``is_link_error`` is shared: Reconnectable retries these errors,
    and KeepAlive does not treat a logical error (one that is not a link
    error) as a reason to stop pinging.

    Logging sits directly above Modbus, so it also sees keepalive pings and
    reconnects.  ``logger`` defaults to this module's logger; pass ``None`` to
    leave logging out of the stack entirely.  ``log_level`` defaults to
    ``logging.DEBUG``.
    """
    transport: Transport = Modbus(port, address)
    if logger is not None:
        transport = Logging(transport, logger, log_level)
    if delay > 0:
        transport = Delayed(transport, delay)
    if keepalive is not None:
        transport = KeepAlive(transport, keepalive, is_link_error)
    if retry_attempts > 0:
        transport = Reconnectable(transport, retry_attempts, retry_delay, is_link_error)
    return transport
