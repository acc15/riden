"""Logging transport and its session.

The transport writes one line per lifecycle event and one line per Modbus
transaction.  Requests and successful responses carry the same monotonic
transaction ID, so they can be correlated even when several sessions share a
logger.  Writes have no response and therefore log only the request.
"""

import itertools
import logging
from typing import override

from .transport import Op, Registers, Session, Transport, Tx


def _format_data(data: Registers) -> str:
    """Format registers as ``[1, 2, 3]`` without building a list."""
    return "[" + ", ".join(map(str, data)) + "]"


class LoggingSession(Session):
    """Session that logs open/close and each request/response."""

    def __init__(self, transport: Logging, inner: Session):
        self.transport = transport
        self.inner = inner

    @override
    def execute(self, tx: Tx) -> Registers:
        logger = self.transport.logger
        level = self.transport.level
        target = str(self.inner)
        request_id = next(self.transport.ids)
        request_data = f" data={_format_data(tx.data)}" if tx.data else ""

        logger.log(
            level,
            "%s request #%d: %s start=%d count=%d%s",
            target,
            request_id,
            tx.op.name,
            tx.start,
            tx.count,
            request_data,
        )
        result = self.inner.execute(tx)
        if tx.op is not Op.WRITE:
            response_data = f" data={_format_data(result)}" if result else ""
            logger.log(
                level,
                "%s response #%d: %s%s",
                target,
                request_id,
                tx.op.name,
                response_data,
            )
        return result

    @override
    def close(self) -> None:
        self.transport.logger.log(
            self.transport.level,
            "%s close",
            self.inner,
        )
        self.inner.close()


class Logging(Transport):
    """Wrap another transport and log its lifecycle and transactions.

    ``logger`` is required; ``level`` defaults to ``logging.DEBUG``.  The
    logged target is ``str(inner session)``: Modbus describes the port or
    MAC/channel plus the Modbus address, while any other session keeps its
    default representation.
    """

    def __init__(
        self,
        inner: Transport,
        logger: logging.Logger,
        level: int = logging.DEBUG,
    ):
        self.inner = inner
        self.logger = logger
        self.level = level
        self.ids = itertools.count(1)

    @override
    def open(self) -> LoggingSession:
        session = LoggingSession(self, self.inner.open())
        self.logger.log(self.level, "%s open", session.inner)
        return session
