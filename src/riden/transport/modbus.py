"""Modbus transport factory for Riden.

The class here owns only the transport details: a pyserial-like port, the
minimalmodbus instrument and buffer handling.  Device semantics (registers,
model, properties) live in Riden; transaction pacing lives in
DelayedTransport.
"""

import minimalmodbus
import serial

from ..bt import BtSerial
from .transport import Transport


class Modbus(Transport[minimalmodbus.Instrument]):
    """Create a minimalmodbus client for one pyserial-like port.

    Construction configures the transport but does not open it: a string is
    resolved with serial_for_url(..., do_not_open=True), which creates no fd
    and no socket.  open() opens the port if needed and builds the instrument;
    close(obj) closes the port.
    """

    def __init__(
        self,
        port: serial.Serial | BtSerial | str,
        address: int = 1
    ):
        if isinstance(port, str):
            # Configure the transport without opening it.  This is not I/O:
            # serial_for_url only parses the URL and constructs the object
            # (no fd, no socket).
            port = serial.serial_for_url(port, do_not_open=True)
            self.owns_port = True
        else:
            self.owns_port = not port.is_open
        self.port = port
        self.address = address

    def open(self) -> minimalmodbus.Instrument:
        try:
            if self.owns_port:
                self.port.open()
            modbus = minimalmodbus.Instrument(self.port, self.address, mode=minimalmodbus.MODE_RTU, debug=False)
            modbus.clear_buffers_before_each_transaction = True
            return modbus
        except BaseException:
            if self.owns_port:
                self.port.close()
            raise

    def close(self, _: minimalmodbus.Instrument) -> None:
        if self.owns_port:
            self.port.close()
