"""Tests for the register-level transaction protocol."""

import dataclasses
from typing import Any, cast

import pytest

from riden.transport.transport import Op, Tx


def test_read_transaction() -> None:
    tx = Tx.read(10, 3)
    assert tx.op is Op.READ
    assert tx.start == 10
    assert tx.count == 3
    assert tx.data == ()


def test_write_transaction() -> None:
    tx = Tx.write(10, [1, 2, 3])
    assert tx.op is Op.WRITE
    assert tx.start == 10
    assert tx.count == 3
    assert tx.data == (1, 2, 3)
    assert isinstance(tx.data, tuple)


def test_write_accepts_any_sequence() -> None:
    assert Tx.write(0, (7,)).data == (7,)
    assert Tx.write(0, [8, 9]).data == (8, 9)


def test_transactions_are_frozen() -> None:
    tx = Tx.read(0, 1)
    mutable = cast(Any, tx)
    with pytest.raises(dataclasses.FrozenInstanceError):
        mutable.start = 1


def test_operations_are_distinct() -> None:
    assert Op.READ is not Op.WRITE
    assert {Op.READ, Op.WRITE} == {Op.READ, Op.WRITE}
