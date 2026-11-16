"""Build a tmodbus client from a serial path or a Bluetooth LE URL.

A ``bt://`` URL passes everything after the scheme to bleak as the BLE
address.  Bleak itself understands MAC addresses and CoreBluetooth UUIDs.

Link settings such as ``connect_timeout`` are regular arguments of
:meth:`riden.Riden.connect`, not URL parameters.
"""

from typing import Protocol

from bleak.backends.device import BLEDevice
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_fixed
from tmodbus import AsyncModbusClient, create_async_rtu_client
from tmodbus.transport import AsyncBaseTransport
from tmodbus.transport.async_smart import AsyncSmartTransport

from .ble import BleTransport


class ModbusClient(Protocol):
    """Minimal tmodbus client surface used by Riden."""

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def read_holding_registers(self, start_address: int, quantity: int) -> list[int]: ...

    async def write_multiple_registers(self, start_address: int, values: list[int]) -> int: ...


DEFAULT_BAUDRATE = 115200
DEFAULT_TIMEOUT = 1
DEFAULT_CONNECT_TIMEOUT = 10.0
DEFAULT_DELAY = 0.02
DEFAULT_RESPONSE_RETRY = AsyncRetrying(
    retry=retry_if_exception_type(TimeoutError),
    stop=stop_after_attempt(3),
    wait=wait_fixed(0.2),
)
BT_PREFIX = "bt://"

type ClientSource = str | ModbusClient | AsyncBaseTransport | BLEDevice


def make_client(
    port: ClientSource,
    address: int = 1,
    *,
    baudrate: int = DEFAULT_BAUDRATE,
    timeout: float | None = DEFAULT_TIMEOUT,
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
    delay: float = DEFAULT_DELAY,
    auto_reconnect: bool = True,
    response_retry: AsyncRetrying | None = DEFAULT_RESPONSE_RETRY
) -> ModbusClient:
    """Return a configured client; construction performs no I/O.

    A path or a ``serialx`` URL creates an async RTU client.  A ``bt://`` URL
    creates a BLE transport wrapped in tmodbus's smart transport for pacing
    and reconnect.  An already constructed client is returned unchanged,
    which keeps tests and custom transports easy.
    """
    response_timeout = DEFAULT_TIMEOUT if timeout is None else timeout

    if isinstance(port, str):
        port = port.strip()
        if not port.lower().startswith(BT_PREFIX):
            return create_async_rtu_client(
                port,
                unit_id=address,
                baudrate=baudrate,
                timeout=response_timeout,
                connect_timeout=connect_timeout,
                wait_between_requests=delay,
                auto_reconnect=auto_reconnect,
            )

        target = port[len(BT_PREFIX):].strip()
        if not target:
            raise ValueError(f"no Bluetooth address in URL: {port!r}")
        port = target

    if isinstance(port, (str, BLEDevice)):
        port = BleTransport(
            port,
            timeout=response_timeout,
            connect_timeout=connect_timeout,
        )

    if not isinstance(port, AsyncBaseTransport):
        return port

    if response_retry is not None or delay > 0 or auto_reconnect:
        port = AsyncSmartTransport(
            port,
            wait_between_requests=delay,
            auto_reconnect=auto_reconnect,
            response_retry_strategy=response_retry,
        )

    return AsyncModbusClient(port, unit_id=address)
