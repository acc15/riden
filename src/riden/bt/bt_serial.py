"""Bluetooth Low Energy serial port for pyserial.

BtSerial is a serial.SerialBase subclass, like pyserial's own URL handlers
(socket://, rfc2217://): it has the full pyserial API, and settings,
validation and defaults all come from SerialBase.  BtSerial.port is a BLE
address or a device name, just as serial.Serial.port is a device path.  URL
parsing lives only in protocol_bt.py, which pyserial uses via
serial_for_url():

    serial.serial_for_url("bt://E1:F9:C6:24:71:C8", timeout=0.5)

Direct construction takes the BLE address or name:

    BtSerial("E1:F9:C6:24:71:C8", timeout=0.5)
    BtSerial("RK6006", timeout=0.5)

The device is a transparent UART: Modbus RTU frames are written to the
``FFE2`` characteristic and replies arrive as notifications from ``FFE1``
(service ``FFE0``).  That is the layout used by the Riden RK6006/RK6012
Bluetooth module and by the vendor's iOS app.

``bleak`` is asynchronous, while pyserial is synchronous.  A private thread
runs an asyncio event loop and one long-lived ``BleakClient``; ``open()``,
``read()`` and ``write()`` submit work to that loop and wait for the result.
The public class therefore behaves like a normal blocking serial port.

The BLE address is not the Classic SPP MAC.  On the tested RK6006/RK6012
modules the BLE address is the Classic MAC - 1, but a device name or a BLE
scan is more reliable.
"""

import asyncio
import contextlib
import io
import math
import re
import threading
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any, override

import serial
from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError
from serial import PortNotOpenError, SerialException, SerialTimeoutException, Timeout

# Riden's BLE UART: FFE2 carries writes, FFE1 delivers notifications.
NOTIFY_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"
WRITE_UUID = "0000ffe2-0000-1000-8000-00805f9b34fb"

# ATT's default payload.  Riden's normal Modbus writes fit in one chunk (a
# five-register preset is 19 bytes), which keeps a frame from being split
# across BLE connection intervals.
_CHUNK_SIZE = 20

_MAC_RE = re.compile(r"^(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$")


def parse_mac(value: str) -> str:
    value = value.strip()
    if not _MAC_RE.match(value):
        raise ValueError(f"invalid Bluetooth MAC: {value!r}")
    return value.replace("-", ":").upper()


