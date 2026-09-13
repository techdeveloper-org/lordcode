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

The second half of this module is the execution side: ExecutorPort, the
in-process reference implementation, the token-budget cap, and run_dag's
failure containment. Three constraints shape it, all of them measured rather
than assumed:

    Spawn pickles everything. get_context("spawn") is the only start method
    available on Windows (agent_runtime.py:175), so a NodeSpec names its
    executor by a registry key instead of holding a function, and carries
    assembled context as TEXT. A KnowledgeGraph handle in a spec would either
    refuse to pickle or ship a second copy of the graph into every child.

    No concurrency is claimed. agent_runtime's dispatcher is one thread
    calling call_role synchronously (agent_runtime.py:129-160), so nodes are
    serviced one at a time no matter how wide a level is. The DAG buys
    independent failure domains, per-node retry and a fresh budget per node --
    not speed.

    The budget cap is frequently 1, and its honest floor is 0. At this repo's
    ~6000 TPM with MAX_CODER_TOKENS = 8000, one code-generation call does not
    fit inside a minute at any context size, so concurrency_cap clamps to 1
    and reports the floor rather than rounding it away silently.
"""

from __future__ import annotations

import pickle
from collections.abc import Callable, Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Generic, Protocol, TypeVar

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


class FailureClass(str, Enum):
    """Whether a failed node is worth trying again.

    The same split M4's tool runtime and M0.2's 429 path already use: a
    timeout or a rate limit will plausibly succeed on a second attempt, a
    validation error or an unparseable document will not.
    """

    TRANSIENT = "transient"
    PERMANENT = "permanent"


class Outcome(str, Enum):
    """What became of one node in a run."""

    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class NodeFailure(Exception):
    """A node executor's failure, carrying whether a retry is worth it.

    Any other exception is treated as PERMANENT. That is deliberate: an
    unexpected exception has, by definition, not been reasoned about, and
    retrying an unknown fault is how a bounded loop becomes an unbounded one.
    """

    def __init__(self, message: str, *, failure_class: FailureClass = FailureClass.PERMANENT):
        super().__init__(message)
        self.failure_class = failure_class


@dataclass(frozen=True)
class NodeSpec:
    """One schedulable unit of work, carrying only picklable state.

    `node_type` names a module-level executor in this module's registry rather
    than holding a function object, and `context` is assembled TEXT. Both
    exist because multiprocessing on Windows only offers the spawn start
    method (agent_runtime.py:175), so every field here is pickled per node and
    the child re-imports the package -- a KnowledgeGraph handle in `state`
    would either fail to pickle or silently ship a second copy of the graph
    into every child.
    """

    label: str
    node_type: str
    state: Mapping[str, Any] = field(default_factory=dict)
    context: str = ""
    calls: int = 1
    ctx_tokens: int = 0
    max_completion_tokens: int = 0


@dataclass(frozen=True)
class NodeResult:
    """One node's outcome, including the attempts it took."""

    label: str
    outcome: Outcome
    value: Any = None
    error: str = ""
    failure_class: FailureClass | None = None
    attempts: int = 0
    skipped_because: str = ""


NodeExecutor = Callable[[NodeSpec], Any]

_NODE_EXECUTORS: dict[str, NodeExecutor] = {}


def register_node_type(node_type: str, executor: NodeExecutor) -> None:
    """Bind a node type to a module-level executor function.

    Raises:
        ValueError: if the type is already bound to a different function, or
            the function is a lambda or a closure. Both would pickle badly or
            not at all, and the failure would surface inside a spawned child
            rather than here.
    """
    existing = _NODE_EXECUTORS.get(node_type)
    if existing is not None and existing is not executor:
        raise ValueError(f"node type {node_type!r} is already registered to {existing!r}")
    if getattr(executor, "__name__", "<lambda>") == "<lambda>":
        raise ValueError(f"node type {node_type!r} needs a module-level function, not a lambda")
    module = getattr(executor, "__module__", "")
    qualname = getattr(executor, "__qualname__", "")
    if not module or "<locals>" in qualname:
        raise ValueError(
            f"node type {node_type!r} needs a module-level function; {qualname!r} is nested"
        )
    _NODE_EXECUTORS[node_type] = executor


def node_type(name: str) -> Callable[[NodeExecutor], NodeExecutor]:
    """Decorator form of register_node_type."""

    def bind(executor: NodeExecutor) -> NodeExecutor:
        register_node_type(name, executor)
        return executor

    return bind


def resolve_node_executor(name: str) -> NodeExecutor:
    """The executor bound to a node type.

    Raises:
        KeyError: naming the registered types, since a typo here fails inside
            a child process where the traceback is far less useful.
    """
    try:
        return _NODE_EXECUTORS[name]
    except KeyError:
        known = ", ".join(sorted(_NODE_EXECUTORS)) or "none registered"
        raise KeyError(f"unknown node type {name!r}; registered: {known}") from None


def registered_node_types() -> tuple[str, ...]:
    """Every bound node type, sorted."""
    return tuple(sorted(_NODE_EXECUTORS))


