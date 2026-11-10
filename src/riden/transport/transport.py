"""Protocol shared by the device client and the transport layer.

``Transport`` deliberately differs from ``retry.OpenClose``:

* ``OpenClose`` is for an object that manages its own lifetime (``Riden``);
  ``RetryOpen`` calls ``obj.open()`` and returns ``obj`` itself.
* ``Transport`` creates a separate resource and closes exactly that resource
  later.  The caller owns the produced object.

A transport is an immutable factory: its constructor stores the configuration
needed to create objects, and ``open()``/``close()`` do not mutate it.
Per-session state belongs to the object returned by ``open()``.
"""

from typing import Protocol


class Transport[T](Protocol):
    """Create a resource with open() and close exactly that resource."""

    def open(self) -> T: ...

    def close(self, obj: T) -> None: ...
