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

from .transport import Op, Registers, Session, Transport, Tx

# Riden factory baud rate; the device menu also offers 9600..57600.
DEFAULT_BAUDRATE = 115200
DEFAULT_TIMEOUT = 1.0

class Modbus(Transport, Session):
    """Create a minimalmodbus client for one pyserial-like port.

    Construction configures the transport but does not open it: a string is
    resolved with serial_for_url(..., do_not_open=True), which creates no fd
    and no socket.  open() opens the port if needed and returns self.

    ``baudrate``, ``timeout`` and ``write_timeout`` apply only to a port
    created here from a string; a port object passed in keeps its own
    settings.  ``write_timeout=None`` (the pyserial default) blocks writes.
    For bt://, BLE has no baud rate: ``baudrate`` only sets the Modbus
    inter-frame timing.

    A port object passed in is managed by Modbus: close() closes it and
    open() reopens it, even if it was already open when passed in.
    """

    def __init__(
        self,
        port: serial.SerialBase | str,
        address: int = 1,
        *,
        baudrate: int = DEFAULT_BAUDRATE,
        timeout: float | None = DEFAULT_TIMEOUT,
        write_timeout: float | None = None,
    ):
        if isinstance(port, str):
            # Configure the transport without opening it.  This is not I/O:
            # serial_for_url only parses the URL and constructs the object
            # (no fd, no socket).  It returns a pyserial port or, for bt://,
            # a BtSerial registered as a pyserial URL handler.
            # Without an explicit timeout pyserial would use timeout=None, and
            # a silent device would block read() forever.  BtSerial takes the
            # same arguments; its baudrate only drives Modbus timing.
            self.port: serial.SerialBase = serial.serial_for_url(
                port,
                baudrate=baudrate,
                timeout=timeout,
                write_timeout=write_timeout,
                do_not_open=True,
            )
        else:
            self.port = port
        self.address = address
        self.instrument: minimalmodbus.Instrument | None = None

    @override
    def __str__(self) -> str:
        port = self.port
        name = port.port if port.port is not None else "?"
        return f"{name}@{self.address}"

    @override
    def open(self) -> Self:
        if not self.port.is_open:
            # SerialBase is the common base of every pyserial port, but it
            # does not declare open(): each concrete port class (serial.Serial,
            # the URL handlers, BtSerial) defines its own.
            cast(serial.Serial, self.port).open()
        try:
            # The instrument is built once and kept: it already points at the
            # right port with the right config, so a reopen only has to bring
            # the port back up.
            instrument = self.instrument
            if instrument is None:
                # minimalmodbus duck-types the port (open/close/read/write/
                # is_open), but its annotations name serial.Serial rather
                # than the SerialBase every pyserial port derives from.
                instrument = minimalmodbus.Instrument(
                    cast(serial.Serial, self.port),
                    self.address,
                    mode=minimalmodbus.MODE_RTU,
                    debug=False,
                )
                instrument.clear_buffers_before_each_transaction = True
                self.instrument = instrument
            return self
        except BaseException:
            # The port is closed whether this call opened it or it came in
            # open: Modbus manages its lifetime.  A port that failed to open
            # never reaches here, since port.open() is outside the try.
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
        self.port.close()
