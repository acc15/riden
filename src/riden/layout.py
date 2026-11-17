"""A model's read-only register map and the helpers that plan I/O."""

from collections.abc import Callable, Iterable, Mapping
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from functools import reduce
from graphlib import CycleError, TopologicalSorter
from types import MappingProxyType
from typing import Any

from .field import Field
from .register import Register, Registers, RegRead, RegWrite


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


@dataclass(frozen=True, slots=True, eq=False)
class Layout:
    """Register map of one connected device.

    ``registers`` is the read-only map built by a model's layout factory.  A
    layout also plans transactions: dependencies are decoded before their
    dependents, a read covers one span, and writes merge into contiguous
    blocks.
    """

    registers: MappingProxyType[Field, Register]

    def dependency_order(
        self,
        fields: Iterable[Field],
        *,
        supplied: AbstractSet[Field] = frozenset(),
    ) -> list[Field]:
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
        graph: dict[Field, set[Field]] = {}
        seen: set[Field] = set()
        stack = list(fields)
        while stack:
            field = stack.pop()
            if field in seen:
                continue
            seen.add(field)

            register = self.registers.get(field)
            if register is None:
                raise ValueError(f"field {field.value} is not supported")
            deps = register.dependencies
            for dep in deps:
                if dep not in self.registers:
                    raise ValueError(
                        f"field {dep.value} is not supported (required by {field.value})"
                    )

            if field not in supplied:
                graph[field] = set(deps) - supplied
            stack.extend(dep for dep in deps if dep not in supplied)

        return _ordered(graph, lambda field: field.value)

    def register_span(self, fields: Iterable[Field]) -> tuple[int, int] | None:
        """Return the ``(start, count)`` span covering ``fields``.

        Virtual fields have size 0 and do not widen the span.  When every
        field is virtual the request needs no transaction at all, so ``None``
        is returned.  The client reads everything in one transaction.  A span
        over the protocol limit is not checked here: Modbus caps a read at
        125 registers and a write at 123, and tmodbus reports the error
        itself.
        """
        merged = reduce(
            lambda left, right: right if left is None else (min(left[0], right[0]), max(left[1], right[1])),
            ((reg.addr, reg.addr + reg.size) for field in fields if (reg := self.registers[field]).size > 0),
            None,
        )
        return None if merged is None else (merged[0], merged[1] - merged[0])

    def readers(self, fields: Iterable[Field]) -> dict[Field, RegRead]:
        """Collect the read codecs for ``fields``, validating readability.

        Every field must be readable; otherwise a ``ValueError`` listing all
        unreadable fields is raised before any I/O.  ``fields`` are assumed to
        be supported (use :meth:`dependency_order` first).
        """
        result: dict[Field, RegRead] = {}
        not_readable: list[str] = []
        for field in fields:
            register = self.registers[field]
            read = register.read
            if read is None:
                not_readable.append(field.value)
            else:
                result[field] = read
        if not_readable:
            raise ValueError(f"fields are not readable: {', '.join(not_readable)}")
        return result

    def decode(
        self,
        readers: Mapping[Field, RegRead],
        regs: Registers,
        start: int,
    ) -> dict[str, Any]:
        """Decode already fetched registers into field values.

        ``readers`` must be collected from fields already in dependency order;
        its keys define both the field set and that order.
        """
        values: dict[str, Any] = {}
        for field, read in readers.items():
            register = self.registers[field]
            if register.size == 0:
                raw: Registers = ()
            else:
                offset = register.addr - start
                raw = regs[offset : offset + register.size]
            values[field.value] = read(raw, register.make_deps(values))
        return values

    def writers(self, fields: Iterable[Field]) -> dict[Field, RegWrite]:
        """Collect the write codecs for ``fields``, validating support/writability.

        Unsupported fields raise ``ValueError`` first, then non-writable ones,
        matching the original behaviour.  ``fields`` are validated against the
        layout's register map.
        """
        result: dict[Field, RegWrite] = {}
        unsupported: list[str] = []
        not_writable: list[str] = []
        for field in fields:
            register = self.registers.get(field)
            if register is None:
                unsupported.append(field.value)
            elif register.write is None:
                not_writable.append(field.value)
            else:
                result[field] = register.write
        if unsupported:
            raise ValueError(f"fields are not supported: {', '.join(unsupported)}")
        if not_writable:
            raise ValueError(f"fields are not writable: {', '.join(not_writable)}")
        return result
    
    def encode(
        self,
        writers: Mapping[Field, RegWrite],
        updates: Mapping[Field, Any],
        dependencies: Mapping[str, Any],
    ) -> dict[Field, Registers]:
        """Encode supplied fields into register blocks.

        Per-field codec validation and size/range checks happen here, before
        anything is written.  Virtual fields are skipped.
        """
        values = {**dependencies, **updates}
        encoded: dict[Field, Registers] = {}
        for field, value in updates.items():
            register = self.registers[field]
            try:
                regs = writers[field](value, register.make_deps(values))
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

    def write_blocks(
        self,
        encoded: Mapping[Field, Registers],
    ) -> list[tuple[int, Registers]]:
        """Merge encoded fields into contiguous write transactions.

        Registers that touch share one transaction.  Blocks are ordered so
        that a field which another written field depends on is written first:
        a current range must reach the device before the current that is
        scaled by it.  Virtual fields have size 0 and are never encoded.
        """
        blocks: list[tuple[int, list[int]]] = []
        block_of: dict[Field, int] = {}
        for field in sorted(encoded, key=lambda f: self.registers[f].addr):
            regs = encoded[field]
            if blocks:
                start, values = blocks[-1]
                offset = self.registers[field].addr - start
                if offset <= len(values):
                    values[offset:offset + len(regs)] = regs
                    block_of[field] = len(blocks) - 1
                    continue
            blocks.append((self.registers[field].addr, list(regs)))
            block_of[field] = len(blocks) - 1

        graph: dict[int, set[int]] = {index: set() for index in range(len(blocks))}
        for field, index in block_of.items():
            for dep in self.registers[field].dependencies:
                source = block_of.get(dep)
                if source is not None and source != index:
                    graph[index].add(source)

        order = _ordered(graph, lambda index: f"block@{blocks[index][0]}")
        return [(blocks[index][0], tuple(blocks[index][1])) for index in order]
