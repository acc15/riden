"""A model's read-only register map and the helpers that plan I/O."""

from collections.abc import Callable, Iterable, Iterator, Mapping
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from functools import reduce
from graphlib import CycleError, TopologicalSorter
from types import MappingProxyType
from typing import Any

from .field import Field, FieldAny, PresetField, PresetParam
from .register import DepTarget, LocatedRegister, Register, Registers, RegRead, RegWrite


def _ordered[Node](
    graph: Mapping[Node, set[Node]],
    label: Callable[[Node], str],
) -> list[Node]:
    """Return the graph's nodes, dependencies first.

    ``graph`` maps a node to the nodes it depends on.  A cycle is reported as
    a ``ValueError`` naming its nodes through ``label``: the field graph and
    the block graph both need it, and only the node names differ.
    """
    try:
        return list(TopologicalSorter(graph).static_order())
    except CycleError as exc:
        cycle = " -> ".join(label(node) for node in exc.args[1])
        raise ValueError(f"cyclic field dependencies: {cycle}") from exc


@dataclass(frozen=True, slots=True)
class PresetLayout:
    """The sliding template of all presets and its resolved addresses.

    ``template`` maps a preset parameter to a register whose ``addr`` is
    relative to the start of one preset.  ``stride`` is the distance between
    two consecutive preset starts.
    """

    base: int = 80
    count: int = 0
    stride: int = 0
    template: Mapping[PresetParam, Register] = MappingProxyType({})

    @staticmethod
    def compute_stride(template: Mapping[PresetParam, Register]) -> int:
        return max(
            (register.addr + register.size for register in template.values() if register.size > 0),
            default=0,
        )

    def find_addr(self, field: PresetField) -> int | None:
        if not 0 <= field.num < self.count or (register := self.template.get(field.param)) is None:
            return None
        return self.base + field.num * self.stride + register.addr

    def find(self, field: PresetField) -> LocatedRegister | None:
        addr = self.find_addr(field)
        return None if addr is None else LocatedRegister(addr, self.template[field.param])


