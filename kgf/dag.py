"""Dependency-graph machinery: union-find, SCCs, depth tiers, levels.

Extracted from vishwakarma's engine/parallel_generate.py rather than written
again. That module had already grown a union-find, an iterative Tarjan, a
depth-tier splitter and a wave scheduler for file manifests; kgf needs the
same four things for an authored phase topology, and two schedulers in one
repo is not acceptable. The algorithms here are that code, generalised from
`str` file paths to any hashable label; parallel_generate.py now calls in.

The one behavioural difference is deliberate and is why this module takes a
policy argument. `_compute_group_waves` responded to a cycle by putting every
group in wave 0, which is sound there -- its clustering invariant means an
edge-connected pair is always merged into one cluster, so a cross-group cycle
is unreachable and the fallback exists only to avoid recursing forever. For
an authored topology a cycle is an authoring mistake and collapsing it would
hide exactly the error the topology test exists to find. So:

    CyclePolicy.COLLAPSE  every node to level 0, report via on_cycle
    CyclePolicy.FATAL     raise DependencyCycleError naming the members

Cycle detection is by SCC rather than by the recursion-marker trick the
original used, because a policy that reports a cycle has to be able to say
which nodes are in it, and a back-edge marker cannot.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable, Mapping, Sequence
from enum import Enum
from typing import Generic, TypeVar

T = TypeVar("T", bound=Hashable)

Edges = Mapping[T, Iterable[T]]
"""node -> the nodes it depends on. A node with no entry depends on nothing."""


class CyclePolicy(str, Enum):
    """What a scheduler does when the dependency graph is not acyclic."""

    COLLAPSE = "collapse"
    FATAL = "fatal"


class DependencyCycleError(Exception):
    """Raised under CyclePolicy.FATAL when the graph contains a cycle.

    Carries every cycle found, not the first, because an author fixing a
    topology wants the whole list in one pass -- the same reasoning as
    GraphBuildError in kgf.errors.
    """

    def __init__(self, cycles: list[list[T]]):
        self.cycles = cycles
        listed = "; ".join(" -> ".join(str(node) for node in cycle) for cycle in cycles[:5])
        more = f" (and {len(cycles) - 5} more)" if len(cycles) > 5 else ""
        super().__init__(f"{len(cycles)} dependency cycle(s): {listed}{more}")


class DisjointSet(Generic[T]):
    """Minimal union-find over a fixed set of items."""

    def __init__(self, items: Iterable[T]):
        self._parent: dict[T, T] = {item: item for item in items}

    def find(self, x: T) -> T:
        """The representative of x's set, path-halving as it walks."""
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def union(self, a: T, b: T) -> None:
        """Merge the sets containing a and b."""
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[ra] = rb

    def groups(self) -> list[list[T]]:
        """Every set, each in insertion order, ordered by first appearance."""
        found: dict[T, list[T]] = {}
        order: list[T] = []
        for item in self._parent:
            root = self.find(item)
            if root not in found:
                found[root] = []
                order.append(root)
            found[root].append(item)
        return [found[root] for root in order]


def strongly_connected_components(nodes: Sequence[T], edges: Edges) -> list[list[T]]:
    """Iterative Tarjan's SCC, restricted to `nodes`.

    Only edges between two members of `nodes` are followed; an edge leaving
    the set is ignored, since callers pass one subgraph at a time. Iterative
    rather than recursive so a long dependency chain cannot exhaust the
    interpreter stack.
    """
    node_set = set(nodes)
    index_counter = [0]
    stack: list[T] = []
    on_stack: set[T] = set()
    indices: dict[T, int] = {}
    lowlink: dict[T, int] = {}
    result: list[list[T]] = []

    def neighbors(n: T) -> list[T]:
        return [d for d in edges.get(n, ()) if d in node_set]

    for start in nodes:
        if start in indices:
            continue
        work: list[tuple[T, int]] = [(start, 0)]
        indices[start] = lowlink[start] = index_counter[0]
        index_counter[0] += 1
        stack.append(start)
        on_stack.add(start)

        while work:
            node, i = work[-1]
            succ = neighbors(node)
            if i < len(succ):
                work[-1] = (node, i + 1)
                nxt = succ[i]
                if nxt not in indices:
                    indices[nxt] = lowlink[nxt] = index_counter[0]
                    index_counter[0] += 1
                    stack.append(nxt)
                    on_stack.add(nxt)
                    work.append((nxt, 0))
                elif nxt in on_stack:
                    lowlink[node] = min(lowlink[node], indices[nxt])
            else:
                work.pop()
                if work:
                    parent = work[-1][0]
                    lowlink[parent] = min(lowlink[parent], lowlink[node])
                if lowlink[node] == indices[node]:
                    component: list[T] = []
                    while True:
                        w = stack.pop()
                        on_stack.discard(w)
                        component.append(w)
                        if w == node:
                            break
                    result.append(component)
    return result


