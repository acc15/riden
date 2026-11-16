"""A model's read-only register map and the helpers that plan I/O."""

from collections.abc import Callable, Iterable, Mapping
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from graphlib import CycleError, TopologicalSorter
from types import MappingProxyType

from .field import Field
from .register import Register
from .transport import Registers


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
        over the protocol limit is not checked here: minimalmodbus already
        caps a read at 125 registers and a write at 123, and reports the error
        itself.
        """
        spans = [
            (self.registers[field].addr, self.registers[field].size)
            for field in fields
            if self.registers[field].size > 0
        ]
        if not spans:
            return None
        start = min(addr for addr, _ in spans)
        end = max(addr + size for addr, size in spans)
        return start, end - start

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