@dataclass(frozen=True, slots=True, eq=False)
class Layout:
    """Register map of one connected device.

    ``registers`` is the direct read-only map of global fields.  ``presets``
    holds the preset template and resolves a :class:`PresetField` to an
    absolute address without materializing one register per preset.  A layout
    also plans transactions: dependencies are decoded before their dependents,
    a read covers one span, and writes merge into contiguous blocks.
    """

    registers: Mapping[Field, Register]
    presets: PresetLayout = PresetLayout()

    def find(self, field: FieldAny) -> LocatedRegister | None:
        if isinstance(field, PresetField):
            return self.presets.find(field)
        register = self.registers.get(field)
        return None if register is None else LocatedRegister(register.addr, register)

    def resolve(self, field: FieldAny) -> LocatedRegister:
        if (located := self.find(field)) is None:
            raise KeyError(field.value)
        return located

    def find_addr(self, field: FieldAny) -> int | None:
        if isinstance(field, PresetField):
            return self.presets.find_addr(field)
        register = self.registers.get(field)
        return None if register is None else register.addr

    def addr(self, field: FieldAny) -> int:
        if (addr := self.find_addr(field)) is None:
            raise KeyError(field.value)
        return addr

    def fields(self) -> Iterator[FieldAny]:
        """Iterate over every field in the layout, including all presets."""
        yield from self.registers
        for num in range(self.presets.count):
            for param in self.presets.template:
                yield PresetField(num, param)

    def dep_target(self, ref: FieldAny, target: DepTarget) -> FieldAny:
        if isinstance(target, PresetParam):
            if not isinstance(ref, PresetField):
                raise TypeError("relative preset dependency outside a preset")
            return PresetField(ref.num, target)
        return target

    def deps(self, field: FieldAny) -> Mapping[Field, FieldAny]:
        """Return a field's dependencies with preset-relative targets resolved."""
        located = self.resolve(field)
        return {alias: self.dep_target(field, target) for alias, target in located.reg.deps.items()}

    def make_deps(
        self,
        field: FieldAny,
        values: Mapping[FieldAny, Any],
    ) -> dict[Field, Any]:
        """Return the dependency mapping a codec is allowed to see."""
        return {alias: values[target] for alias, target in self.deps(field).items()}

    def dependency_order(
        self,
        fields: Iterable[FieldAny],
        supplied: AbstractSet[FieldAny] = frozenset(),
    ) -> list[FieldAny]:
        """Return ``fields`` plus their transitive dependencies, dependencies first.

        The order is what decoding needs: a codec can only look at fields that
        are already decoded, so a dependency always precedes its dependents.
        Unsupported fields and dependency cycles raise ``ValueError`` before
        any I/O.

        ``supplied`` fields are used as-is, so they are neither returned nor
        descended into when reached as a dependency: ``write(i_set=1,
        i_range=0)`` must not read ``i_range``.  A supplied field that is
        itself requested still gets its direct dependencies collected, because
        it is encoded and its codec may need them.
        """
        graph: dict[FieldAny, set[FieldAny]] = {}
        seen: set[FieldAny] = set()
        supplied_refs = set(supplied)
        stack = list(fields)
        while stack:
            field = stack.pop()
            if field in seen:
                continue
            seen.add(field)

            if self.find(field) is None:
                raise ValueError(f"field {field.value} is not supported")
            deps = self.deps(field).values()
            for dep in deps:
                if self.find(dep) is None:
                    raise ValueError(
                        f"field {dep.value} is not supported (required by {field.value})"
                    )

            if field not in supplied_refs:
                graph[field] = set(deps) - supplied_refs
            stack.extend(dep for dep in deps if dep not in supplied_refs)

        return _ordered(graph, lambda field: field.value)

    def register_span(self, fields: Iterable[FieldAny]) -> tuple[int, int] | None:
        """Return the ``(start, count)`` span covering ``fields``.

        Virtual fields have size 0 and do not widen the span.  When every
        field is virtual the request needs no transaction at all, so ``None``
        is returned.  The client reads everything in one transaction.  A span
        over the protocol limit is not checked here: Modbus caps a read at
        125 registers and a write at 123, and tmodbus reports the error
        itself.
        """
        merged = reduce(
            lambda left, right: right if left is None else (
                min(left[0], right[0]),
                max(left[1], right[1]),
            ),
            (
                (located.addr, located.addr + located.reg.size)
                for field in fields
                if (located := self.resolve(field)).reg.size > 0
            ),
            None,
        )
        return None if merged is None else (merged[0], merged[1] - merged[0])

    def readers(self, fields: Iterable[FieldAny]) -> dict[FieldAny, RegRead]:
        """Collect the read codecs for ``fields``, validating readability.

        Every field must be readable; otherwise a ``ValueError`` listing all
        unreadable fields is raised before any I/O.  ``fields`` are assumed to
        be supported (use :meth:`dependency_order` first).
        """
        result: dict[FieldAny, RegRead] = {}
        not_readable: list[str] = []
        for ref in fields:
            located = self.resolve(ref)
            read = located.reg.read
            if read is None:
                not_readable.append(ref.value)
            else:
                result[ref] = read
        if not_readable:
            raise ValueError(f"fields are not readable: {', '.join(not_readable)}")
        return result

    def decode(
        self,
        readers: Mapping[FieldAny, RegRead],
        regs: Registers,
        start: int,
        initial: Mapping[FieldAny, Any] = MappingProxyType({}),
    ) -> dict[FieldAny, Any]:
        """Decode already fetched registers into field values.

        ``readers`` must be collected from fields already in dependency order;
        its keys define both the field set and that order.  ``initial`` seeds
        the decoded values, so a dependency the caller already knows need not
        be fetched.  A field present in both is decoded normally and replaces
        the seeded value.  Both the input and the result are keyed by
        :class:`FieldRef`; the public ``str`` names are applied by the client.
        """
        values: dict[FieldAny, Any] = dict(initial)
        for field, read in readers.items():
            located = self.resolve(field)
            if located.reg.size == 0:
                raw: Registers = ()
            else:
                offset = located.addr - start
                raw = regs[offset : offset + located.reg.size]
            values[field] = read(raw, self.make_deps(field, values))
        return values

    def writers(self, fields: Iterable[FieldAny]) -> dict[FieldAny, RegWrite]:
        """Collect the write codecs for ``fields``, validating support/writability.

        Unsupported fields raise ``ValueError`` first, then non-writable ones,
        matching the original behaviour.  ``fields`` are validated against the
        layout's register map.
        """
        result: dict[FieldAny, RegWrite] = {}
        unsupported: list[str] = []
        not_writable: list[str] = []
        for ref in fields:
            located = self.find(ref)
            if located is None:
                unsupported.append(ref.value)
            elif located.reg.write is None:
                not_writable.append(ref.value)
            else:
                result[ref] = located.reg.write
        if unsupported:
            raise ValueError(f"fields are not supported: {', '.join(unsupported)}")
        if not_writable:
            raise ValueError(f"fields are not writable: {', '.join(not_writable)}")
        return result

    def encode(
        self,
        writers: Mapping[FieldAny, RegWrite],
        updates: Mapping[FieldAny, Any],
        dependencies: Mapping[FieldAny, Any],
    ) -> dict[FieldAny, Registers]:
        """Encode supplied fields into register blocks.

        ``dependencies`` are decoded values keyed by :class:`FieldRef`; they
        and ``updates`` are merged before the codecs see them, so a
        caller-supplied value overrides a read one.  Per-field codec validation
        and size/range checks happen here, before anything is written.  Virtual
        fields are skipped.
        """
        values: dict[FieldAny, Any] = {**dependencies, **updates}
        encoded: dict[FieldAny, Registers] = {}
        for field, value in updates.items():
            register = self.resolve(field).reg
            try:
                regs = writers[field](value, self.make_deps(field, values))
            except ValueError as exc:
                raise ValueError(f"field {field.value}: {exc}") from exc
            if len(regs) != register.size:
                raise ValueError(
                    f"field {field.value} produced {len(regs)} registers, "
                    f"expected {register.size}"
                )
            if any(reg < 0 or reg > 0xFFFF for reg in regs):
                raise ValueError(
                    f"field {field.value} produced out-of-range registers: {regs}"
                )
            if register.size == 0:
                continue
            encoded[field] = regs
        return encoded

    def _write_predecessors(
        self,
        field: FieldAny,
        encoded: AbstractSet[FieldAny],
    ) -> set[FieldAny]:
        """Return the written fields that ``field`` transitively depends on.

        Virtual fields are never encoded, but they can have real dependencies:
        a current's scale depends on its range.  The walk passes through
        unencoded fields instead of stopping at them, so the range is still
        ordered before the current it scales.
        """
        result: set[FieldAny] = set()
        seen: set[FieldAny] = set()
        stack = list(self.deps(field).values())
        while stack:
            dep = stack.pop()
            if dep in seen:
                continue
            seen.add(dep)
            if dep in encoded:
                result.add(dep)
            else:
                located = self.find(dep)
                if located is not None:
                    stack.extend(self.deps(dep).values())
        return result

    def write_blocks(
        self,
        encoded: Mapping[FieldAny, Registers],
    ) -> list[tuple[int, Registers]]:
        """Merge encoded fields into contiguous write transactions.

        Registers that touch share one transaction.  Blocks are ordered so
        that a field which another written field depends on is written first:
        a current range must reach the device before the current that is
        scaled by it.  Virtual fields have size 0 and are never encoded, but
        dependencies are followed through them, so a virtual scale still
        links a current to the written range it depends on.
        """
        blocks: list[tuple[int, list[int]]] = []
        block_of: dict[FieldAny, int] = {}
        ordered = sorted(((self.addr(field), field) for field in encoded), key=lambda v: v[0])
        for addr, field in ordered:
            regs = encoded[field]
            if blocks:
                start, values = blocks[-1]
                offset = addr - start
                if offset <= len(values):
                    values[offset : offset + len(regs)] = regs
                    block_of[field] = len(blocks) - 1
                    continue
            blocks.append((addr, list(regs)))
            block_of[field] = len(blocks) - 1

        encoded_fields = frozenset(encoded)
        graph: dict[int, set[int]] = {index: set() for index in range(len(blocks))}
        for field, index in block_of.items():
            for dep in self._write_predecessors(field, encoded_fields):
                source = block_of[dep]
                if source != index:
                    graph[index].add(source)

        order = _ordered(graph, lambda index: f"block@{blocks[index][0]}")
        return [(blocks[index][0], tuple(blocks[index][1])) for index in order]
