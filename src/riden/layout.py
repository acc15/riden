"""A model's read-only register map and the helpers that plan I/O."""

from collections.abc import Callable, Iterable, Iterator, Mapping
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from graphlib import CycleError, TopologicalSorter
from types import MappingProxyType
from typing import Any

from .field import Field, FieldRef
from .preset import PresetField, PresetParam
from .register import LocatedRegister, Register, Registers, RegRead, RegWrite


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

    def resolve(self, field: PresetField) -> LocatedRegister | None:
        if not 0 <= field.num < self.count:
            return None
        register = self.template.get(field.param)
        if register is None:
            return None
        addr = self.base + field.num * self.stride + register.addr
        return LocatedRegister(addr, register)


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

    def resolve(self, field: FieldRef) -> LocatedRegister | None:
        target = field.target
        if isinstance(target, PresetField):
            return self.presets.resolve(target)
        register = self.registers.get(target)
        return None if register is None else LocatedRegister(register.addr, register)

    def addr(self, field: FieldRef) -> int:
        located = self.resolve(field)
        if located is None:
            raise KeyError(field.value)
        return located.addr

    def fields(self) -> Iterator[FieldRef]:
        """Iterate over every field in the layout, including all presets."""
        for field in self.registers:
            yield FieldRef(field)
        for num in range(self.presets.count):
            for param in self.presets.template:
                yield FieldRef(PresetField(num, param))

    def _target(self, ref: FieldRef, target: Field | PresetField | PresetParam) -> FieldRef:
        if isinstance(target, PresetParam):
            field = ref.target
            if not isinstance(field, PresetField):
                raise TypeError("relative preset dependency outside a preset")
            return FieldRef(PresetField(field.num, target))
        return FieldRef(target)

    def deps(self, field: FieldRef) -> Mapping[Field, FieldRef]:
        """Return a field's dependencies with preset-relative targets resolved."""
        located = self.resolve(field)
        if located is None:
            raise KeyError(field.value)
        return {
            alias: self._target(field, target)
            for alias, target in located.reg.deps.items()
        }

    def dependencies(self, field: FieldRef) -> frozenset[FieldRef]:
        return frozenset(self.deps(field).values())

    def make_deps(
        self,
        field: FieldRef,
        values: Mapping[FieldRef, Any],
    ) -> dict[Field, Any]:
        """Return the dependency mapping a codec is allowed to see."""
        return {alias: values[target] for alias, target in self.deps(field).items()}

    def dependency_order(
        self,
        fields: Iterable[FieldRef],
        supplied: AbstractSet[FieldRef] = frozenset(),
    ) -> list[FieldRef]:
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
        graph: dict[FieldRef, set[FieldRef]] = {}
        seen: set[FieldRef] = set()
        supplied_refs = set(supplied)
        stack = list(fields)
        while stack:
            field = stack.pop()
            if field in seen:
                continue
            seen.add(field)

            located = self.resolve(field)
            if located is None:
                raise ValueError(f"field {field.value} is not supported")
            deps = self.dependencies(field)
            for dep in deps:
                if self.resolve(dep) is None:
                    raise ValueError(
                        f"field {dep.value} is not supported (required by {field.value})"
                    )

            if field not in supplied_refs:
                graph[field] = set(deps) - supplied_refs
            stack.extend(dep for dep in deps if dep not in supplied_refs)

        return _ordered(graph, lambda field: field.value)

    def register_span(self, fields: Iterable[FieldRef]) -> tuple[int, int] | None:
        """Return the ``(start, count)`` span covering ``fields``.

        Virtual fields have size 0 and do not widen the span.  When every
        field is virtual the request needs no transaction at all, so ``None``
        is returned.  The client reads everything in one transaction.  A span
        over the protocol limit is not checked here: Modbus caps a read at
        125 registers and a write at 123, and tmodbus reports the error
        itself.
        """
        merged: tuple[int, int] | None = None
        for field in fields:
            located = self.resolve(field)
            if located is None:
                raise KeyError(field.value)
            if located.reg.size == 0:
                continue
            start = located.addr
            end = start + located.reg.size
            merged = (
                (start, end)
                if merged is None
                else (min(merged[0], start), max(merged[1], end))
            )
        return None if merged is None else (merged[0], merged[1] - merged[0])

    def readers(self, fields: Iterable[FieldRef]) -> dict[FieldRef, RegRead]:
        """Collect the read codecs for ``fields``, validating readability.

        Every field must be readable; otherwise a ``ValueError`` listing all
        unreadable fields is raised before any I/O.  ``fields`` are assumed to
        be supported (use :meth:`dependency_order` first).
        """
        result: dict[FieldRef, RegRead] = {}
        not_readable: list[str] = []
        for ref in fields:
            located = self.resolve(ref)
            if located is None:
                raise KeyError(ref.value)
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
        readers: Mapping[FieldRef, RegRead],
        regs: Registers,
        start: int,
        initial: Mapping[FieldRef, Any] = MappingProxyType({}),
    ) -> dict[FieldRef, Any]:
        """Decode already fetched registers into field values.

        ``readers`` must be collected from fields already in dependency order;
        its keys define both the field set and that order.  ``initial`` seeds
        the decoded values, so a dependency the caller already knows need not
        be fetched.  A field present in both is decoded normally and replaces
        the seeded value.  Both the input and the result are keyed by
        :class:`FieldRef`; the public ``str`` names are applied by the client.
        """
        values: dict[FieldRef, Any] = {FieldRef(key): value for key, value in initial.items()}
        for field, read in readers.items():
            ref = FieldRef(field)
            located = self.resolve(ref)
            if located is None:
                raise KeyError(ref.value)
            if located.reg.size == 0:
                raw: Registers = ()
            else:
                offset = located.addr - start
                raw = regs[offset : offset + located.reg.size]
            values[ref] = read(raw, self.make_deps(ref, values))
        return values

    def writers(self, fields: Iterable[FieldRef]) -> dict[FieldRef, RegWrite]:
        """Collect the write codecs for ``fields``, validating support/writability.

        Unsupported fields raise ``ValueError`` first, then non-writable ones,
        matching the original behaviour.  ``fields`` are validated against the
        layout's register map.
        """
        result: dict[FieldRef, RegWrite] = {}
        unsupported: list[str] = []
        not_writable: list[str] = []
        for ref in fields:
            located = self.resolve(ref)
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
        writers: Mapping[FieldRef, RegWrite],
        updates: Mapping[FieldRef, Any],
        dependencies: Mapping[FieldRef, Any],
    ) -> dict[FieldRef, Registers]:
        """Encode supplied fields into register blocks.

        ``dependencies`` are decoded values keyed by :class:`FieldRef`; they
        and ``updates`` are merged before the codecs see them, so a
        caller-supplied value overrides a read one.  Per-field codec validation
        and size/range checks happen here, before anything is written.  Virtual
        fields are skipped.
        """
        values: dict[FieldRef, Any] = {
            FieldRef(key): value for key, value in {**dependencies, **updates}.items()
        }
        encoded: dict[FieldRef, Registers] = {}
        for field, value in updates.items():
            ref = FieldRef(field)
            located = self.resolve(ref)
            if located is None:
                raise KeyError(ref.value)
            register = located.reg
            try:
                regs = writers[ref](value, self.make_deps(ref, values))
            except ValueError as exc:
                raise ValueError(f"field {ref.value}: {exc}") from exc
            if len(regs) != register.size:
                raise ValueError(
                    f"field {ref.value} produced {len(regs)} registers, "
                    f"expected {register.size}"
                )
            if any(reg < 0 or reg > 0xFFFF for reg in regs):
                raise ValueError(
                    f"field {ref.value} produced out-of-range registers: {regs}"
                )
            if register.size == 0:
                continue
            encoded[ref] = regs
        return encoded

    def _write_predecessors(
        self,
        field: FieldRef,
        encoded: AbstractSet[FieldRef],
    ) -> set[FieldRef]:
        """Return the written fields that ``field`` transitively depends on.

        Virtual fields are never encoded, but they can have real dependencies:
        a current's scale depends on its range.  The walk passes through
        unencoded fields instead of stopping at them, so the range is still
        ordered before the current it scales.
        """
        result: set[FieldRef] = set()
        seen: set[FieldRef] = set()
        stack = list(self.dependencies(field))
        while stack:
            dep = stack.pop()
            if dep in seen:
                continue
            seen.add(dep)
            if dep in encoded:
                result.add(dep)
            else:
                located = self.resolve(dep)
                if located is not None:
                    stack.extend(self.dependencies(dep))
        return result

    def write_blocks(
        self,
        encoded: Mapping[FieldRef, Registers],
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
        block_of: dict[FieldRef, int] = {}
        for field in sorted(encoded, key=self.addr):
            located = self.resolve(field)
            if located is None:
                raise KeyError(field.value)
            regs = encoded[field]
            if blocks:
                start, values = blocks[-1]
                offset = located.addr - start
                if offset <= len(values):
                    values[offset : offset + len(regs)] = regs
                    block_of[field] = len(blocks) - 1
                    continue
            blocks.append((located.addr, list(regs)))
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