def clear_node_types() -> None:
    """Drop every binding. For tests that register throwaway types."""
    _NODE_EXECUTORS.clear()


def unpicklable_fields(spec: NodeSpec) -> tuple[str, ...]:
    """Which of a spec's fields cannot survive a spawn.

    Called by the reference executor and worth calling from any adapter: the
    cost of checking is one pickle round-trip per node, and the cost of not
    checking is a spawn failure whose traceback names the pickler rather than
    the field that caused it.
    """
    offenders: list[str] = []
    for name in ("state", "context", "calls", "ctx_tokens", "max_completion_tokens"):
        try:
            pickle.dumps(getattr(spec, name))
        except Exception:
            offenders.append(name)
    return tuple(offenders)


class ExecutorPort(Protocol):
    """How a level of independent nodes gets run.

    Mirrors AgentCoordinator.run_agents_parallel's real shape --
    `list[AgentSpec] -> dict[label, result]` -- so the vishwakarma adapter is
    a thin wrapper rather than a translation layer. kgf ships only the
    in-process reference implementation below; the process-spawning one stays
    on the vishwakarma side, which is what keeps ADR-2's one-way rule true.

    MUST NOT raise because one node failed. A single failure has to come back
    as that node's value so the scheduler can classify it, retry it, and skip
    only its dependents -- an exception escaping run_level loses the results
    of every sibling that succeeded in the same level.
    """

    def run_level(self, specs: Sequence[NodeSpec]) -> dict[str, Any]:
        """Run every spec and return label -> result or captured exception."""
        ...


class InProcessExecutor:
    """Reference ExecutorPort: runs each node here, in order, no processes.

    Deliberately sequential. agent_runtime's dispatcher is a single thread
    calling call_role synchronously (agent_runtime.py:129-160), so even the
    real process-spawning executor services concurrent nodes one at a time --
    a reference implementation that looked concurrent would misrepresent the
    system it stands in for.
    """

    def __init__(self, on_event: Callable[[dict[str, Any]], None] | None = None):
        self._on_event = on_event

    def run_level(self, specs: Sequence[NodeSpec]) -> dict[str, Any]:
        """Run every spec, capturing each failure as that node's value."""
        results: dict[str, Any] = {}
        for spec in specs:
            offenders = unpicklable_fields(spec)
            if offenders:
                results[spec.label] = NodeFailure(
                    f"node {spec.label} has unpicklable {', '.join(offenders)}; "
                    "spawn pickles every field, so this would fail inside the child"
                )
                continue
            try:
                results[spec.label] = resolve_node_executor(spec.node_type)(spec)
            except Exception as failure:
                results[spec.label] = failure
            if self._on_event is not None:
                self._on_event({"type": "node_finished", "label": spec.label})
        return results


def concurrency_cap(
    tpm_budget: int,
    ctx_tokens: int,
    max_completion_tokens: int,
    *,
    on_warning: Callable[[str], None] | None = None,
) -> int:
    """How many nodes of this shape a token budget admits per minute.

    floor(tpm_budget / (ctx_tokens + max_completion_tokens)), clamped to at
    least 1. The clamp is not cosmetic: on this repo's real numbers the floor
    is 0 for the generate node, because MAX_CODER_TOKENS = 8000 alone exceeds
    the whole ~6000 TPM ceiling, so one code-generation call cannot fit inside
    a single minute at any context size. A cap of 0 is not a scheduling
    decision -- it means that node is paced across minutes regardless -- so
    the floor is reported through on_warning rather than silently rounded up.
    """
    total = ctx_tokens + max_completion_tokens
    if total <= 0:
        return 1
    floor = tpm_budget // total
    if floor == 0 and on_warning is not None:
        on_warning(
            f"one call of {total} tokens exceeds the {tpm_budget} TPM budget; "
            f"this node is paced at about {total / max(tpm_budget, 1):.1f} minutes per call"
        )
    return max(1, floor)


def level_cap(
    specs: Sequence[NodeSpec],
    tpm_budget: int,
    *,
    on_warning: Callable[[str], None] | None = None,
) -> int:
    """The concurrency cap for a whole level, using its most expensive node.

    A node making k calls counts k times, so a level's admissible width is
    governed by its total call cost and not by its node count.
    """
    if not specs:
        return 1
    widest = max(specs, key=lambda spec: spec.ctx_tokens + spec.max_completion_tokens)
    per_node = concurrency_cap(
        tpm_budget, widest.ctx_tokens, widest.max_completion_tokens, on_warning=on_warning
    )
    calls = sum(max(spec.calls, 1) for spec in specs)
    return max(1, min(per_node, calls))


