
import typing
from functools import partial
from urllib.parse import parse_qs, urlsplit

from .bt_serial import BtSerial


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

    query = parse_qs(parsed.query)

    def qs(name: str, type: type):
        values = query.get(name)
        if values is None:
            return None
        try:
            return type(values[0])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid {name} in URL: {values[0]!r}") from exc

    kwargs: dict[str, typing.Any] = {
        "channel": qs("channel", int) or 1,
        "timeout": qs("timeout", float),
        "connect_timeout": qs("connect_timeout", float)
    }

    return mac, kwargs

def serial_class_for_url(url: str):
    """Return (MAC, partial(BtSerial, channel=..., timeout=...)).

    pyserial calls this hook, then constructs the class with port=None, sets
    instance.port to the returned MAC, and calls open() unless do_not_open.
    """
    mac, kwargs = parse_bt_url(url)
    return mac, partial(BtSerial, **kwargs)