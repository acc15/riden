"""Bluetooth SPP (RFCOMM) port for pyserial.

BtSerial is a serial.SerialBase subclass, like pyserial's own URL handlers
(socket://, rfc2217://): it has the full pyserial API, and settings,
validation and defaults all come from SerialBase.  BtSerial.port is a
Bluetooth MAC, just as serial.Serial.port is a device path.  URL parsing
lives only in protocol_bt.py, which pyserial uses via serial_for_url():

    serial.serial_for_url("bt://E2:F9:C6:24:71:C8?channel=1", timeout=0.5)

Direct construction uses the MAC:

    BtSerial("E2:F9:C6:24:71:C8", channel=1, timeout=0.5)

The URL carries only link settings (channel, connect_timeout, security);
everything else is a regular pyserial argument with pyserial semantics.
``timeout``, ``write_timeout`` and ``inter_byte_timeout`` are enforced with
select(); the socket itself is always blocking after connect().  Serial line
settings (baudrate, bytesize, parity, ...) mean nothing to RFCOMM and are
accepted but ignored, except that minimalmodbus derives its inter-frame
silence from ``baudrate``.
"""
import errno
import fcntl
import re
import select
import socket
import struct
import termios
from enum import IntEnum
from typing import Any, override

import serial
from serial import PortNotOpenError, SerialException, SerialTimeoutException, Timeout

# Python's socket module does not export these.
SOL_BLUETOOTH = 274
BT_SECURITY = 4

# Transient errnos: the same call can simply be retried.
_RETRY_ERRNOS = frozenset({errno.EAGAIN, errno.EWOULDBLOCK, errno.EINTR})


class SecurityLevel(IntEnum):
    """RFCOMM security levels (BT_SECURITY_* from <bluetooth/bluetooth.h>).

    MEDIUM (authenticated + encrypted) is the default: some SPP modules (seen
    on Riden RK6012) drop an idle unencrypted link after ~10 s with a
    supervision timeout, while an encrypted one stays up.
    """

    SDP = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    FIPS = 4

_MAC_RE = re.compile(r"^(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$")

def parse_mac(value: str) -> str:
    value = value.strip()
    if not _MAC_RE.match(value):
        raise ValueError(f"invalid Bluetooth MAC: {value!r}")
    return value.replace("-", ":").upper()


