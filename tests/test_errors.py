"""Tests for transport error classification."""

import errno

import minimalmodbus
import pytest
import serial

from riden.transport.errors import is_link_error


@pytest.mark.parametrize(
    "exc",
    [
        minimalmodbus.SlaveReportedException("device says no"),
        minimalmodbus.SlaveDeviceBusyError("busy"),
        minimalmodbus.NegativeAcknowledgeError("nack"),
        minimalmodbus.IllegalRequestError("illegal"),
    ],
)
def test_slave_errors_are_not_link_errors(exc: BaseException) -> None:
    assert is_link_error(exc) is False


@pytest.mark.parametrize(
    "exc",
    [
        minimalmodbus.NoResponseError("no response"),
        minimalmodbus.InvalidResponseError("bad crc"),
        serial.SerialException("port gone"),
        TimeoutError("timed out"),
        ConnectionError("reset"),
        ConnectionResetError("reset"),
        OSError(errno.ETIMEDOUT, "timed out"),
        OSError(errno.ENODEV, "gone"),
    ],
)
def test_transport_errors_are_link_errors(exc: BaseException) -> None:
    assert is_link_error(exc) is True


@pytest.mark.parametrize(
    "exc",
    [
        ValueError("nope"),
        OSError(errno.ENOENT, "no such file"),
    ],
)
def test_unrelated_errors_are_not_link_errors(exc: BaseException) -> None:
    assert is_link_error(exc) is False