def find_cycles(nodes: Sequence[T], edges: Edges) -> list[list[T]]:
    """Every cycle in the subgraph induced by `nodes`, as SCC membership.

    A multi-member SCC is a cycle. A single-member SCC is one only if the
    node depends on itself -- which a hand-authored topology can express and
    a file manifest cannot, so it is checked rather than assumed away.
    """
    cycles: list[list[T]] = []
    node_set = set(nodes)
    for component in strongly_connected_components(nodes, edges):
        if len(component) > 1:
            cycles.append(component)
        else:
            only = component[0]
            if only in set(edges.get(only, ())) & node_set:
                cycles.append(component)
    return cycles


def _condensation_depths(nodes: Sequence[T], edges: Edges) -> tuple[dict[T, int], list[list[T]]]:
    """Depth of each node's SCC over the condensation graph.

    The condensation of any digraph is acyclic, so depth always terminates no
    matter how many cycles the input had. Computed over a Kahn ordering
    rather than by recursion, so depth is bounded by memory and not by the
    interpreter's stack limit.
    """
    components = strongly_connected_components(nodes, edges)
    component_of: dict[T, int] = {node: i for i, comp in enumerate(components) for node in comp}

    node_set = set(nodes)
    dependencies: list[set[int]] = [set() for _ in components]
    dependents: list[set[int]] = [set() for _ in components]
    for node in nodes:
        for dep in edges.get(node, ()):
            if dep not in node_set:
                continue
            source, target = component_of[node], component_of[dep]
            if source != target:
                dependencies[source].add(target)
                dependents[target].add(source)

    remaining = [len(deps) for deps in dependencies]
    depth = [0] * len(components)
    ready = [i for i in range(len(components)) if remaining[i] == 0]
    processed = 0
    while ready:
        index = ready.pop()
        processed += 1
        for dependent in dependents[index]:
            depth[dependent] = max(depth[dependent], depth[index] + 1)
            remaining[dependent] -= 1
            if remaining[dependent] == 0:
                ready.append(dependent)

    if processed != len(components):
        raise AssertionError("condensation graph is cyclic, which is impossible by construction")

    return {node: depth[component_of[node]] for node in nodes}, components


def depth_tiers(nodes: Sequence[T], edges: Edges) -> list[list[T]]:
    """Split `nodes` into ordered dependency-depth tiers, cycles condensed.

    Nodes inside a cycle land in the same tier, which generalises the mutual-
    dependency tie rule the original code needed for free-text-derived edges
    that are not provably acyclic. Tiers come back in ascending depth order
    and nodes keep their input order within a tier, so the result is stable.
    """
    if not nodes:
        return []
    depth_of, _components = _condensation_depths(nodes, edges)
    tiers: list[list[T]] = [[] for _ in range(max(depth_of.values()) + 1)]
    for node in nodes:
        tiers[depth_of[node]].append(node)
    return [tier for tier in tiers if tier]


def levels(
    nodes: Sequence[T],
    edges: Edges,
    *,
    cycle_policy: CyclePolicy = CyclePolicy.FATAL,
    on_cycle: Callable[[list[list[T]]], None] | None = None,
) -> list[list[T]]:
    """Group `nodes` into execution levels: level N depends only on < N.

    A node's level is 1 + the maximum level of the nodes it depends on, or 0
    if it depends on none, so every node in a level is independent of every
    other and the level can be run as a unit.

    Under CyclePolicy.FATAL a cycle raises DependencyCycleError. Under
    COLLAPSE every node goes into level 0 and on_cycle is called with the
    cycles -- preserving parallel_generate's existing fallback, which is
    sound there and wrong for an authored graph.
    """
    if not nodes:
        return []

    cycles = find_cycles(nodes, edges)
    if cycles:
        if cycle_policy is CyclePolicy.FATAL:
            raise DependencyCycleError(cycles)
        if on_cycle is not None:
            on_cycle(cycles)
        return [list(nodes)]

    depth_of, _components = _condensation_depths(nodes, edges)
    ordered: list[list[T]] = [[] for _ in range(max(depth_of.values()) + 1)]
    for node in nodes:
        ordered[depth_of[node]].append(node)
    return [level for level in ordered if level]