class BtSerial(serial.SerialBase):
    """pyserial port over an RFCOMM socket.

    Positional and pyserial keyword arguments go to SerialBase unchanged,
    with its defaults; ``channel``, ``connect_timeout`` and ``security`` are
    RFCOMM link settings and keyword-only.
    """

    def __init__(
        self,
        *args: Any,
        channel: int = 1,
        connect_timeout: float | None = 10,
        security: SecurityLevel = SecurityLevel.MEDIUM,
        **kwargs: Any,
    ):
        # SerialBase.__init__ opens the port when one is given, so the link
        # settings must be in place before it runs.
        self.sock: socket.socket | None = None
        self.channel = channel
        self.connect_timeout = connect_timeout
        self.security = security
        super().__init__(*args, **kwargs)

    def _require_sock(self) -> socket.socket:
        sock = self.sock
        if sock is None:
            raise PortNotOpenError()
        return sock

    # -- lifecycle --------------------------------------------------------
    def open(self) -> None:
        if self._port is None:
            raise SerialException("Port must be configured before it can be used.")
        if self.is_open:
            raise SerialException("Port is already open.")

        try:
            mac = parse_mac(str(self._port))
        except ValueError as exc:
            raise SerialException(str(exc)) from exc
        channel = self.channel
        if not 1 <= channel <= 30:
            raise ValueError(f"Bluetooth channel must be 1..30, got {channel}")

        sock = socket.socket(
            socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM
        )
        try:
            sock.setsockopt(SOL_BLUETOOTH, BT_SECURITY, bytes((self.security, 0)))
            sock.settimeout(self.connect_timeout)
            sock.connect((mac, channel))
            # Blocking from here on: read() and write() enforce the pyserial
            # timeouts with select(), so changing them never touches the socket.
            sock.settimeout(None)
        except BaseException:
            sock.close()
            raise

        self.sock = sock
        self.is_open = True

    @override
    def close(self) -> None:
        sock = self.sock
        self.sock = None
        self.is_open = False
        if sock is not None:
            sock.close()

    def _reconfigure_port(self) -> None:
        """SerialBase hook for setting changes; RFCOMM has nothing to apply."""

    # -- I/O --------------------------------------------------------------
    @property
    def in_waiting(self) -> int:
        """Number of received bytes not read yet."""
        sock = self._require_sock()
        buf = fcntl.ioctl(sock.fileno(), termios.FIONREAD, struct.pack("i", 0))
        return struct.unpack("i", buf)[0]

    @override
    def read(self, size: int = 1) -> bytes:
        sock = self._require_sock()
        read = bytearray()
        timeout = Timeout(self._timeout)
        while len(read) < size:
            wait = timeout.time_left()
            # pyserial semantics: once data has started to arrive, a gap
            # longer than inter_byte_timeout ends the read.
            inter = self._inter_byte_timeout
            if inter is not None and read:
                wait = inter if wait is None else min(wait, inter)
            try:
                # select() waits with the time left, so recv() on the
                # blocking socket returns at once and cannot pass the deadline.
                if not select.select([sock], [], [], wait)[0]:
                    break
                chunk = sock.recv(size - len(read))
            except OSError as exc:
                if exc.errno in _RETRY_ERRNOS:
                    continue
                raise SerialException(f"read failed: {exc}") from exc
            if not chunk:
                raise SerialException("Bluetooth peer closed the link")
            read.extend(chunk)
            if timeout.expired():
                break
        return bytes(read)

    @override
    def write(self, data: Any) -> int:
        sock = self._require_sock()
        view = memoryview(serial.to_bytes(data))
        timeout = Timeout(self._write_timeout)
        if timeout.is_non_blocking:
            # pyserial semantics: write what fits, return the count.
            try:
                return sock.send(view, socket.MSG_DONTWAIT)
            except BlockingIOError:
                return 0
            except OSError as exc:
                raise SerialException(f"write failed: {exc}") from exc

        # SerialException derives from OSError, so the timeouts are raised
        # outside the try block, which only wraps the socket call.
        sent = 0
        while sent < len(view):
            if not select.select([], [sock], [], timeout.time_left())[1]:
                raise SerialTimeoutException("Write timeout")
            try:
                sent += sock.send(view[sent:], socket.MSG_DONTWAIT)
            except BlockingIOError:
                pass
            except OSError as exc:
                if exc.errno not in _RETRY_ERRNOS:
                    raise SerialException(f"write failed: {exc}") from exc
            if sent < len(view) and timeout.expired():
                raise SerialTimeoutException("Write timeout")
        return sent

    @override
    def flush(self) -> None:
        """Nothing to drain: send() has already handed the data to the kernel."""
        self._require_sock()

    def reset_input_buffer(self) -> None:
        sock = self._require_sock()
        # Zero-timeout poll: recv() after a readable select() returns at once.
        while select.select([sock], [], [], 0)[0]:
            if not sock.recv(4096):
                break

    def reset_output_buffer(self) -> None:
        self._require_sock()

    # -- modem lines: RFCOMM has none, handled as in socket:// --------------
    @override
    def send_break(self, duration: float = 0.25) -> None:
        self._require_sock()

    def _update_break_state(self) -> None:
        pass

    def _update_rts_state(self) -> None:
        pass

    def _update_dtr_state(self) -> None:
        pass

    @property
    def cts(self) -> bool:
        self._require_sock()
        return True

    @property
    def dsr(self) -> bool:
        self._require_sock()
        return True

    @property
    def ri(self) -> bool:
        self._require_sock()
        return False

    @property
    def cd(self) -> bool:
        self._require_sock()
        return True

    @override
    def fileno(self) -> int:
        return self._require_sock().fileno()