@dataclass
class RunReport:
    """The outcome of one DAG run, and the ledger a rerun resumes from."""

    results: dict[str, NodeResult] = field(default_factory=dict)
    levels: list[list[str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def of(self, outcome: Outcome) -> tuple[str, ...]:
        """Labels with one outcome, in the order they were recorded."""
        return tuple(label for label, result in self.results.items() if result.outcome is outcome)

    @property
    def completed(self) -> tuple[str, ...]:
        """Nodes that produced a value, whose outputs a rerun can reuse."""
        return self.of(Outcome.COMPLETED)

    @property
    def failed(self) -> tuple[str, ...]:
        """Nodes that failed after their retries were exhausted."""
        return self.of(Outcome.FAILED)

    @property
    def skipped(self) -> tuple[str, ...]:
        """Nodes never attempted because something they depend on failed."""
        return self.of(Outcome.SKIPPED)

    @property
    def ok(self) -> bool:
        """True when nothing failed and nothing was skipped."""
        return not (self.failed or self.skipped)

    def values(self) -> dict[str, Any]:
        """Completed nodes' values, keyed by label."""
        return {
            label: result.value
            for label, result in self.results.items()
            if result.outcome is Outcome.COMPLETED
        }


def _classify(value: Any) -> FailureClass | None:
    """The failure class of a run_level value, or None if it succeeded."""
    if isinstance(value, NodeFailure):
        return value.failure_class
    if isinstance(value, BaseException):
        return FailureClass.PERMANENT
    return None


def run_dag(
    specs: Sequence[NodeSpec],
    edges: Edges,
    executor: ExecutorPort,
    *,
    cycle_policy: CyclePolicy = CyclePolicy.FATAL,
    transient_retries: int = 1,
    tpm_budget: int = 0,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> RunReport:
    """Run every spec in dependency order, containing failures to dependents.

    Failure containment, stated as behaviour rather than aspiration: a node
    that fails after its retries are exhausted causes every transitive
    dependent to be SKIPPED, while completed nodes keep their values in the
    report. Nothing is rolled back -- rollback scope is nothing, deliberately,
    because a node that wrote files cannot be un-run and pretending otherwise
    would be worse than saying so. A rerun therefore resumes from the report's
    completed set instead of repeating it.

    A TRANSIENT failure is retried on its own, up to transient_retries times,
    rather than by re-running its whole level: the siblings already succeeded
    and re-running them would spend budget to recompute known values.
    """
    by_label = {spec.label: spec for spec in specs}
    if len(by_label) != len(specs):
        raise ValueError("every NodeSpec needs a unique label")

    report = RunReport()

    def note(warning: str) -> None:
        report.warnings.append(warning)
        if on_event is not None:
            on_event({"type": "budget_warning", "detail": warning})

    ordered = levels(list(by_label), edges, cycle_policy=cycle_policy)
    report.levels = [list(level) for level in ordered]

    blocked: dict[str, str] = {}
    for level in ordered:
        runnable: list[NodeSpec] = []
        for label in level:
            culprit = next(
                (dep for dep in edges.get(label, ()) if dep in blocked or dep in report.failed),
                None,
            )
            if culprit is not None:
                blocked[label] = culprit
                report.results[label] = NodeResult(
                    label=label,
                    outcome=Outcome.SKIPPED,
                    skipped_because=culprit,
                )
                continue
            runnable.append(by_label[label])

        if not runnable:
            continue

        if tpm_budget:
            cap = level_cap(runnable, tpm_budget, on_warning=note)
            if on_event is not None:
                on_event({"type": "level_cap", "cap": cap, "nodes": len(runnable)})

        outcomes = executor.run_level(runnable)
        pending: list[NodeSpec] = []
        for spec in runnable:
            value = outcomes.get(spec.label, KeyError(f"executor returned no result for {spec.label}"))
            failure = _classify(value)
            if failure is None:
                report.results[spec.label] = NodeResult(
                    label=spec.label, outcome=Outcome.COMPLETED, value=value, attempts=1
                )
            elif failure is FailureClass.TRANSIENT and transient_retries > 0:
                pending.append(spec)
            else:
                report.results[spec.label] = NodeResult(
                    label=spec.label,
                    outcome=Outcome.FAILED,
                    error=str(value),
                    failure_class=failure,
                    attempts=1,
                )

        attempt = 1
        while pending and attempt <= transient_retries:
            attempt += 1
            retrying, pending = pending, []
            for spec in retrying:
                if on_event is not None:
                    on_event({"type": "node_retry", "label": spec.label, "attempt": attempt})
                value = executor.run_level([spec]).get(spec.label)
                failure = _classify(value)
                if failure is None:
                    report.results[spec.label] = NodeResult(
                        label=spec.label, outcome=Outcome.COMPLETED, value=value, attempts=attempt
                    )
                elif failure is FailureClass.TRANSIENT and attempt < transient_retries + 1:
                    pending.append(spec)
                else:
                    report.results[spec.label] = NodeResult(
                        label=spec.label,
                        outcome=Outcome.FAILED,
                        error=str(value),
                        failure_class=failure,
                        attempts=attempt,
                    )

        for spec in pending:
            report.results[spec.label] = NodeResult(
                label=spec.label,
                outcome=Outcome.FAILED,
                error="transient failure persisted past every retry",
                failure_class=FailureClass.TRANSIENT,
                attempts=transient_retries + 1,
            )

    return report
