"""Classification of transport errors."""

import errno

import minimalmodbus
import serial

_LINK_ERRNOS = frozenset(
    {
        errno.ETIMEDOUT,
        errno.ECONNRESET,
        errno.ECONNREFUSED,
        errno.EBUSY,
        errno.EPIPE,
        errno.EBADF,
        errno.EIO,
        errno.ENODEV,
        errno.ENXIO,
        errno.ESHUTDOWN,
    }
)


def is_link_error(exc: BaseException) -> bool:
    """Return True only for errors that a reconnect can plausibly fix.

    SlaveReportedException is a device/protocol error, not a link error, and
    must not trigger a reconnect.  NoResponseError and InvalidResponseError,
    on the other hand, are retryable link/protocol failures.
    """
    if isinstance(exc, minimalmodbus.SlaveReportedException):
        return False
    if isinstance(
        exc,
        (
            minimalmodbus.NoResponseError,
            minimalmodbus.InvalidResponseError,
            serial.SerialException,
            TimeoutError,
            ConnectionError,
        ),
    ):
        return True
    return isinstance(exc, OSError) and exc.errno in _LINK_ERRNOS
