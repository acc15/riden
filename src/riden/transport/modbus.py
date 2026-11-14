"""Modbus transport for Riden.

``Modbus`` is both the transport and the session: there is exactly one port,
so ``open()`` opens it and returns self, and ``close()`` closes it.  No
ownership is transferred to a separate session object.

Device semantics (registers, model, properties) live in Riden; transaction
pacing lives in Delayed.
"""

from typing import Self, cast, override

import minimalmodbus
import serial

from ..bt import BtSerial
from .transport import Op, Registers, Session, Transport, Tx

type Port = serial.Serial | BtSerial | str

class Modbus(Transport, Session):
    """Create a minimalmodbus client for one pyserial-like port.

    Construction configures the transport but does not open it: a string is
    resolved with serial_for_url(..., do_not_open=True), which creates no fd
    and no socket.  open() opens the port if needed and returns self.
    """

    def __init__(
        self,
        port: Port,
        address: int = 1
    ):
        if isinstance(port, str):
            # Configure the transport without opening it.  This is not I/O:
            # serial_for_url only parses the URL and constructs the object
            # (no fd, no socket).  It returns a pyserial port or, for bt://,
            # a BtSerial registered as a pyserial URL handler.
            self.port: serial.Serial | BtSerial = cast(
                "serial.Serial | BtSerial",
                serial.serial_for_url(port, do_not_open=True),
            )
            self.owns_port = True
        else:
            self.port = port
            self.owns_port = not port.is_open
        self.address = address
        self.instrument: minimalmodbus.Instrument | None = None

    @override
    def __str__(self) -> str:
        port = self.port
        name = port.port if port.port is not None else "?"
        if isinstance(port, BtSerial):
            return f"{name}/{port.channel}@{self.address}"
        return f"{name}@{self.address}"

    @override
    def open(self) -> Self:
        if self.owns_port and not self.port.is_open:
            self.port.open()
        try:
            # The instrument is built once and kept: it already points at the
            # right port with the right config, so a reopen only has to bring
            # the port back up.
            instrument = self.instrument
            if instrument is None:
                # minimalmodbus duck-types the port (open/close/read/write/
                # is_open) and its annotations only name serial.Serial;
                # BtSerial implements the same interface.
                instrument = minimalmodbus.Instrument(
                    cast("serial.Serial", self.port),
                    self.address,
                    mode=minimalmodbus.MODE_RTU,
                    debug=False,
                )
                instrument.clear_buffers_before_each_transaction = True
                self.instrument = instrument
            return self
        except BaseException:
            # Only undo what this call did: a port that failed to open (or
            # that belongs to the caller) must not be closed here.
            if self.owns_port:
                self.port.close()
            raise

    @override
    def execute(self, tx: Tx) -> Registers:
        # Both read_register/read_registers and write_register/write_registers
        # produce identical requests, so only the plural forms are used.
        # The port check matters: minimalmodbus reopens a closed port by
        # itself, so without it a closed session would silently come back.
        instrument = self.instrument
        if instrument is None or not self.port.is_open:
            raise RuntimeError("Modbus is not open")
        if tx.op is Op.READ:
            return tuple(instrument.read_registers(tx.start, tx.count))
        instrument.write_registers(tx.start, list(tx.data))
        return ()

    @override
    def close(self) -> None:
        # Keep the instrument and the port: they still point at the right
        # port and hold the configuration, so the next open() reuses them.
        # Only the OS handle/socket is released.
        if self.owns_port:
            self.port.close()