class BtSerial(serial.SerialBase):
    """pyserial port over a BLE UART (transparent Modbus RTU bridge).

    Positional and pyserial keyword arguments go to SerialBase unchanged,
    with its defaults.  ``connect_timeout``, ``notify_uuid`` and
    ``write_uuid`` are BLE link settings and keyword-only.
    """

    def __init__(
        self,
        *args: Any,
        connect_timeout: float | None = 10,
        notify_uuid: str = NOTIFY_UUID,
        write_uuid: str = WRITE_UUID,
        **kwargs: Any,
    ):
        # SerialBase.__init__ opens the port when one is given, so everything
        # the connection needs must be in place before it runs.
        self._client: BleakClient | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._rx = bytearray()
        self._cv = threading.Condition()
        self._error: str | None = None
        self._closing = False
        self._write_lock = threading.Lock()
        self.connect_timeout = connect_timeout
        self.notify_uuid = notify_uuid
        self.write_uuid = write_uuid
        super().__init__(*args, **kwargs)

    # -- lifecycle --------------------------------------------------------
    def _require_open(self) -> None:
        if not self.is_open or self._client is None:
            raise PortNotOpenError()

    def _require_loop(self) -> asyncio.AbstractEventLoop:
        loop = self._loop
        if loop is None or loop.is_closed():
            raise PortNotOpenError()
        return loop

    def _start_loop(self) -> None:
        loop = asyncio.new_event_loop()
        ready = threading.Event()

        def run() -> None:
            asyncio.set_event_loop(loop)
            ready.set()
            loop.run_forever()
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()

        thread = threading.Thread(
            target=run, name=f"BtSerial({self._port})", daemon=True
        )
        self._loop = loop
        self._thread = thread
        thread.start()
        ready.wait()

    def _stop_loop(self) -> None:
        loop = self._loop
        thread = self._thread
        self._loop = None
        self._thread = None
        if loop is not None:
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(loop.stop)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)

    def open(self) -> None:
        if self._port is None:
            raise SerialException("Port must be configured before it can be used.")
        if self.is_open:
            raise SerialException("Port is already open.")

        self._closing = False
        with self._cv:
            self._rx.clear()
            self._error = None

        self._start_loop()
        future = None
        try:
            future = asyncio.run_coroutine_threadsafe(self._connect(), self._require_loop())
            # Bleak enforces connect_timeout for the scan and for the connect.
            # Wait for both plus a margin, so a specific error (device not
            # found, D-Bus failure) wins over a generic timeout.
            outer = None if self.connect_timeout is None else self.connect_timeout * 2 + 1
            future.result(timeout=outer)
        except FutureTimeoutError as exc:
            if future is not None:
                future.cancel()
            self._stop_loop()
            raise SerialException(
                f"Bluetooth connect timed out after {self.connect_timeout} s"
            ) from exc
        except SerialException:
            self._stop_loop()
            raise
        except Exception as exc:
            self._stop_loop()
            raise SerialException(f"Bluetooth connect failed: {exc}") from exc

        self.is_open = True

    async def _connect(self) -> None:
        port = str(self._port).strip()
        timeout = math.inf if self.connect_timeout is None else self.connect_timeout
        if _MAC_RE.match(port):
            address = parse_mac(port)
            device = await BleakScanner.find_device_by_address(address, timeout=timeout)
            if device is None:
                raise SerialException(f"Bluetooth device not found: {address!r}")
        else:
            device = await BleakScanner.find_device_by_name(port, timeout=timeout)
            if device is None:
                raise SerialException(f"Bluetooth device not found: {port!r}")

        # Pass the scanned BLEDevice, not the address string: BleakClient then
        # uses the D-Bus object found by this scan and does not scan again.
        client = BleakClient(
            device,
            disconnected_callback=self._on_disconnect,
            timeout=math.inf if self.connect_timeout is None else self.connect_timeout,
        )
        try:
            await client.connect()
            await client.start_notify(self.notify_uuid, self._on_notify)
        except BaseException:
            with contextlib.suppress(BleakError, RuntimeError):
                await client.disconnect()
            raise
        self._client = client

    @override
    def close(self) -> None:
        client = self._client
        self._client = None
        self.is_open = False
        with self._cv:
            self._closing = True
            self._cv.notify_all()

        loop = self._loop
        if client is not None and loop is not None and loop.is_running():
            if threading.current_thread() is self._thread:
                asyncio.ensure_future(client.disconnect())
            else:
                future = None
                try:
                    future = asyncio.run_coroutine_threadsafe(client.disconnect(), loop)
                    future.result(timeout=5)
                except FutureTimeoutError:
                    if future is not None:
                        future.cancel()
                except (BleakError, RuntimeError):
                    pass

        self._stop_loop()
        with self._cv:
            self._rx.clear()
            self._closing = False

    def _reconfigure_port(self) -> None:
        """SerialBase hook for setting changes; BLE has nothing to apply."""

    # -- connection callbacks --------------------------------------------
    def _on_notify(self, _sender: Any, data: bytearray) -> None:
        with self._cv:
            if self._closing:
                return
            self._rx.extend(data)
            self._cv.notify_all()

    def _on_disconnect(self, _client: BleakClient) -> None:
        with self._cv:
            if not self._closing:
                self._error = "Bluetooth peer closed the link"
            self._cv.notify_all()

    def _write_done(self, future: Future[None]) -> None:
        if future.cancelled():
            return
        exc = future.exception()
        if exc is None:
            return
        with self._cv:
            if not self._closing and self._error is None:
                self._error = f"write failed: {exc}"
                self._cv.notify_all()

    # -- I/O --------------------------------------------------------------
    @property
    def in_waiting(self) -> int:
        """Number of received bytes not read yet."""
        self._require_open()
        with self._cv:
            return len(self._rx)

    @override
    def read(self, size: int = 1) -> bytes:
        self._require_open()
        if size <= 0:
            return b""

        read = bytearray()
        timeout = Timeout(self._timeout)
        while len(read) < size:
            wait = timeout.time_left()
            # pyserial semantics: once data has started to arrive, a gap
            # longer than inter_byte_timeout ends the read.
            inter = self._inter_byte_timeout
            if inter is not None and read:
                wait = inter if wait is None else min(wait, inter)

            with self._cv:
                if not self._rx:
                    if self._error is not None:
                        raise SerialException(self._error)
                    if wait == 0:
                        break
                    if not self._cv.wait(wait) and not self._rx:
                        break
                if not self.is_open:
                    raise PortNotOpenError()
                if self._error is not None and not self._rx:
                    raise SerialException(self._error)
                take = min(size - len(read), len(self._rx))
                read += self._rx[:take]
                del self._rx[:take]

            if timeout.expired():
                break
        return bytes(read)

    @override
    def write(self, data: Any) -> int:
        self._require_open()
        payload = bytes(serial.to_bytes(data))
        if not payload:
            return 0

        timeout = Timeout(self._write_timeout)
        if timeout.is_non_blocking:
            # pyserial semantics: write what fits, return the count.  A GATT
            # write is atomic, so either the whole frame is queued or 0.
            if not self._write_lock.acquire(blocking=False):
                return 0
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self._write(payload), self._require_loop()
                )
            finally:
                self._write_lock.release()
            future.add_done_callback(self._write_done)
            return len(payload)

        with self._write_lock:
            future = asyncio.run_coroutine_threadsafe(
                self._write(payload), self._require_loop()
            )
            try:
                future.result(timeout=timeout.time_left())
            except FutureTimeoutError as exc:
                future.cancel()
                raise SerialTimeoutException("Write timeout") from exc
            except SerialException:
                raise
            except Exception as exc:
                raise SerialException(f"write failed: {exc}") from exc
        return len(payload)

    async def _write(self, payload: bytes) -> None:
        client = self._client
        if client is None:
            raise SerialException("port is not open")
        for offset in range(0, len(payload), _CHUNK_SIZE):
            await client.write_gatt_char(
                self.write_uuid,
                payload[offset : offset + _CHUNK_SIZE],
                response=False,
            )

    @override
    def flush(self) -> None:
        """Nothing to drain: write() waits for the GATT write to complete."""
        self._require_open()

    def reset_input_buffer(self) -> None:
        self._require_open()
        with self._cv:
            self._rx.clear()

    def reset_output_buffer(self) -> None:
        self._require_open()

    # -- modem lines: BLE has none, handled as in pyserial's socket:// ----
    @override
    def send_break(self, duration: float = 0.25) -> None:
        self._require_open()

    def _update_break_state(self) -> None:
        pass

    def _update_rts_state(self) -> None:
        pass

    def _update_dtr_state(self) -> None:
        pass

    @property
    def cts(self) -> bool:
        self._require_open()
        return True

    @property
    def dsr(self) -> bool:
        self._require_open()
        return True

    @property
    def ri(self) -> bool:
        self._require_open()
        return False

    @property
    def cd(self) -> bool:
        self._require_open()
        return True

    @override
    def fileno(self) -> int:
        raise io.UnsupportedOperation("BLE port has no file descriptor")
