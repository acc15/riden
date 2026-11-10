"""Base class for proxies that delegate attribute access to a target."""

from collections.abc import Callable
from typing import Any


class Proxy[T]:
    """Delegate attribute access to a target object.

    Proxy-local fields are exactly the attributes present in ``self.__dict__``.
    The base class seeds ``target``; subclasses must seed their own fields with
    ``object.__setattr__`` so they become local.  Any other assignment is
    forwarded to the target.

    ``target`` must not be None.  Setting it to None invalidates the proxy:
    subsequent delegated access raises RuntimeError.

    Callable attributes are passed through ``_wrap_callable`` so subclasses can
    add delay or retry behavior without reimplementing delegation.
    """

    target: T

    def __init__(self, target: T):
        object.__setattr__(self, "target", target)

    def _get_target(self) -> T:
        if self.target is None:
            raise RuntimeError("Proxy has no target")
        return self.target

    def _wrap_callable(self, _: str, func: Callable) -> Callable:
        return func

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._get_target(), name)
        if callable(attr):
            return self._wrap_callable(name, attr)
        return attr

    def __setattr__(self, name: str, value: Any) -> None:
        if name in self.__dict__:
            object.__setattr__(self, name, value)
        else:
            setattr(self._get_target(), name, value)
