
import typing
from collections.abc import Callable
from functools import partial
from urllib.parse import parse_qs, urlsplit

from .bt_serial import BtSerial, SecurityLevel

# URL parameter name -> converter from its string value.
_URL_PARAMS: dict[str, Callable[[str], typing.Any]] = {
    "channel": int,
    "timeout": float,
    "connect_timeout": float,
    "security": lambda value: SecurityLevel[value.upper()],
}


def parse_bt_url(url: str):
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "bt":
        raise ValueError(f"not a bt:// URL: {url!r}")

    mac = parsed.netloc
    if not mac:
        raise ValueError(f"no MAC in bt URL: {url!r}")
    if parsed.path not in ("", "/"):
        raise ValueError(
            "channel must be a query parameter, e.g. bt://MAC?channel=1"
        )

    # Only parameters present in the URL are returned, so every default stays
    # in one place: BtSerial.__init__.  KeyError covers both an unknown
    # parameter and an unknown SecurityLevel name.
    kwargs: dict[str, typing.Any] = {}
    for name, values in parse_qs(parsed.query).items():
        try:
            kwargs[name] = _URL_PARAMS[name](values[0])
        except (TypeError, ValueError, KeyError) as exc:
            raise ValueError(f"invalid bt URL parameter: {name}={values[0]!r}") from exc

    return mac, kwargs


def serial_class_for_url(url: str):
    """Return (MAC, partial(BtSerial, **params present in the URL)).

    pyserial calls this hook, then constructs the class with port=None, sets
    instance.port to the returned MAC, and calls open() unless do_not_open.
    """
    mac, kwargs = parse_bt_url(url)
    return mac, partial(BtSerial, **kwargs)