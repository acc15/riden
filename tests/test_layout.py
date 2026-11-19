"""Tests for the Layout helpers that plan I/O."""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

import pytest

from riden.field import Field, FieldRef
from riden.layout import Layout
from riden.register import Register, Registers
from riden.spec import read_single, write_int


def layout_of(registers: dict[Field, Register]) -> Layout:
    return Layout(MappingProxyType(registers))


def test_layout_readers_collects_codecs() -> None:
    layout = layout_of(
        {
            Field.V: Register(10, 1, read_single(int)),
            Field.P: Register(12, 2, read_single(int)),
        }
    )
    readers = layout.readers([FieldRef(Field.V), FieldRef(Field.P)])
    assert set(readers) == {Field.V, Field.P}
    assert readers[FieldRef(Field.V)] is layout.registers[Field.V].read


def test_layout_readers_raises_on_unreadable() -> None:
    layout = layout_of({Field.V: Register(10, 1, None)})
    with pytest.raises(ValueError, match="not readable"):
        layout.readers([FieldRef(Field.V)])


def test_layout_writers_collects_and_validates() -> None:
    layout = layout_of(
        {
            Field.V: Register(10, 1, read_single(int), write_int),
            Field.P: Register(12, 2, read_single(int)),
        }
    )
    writers = layout.writers([FieldRef(Field.V)])
    assert set(writers) == {Field.V}
    assert writers[FieldRef(Field.V)] is layout.registers[Field.V].write

    with pytest.raises(ValueError, match="not writable"):
        layout.writers([FieldRef(Field.P)])

    with pytest.raises(ValueError, match="not supported"):
        layout.writers([FieldRef(Field.I)])


def test_layout_decode() -> None:
    layout = layout_of(
        {
            Field.V: Register(10, 1, read_single(int)),
            Field.P: Register(12, 2, read_single(int)),
        }
    )
    readers = layout.readers([FieldRef(Field.V), FieldRef(Field.P)])
    regs = [0] * 14
    regs[10] = 42
    regs[12] = 7
    regs[13] = 8
    values = layout.decode(readers, tuple(regs), 0)
    assert values == {Field.V: 42, Field.P: 7}


def test_layout_decode_seeds_dependency_values() -> None:
    def read_scale(_: Registers, deps: Mapping[Field, Any]) -> int:
        return 10000 if deps[Field.I_RANGE] else 1000

    layout = layout_of(
        {
            Field.V_MAX: Register(
                0, 0, read_scale, deps={Field.I_RANGE: Field.I_RANGE}
            ),
            Field.I_RANGE: Register(20, 1, read_single(bool)),
        }
    )
    readers = layout.readers([FieldRef(Field.V_MAX)])
    assert layout.decode(readers, (), 0, initial={FieldRef(Field.I_RANGE): 1}) == {
        Field.I_RANGE: 1,
        Field.V_MAX: 10000,
    }
    assert layout.decode(readers, (), 0, initial={FieldRef(Field.I_RANGE): 0}) == {
        Field.I_RANGE: 0,
        Field.V_MAX: 1000,
    }


def test_layout_decode_overrides_initial_values() -> None:
    layout = layout_of({Field.V: Register(10, 1, read_single(int))})
    readers = layout.readers([FieldRef(Field.V)])
    values = layout.decode(readers, (42,), 10, initial={FieldRef(Field.V): 0})
    assert values == {Field.V: 42}


def test_layout_encode() -> None:
    layout = layout_of({Field.V: Register(10, 1, read_single(int), write_int)})
    writers = layout.writers([FieldRef(Field.V)])
    dependencies = {FieldRef(Field.V): 42}
    encoded = layout.encode(writers, {FieldRef(Field.V): 42}, dependencies)
    assert encoded == {Field.V: (42,)}

    with pytest.raises(ValueError, match="produced 1 registers, expected 2"):
        layout2 = layout_of({Field.V: Register(10, 2, read_single(int), write_int)})
        writers2 = layout2.writers([FieldRef(Field.V)])
        layout2.encode(
            writers2,
            {FieldRef(Field.V): 42},
            {FieldRef(Field.V): 42},
        )

    with pytest.raises(ValueError, match="out-of-range"):
        layout3 = layout_of({Field.V: Register(10, 1, read_single(int), write_int)})
        writers3 = layout3.writers([FieldRef(Field.V)])
        layout3.encode(
            writers3,
            {FieldRef(Field.V): 70000},
            {FieldRef(Field.V): 70000},
        )

    def write_virtual(_: Any, __: Any) -> Registers:
        return ()

    layout4 = layout_of({Field.V_MAX: Register(0, 0, read_single(bool), write_virtual)})
    writers4 = layout4.writers([FieldRef(Field.V_MAX)])
    encoded4 = layout4.encode(
        writers4,
        {FieldRef(Field.V_MAX): True},
        {FieldRef(Field.V_MAX): True},
    )
    assert encoded4 == {}