"""Tests for the Layout helpers that plan I/O."""

from types import MappingProxyType
from typing import Any

import pytest

from riden.field import Field
from riden.layout import Layout
from riden.register import Register, Registers
from riden.spec import read_flag, read_int, write_int


def layout_of(registers: dict[Field, Register]) -> Layout:
    return Layout(MappingProxyType(registers))


def test_layout_readers_collects_codecs() -> None:
    layout = layout_of(
        {
            Field.V: Register(10, 1, read_int),
            Field.P: Register(12, 2, read_int),
        }
    )
    readers = layout.readers([Field.V, Field.P])
    assert set(readers) == {Field.V, Field.P}
    assert readers[Field.V] is layout.registers[Field.V].read


def test_layout_readers_raises_on_unreadable() -> None:
    layout = layout_of({Field.V: Register(10, 1, None)})
    with pytest.raises(ValueError, match="not readable"):
        layout.readers([Field.V])


def test_layout_writers_collects_and_validates() -> None:
    layout = layout_of(
        {
            Field.V: Register(10, 1, read_int, write_int),
            Field.P: Register(12, 2, read_int),
        }
    )
    writers = layout.writers([Field.V])
    assert set(writers) == {Field.V}
    assert writers[Field.V] is layout.registers[Field.V].write

    with pytest.raises(ValueError, match="not writable"):
        layout.writers([Field.P])

    with pytest.raises(ValueError, match="not supported"):
        layout.writers([Field.I])


def test_layout_decode() -> None:
    layout = layout_of(
        {
            Field.V: Register(10, 1, read_int),
            Field.P: Register(12, 2, read_int),
        }
    )
    readers = layout.readers([Field.V, Field.P])
    regs = [0] * 14
    regs[10] = 42
    regs[12] = 7
    regs[13] = 8
    values = layout.decode(tuple(regs), 0, readers)
    assert values == {"v": 42, "p": 7}


def test_layout_encode() -> None:
    layout = layout_of({Field.V: Register(10, 1, read_int, write_int)})
    writers = layout.writers([Field.V])
    values_by_field = {"v": 42}
    encoded = layout.encode({Field.V: 42}, writers, values_by_field)
    assert encoded == {Field.V: (42,)}

    with pytest.raises(ValueError, match="produced 1 registers, expected 2"):
        layout2 = layout_of({Field.V: Register(10, 2, read_int, write_int)})
        writers2 = layout2.writers([Field.V])
        layout2.encode({Field.V: 42}, writers2, {"v": 42})

    with pytest.raises(ValueError, match="out-of-range"):
        layout3 = layout_of({Field.V: Register(10, 1, read_int, write_int)})
        writers3 = layout3.writers([Field.V])
        layout3.encode({Field.V: 70000}, writers3, {"v": 70000})

    def write_virtual(_: Any, __: Any) -> Registers:
        return ()

    layout4 = layout_of({Field.M0_I_RANGE: Register(0, 0, read_flag, write_virtual)})
    writers4 = layout4.writers([Field.M0_I_RANGE])
    encoded4 = layout4.encode({Field.M0_I_RANGE: True}, writers4, {"m0_i_range": True})
    assert encoded4 == {}