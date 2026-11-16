"""pyserial URL handler for the Bluetooth LE port.

Only link settings live in the URL; the read/write timeout is a regular port
setting passed as an argument, like for any pyserial port:
serial_for_url("bt://ADDRESS?connect_timeout=5", timeout=1).

The netloc is a BLE address or a device name, for example:

    bt://E1:F9:C6:24:71:C8
    bt://RK6006?connect_timeout=5
"""

import typing
from collections.abc import Callable
from functools import partial
from urllib.parse import parse_qs, unquote, urlsplit

from .bt_serial import BtSerial

# URL parameter name -> converter from its string value.
_URL_PARAMS: dict[str, Callable[[str], typing.Any]] = {
    "connect_timeout": float,
}


def parse_bt_url(url: str) -> tuple[str, dict[str, typing.Any]]:
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "bt":
        raise ValueError(f"not a bt:// URL: {url!r}")

    target = unquote(parsed.netloc)
    if not target:
        raise ValueError(f"no address or device name in bt URL: {url!r}")
    if parsed.path not in ("", "/"):
        raise ValueError("unexpected path in bt URL; use bt://ADDRESS?connect_timeout=5")

    # Only parameters present in the URL are returned, so every default stays
    # in one place: BtSerial.__init__.  KeyError covers both an unknown
    # parameter and a value the converter rejects.
    kwargs: dict[str, typing.Any] = {}
    for name, values in parse_qs(parsed.query, keep_blank_values=True).items():
        try:
            kwargs[name] = _URL_PARAMS[name](values[0])
        except (TypeError, ValueError, KeyError) as exc:
            raise ValueError(f"invalid bt URL parameter: {name}={values[0]!r}") from exc

    return target, kwargs


def serial_class_for_url(url: str):
    """Return (target, partial(BtSerial, **params present in the URL)).

    pyserial calls this hook, then constructs the class with port=None, sets
    instance.port to the returned target, and calls open() unless do_not_open.
    """
    target, kwargs = parse_bt_url(url)
    return target, partial(BtSerial, **kwargs)
