"""Bluetooth SPP transport shaped like a pyserial port.

BtSerial.port is always a Bluetooth MAC, just as serial.Serial.port is a
device path.  URL parsing lives only in serial_urlhandler/protocol_bt.py,
which pyserial uses via serial_for_url():

    serial.serial_for_url("bt://E2:F9:C6:24:71:C8?channel=1&timeout=0.5")

Direct construction uses the MAC:

    BtSerial("E2:F9:C6:24:71:C8", channel=1, timeout=0.5)

The connect timeout is an internal constant (CONNECT_TIMEOUT), not part of the
serial interface.  For a configured but closed object use
serial_for_url(..., do_not_open=True), or BtSerial(None) and set .port before
open().
"""
import contextlib
import re
import select
import socket
import time
from typing import override

import serial

# Fixed for minimalmodbus; RFCOMM has no real baudrate.
BAUDRATE = 115200

_MAC_RE = re.compile(r"^(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$")

def parse_mac(value: str) -> str:
    value = value.strip()
    if not _MAC_RE.match(value):
        raise ValueError(f"invalid Bluetooth MAC: {value!r}")
    return value.replace("-", ":").upper()


class BtSerial(contextlib.AbstractContextManager["BtSerial"]):

    def __init__(self, 
        port: str | None = None, 
        channel: int = 1,
        timeout: float | None = 0.5,
        connect_timeout: float | None = 10
    ):
        self.port = port
        self.channel = channel
        self.sock: socket.socket | None = None
        self._buf = bytearray()
        self.timeout = timeout
        self.connect_timeout = connect_timeout
        if port is not None:
            self.open()

    @property
    def timeout(self) -> float | None:
        return self._timeout

    @timeout.setter
    def timeout(self, value: float | None) -> None:
        if value is not None:
            try:
                value + 1  # numeric check, like pyserial
            except TypeError:
                raise ValueError(f"Not a valid timeout: {value!r}") from None
            if value < 0:
                raise ValueError(f"Not a valid timeout: {value!r}")
        self._timeout = value
        if self.sock is not None:
            self.sock.settimeout(value)

    @property
    def baudrate(self) -> int:
        # minimalmodbus reads this to calculate the 3.5-character silent
        # period; RFCOMM itself has no baudrate setting.
        return BAUDRATE

    @property
    def is_open(self) -> bool:
        return self.sock is not None

    # -- pyserial-compatible lifecycle ------------------------------------
    def ensure_opened(self) -> socket.socket:
        sock = self.sock
        if sock is None:
            raise serial.SerialException("Bluetooth socket is closed")
        return sock

    def open(self) -> None:
        if self.is_open:
            raise serial.SerialException("Port is already open.")
        if self.port is None:
            raise serial.SerialException("Port must be configured before it can be used.")

        try:
            mac = parse_mac(str(self.port))
        except ValueError as exc:
            raise serial.SerialException(str(exc)) from exc
        channel = int(self.channel)
        if not 1 <= channel <= 30:
            raise ValueError(f"Bluetooth channel must be 1..30, got {channel}")

        sock = socket.socket(
            socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM
        )
        try:
            sock.settimeout(self.connect_timeout)
            sock.connect((mac, channel))
            sock.settimeout(self.timeout)
        except Exception:
            sock.close()
            raise

        self.sock = sock
        self.mac = mac
        self.channel = channel
        self._buf.clear()

    def close(self) -> None:
        sock = self.sock
        self.sock = None
        if sock is not None:
            sock.close()

    def __del__(self):
        with contextlib.suppress(Exception):
            self.close()

    @override
    def __exit__(self, *_):
        self.close()

    # -- pyserial-like I/O ------------------------------------------------
    def write(self, data: bytes) -> int:
        sock = self.ensure_opened()
        sock.sendall(bytes(data))
        return len(data)

    def read(self, size: int = 1) -> bytes:
        sock = self.ensure_opened()
        if size <= 0:
            return b""

        if self.timeout is None:
            # pyserial semantics: None means blocking until size bytes or EOF.
            while len(self._buf) < size:
                chunk = sock.recv(size - len(self._buf))
                if not chunk:
                    raise serial.SerialException("Bluetooth peer closed the link")
                self._buf.extend(chunk)
            out = bytes(self._buf[:size])
            del self._buf[:size]
            return out

        if self.timeout == 0:
            # pyserial semantics: return immediately with what is available.
            try:
                chunk = sock.recv(size - len(self._buf), socket.MSG_DONTWAIT)
                if chunk:
                    self._buf.extend(chunk)
            except BlockingIOError:
                pass
            except OSError as exc:
                raise serial.SerialException(str(exc)) from exc
            out = bytes(self._buf[:size])
            del self._buf[:size]
            return out

        # timeout > 0: the timeout is for the whole call (pyserial semantics).
        # select() waits for readability with the time left, so the socket
        # timeout is never touched and recv() cannot block past the deadline.
        deadline = time.monotonic() + self.timeout
        while len(self._buf) < size:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if not select.select([sock], [], [], remaining)[0]:
                break
            chunk = sock.recv(size - len(self._buf))
            if not chunk:
                raise serial.SerialException("Bluetooth peer closed the link")
            self._buf.extend(chunk)

        out = bytes(self._buf[:size])
        del self._buf[:size]
        return out

    def reset_input_buffer(self) -> None:
        sock = self.ensure_opened()
        self._buf.clear()
        # Zero-timeout poll: recv() after a readable select() returns at once,
        # so the socket timeout is never touched.
        while select.select([sock], [], [], 0)[0]:
            if not sock.recv(4096):
                break

    def reset_output_buffer(self) -> None:
        pass

    def flush(self) -> None:
        pass


