"""kgf's ExecutorPort, implemented over this engine's AgentCoordinator.

kgf ships only an in-process reference executor, deliberately: the
process-spawning one belongs on this side of the boundary, which is what keeps
ADR-2's one-way rule true. This module is that implementation, plus the
re-exports run_task needs so the orchestrator never writes `import kgf`
itself.

Two things it has to get right, both of them lessons this repo already paid
for:

    Drain before joining. AgentCoordinator documents the deadlock at length
    (agent_runtime.py:250-262): a child blocks in its Queue feeder thread once
    the OS pipe buffer fills, while a parent sitting in process.join() waits
    for a child that cannot exit until somebody drains the queue. Issue #2
    found 20 call sites in this state. run_level drains every node's result
    first and only then joins.

    Never let one node's failure escape. The port's MUST NOT exists because an
    exception leaving run_level discards the results of every sibling that
    succeeded in the same level -- and this executor's siblings are OS
    processes whose work is already paid for. Each failure comes back as that
    node's value, which is what lets the scheduler classify it, retry it, and
    skip only its dependents.

Not every node can be a child process. A node that itself spawns agents --
implementation, which goes through parallel_generate -- would be nesting spawn
inside spawn, forking the coordinator and its dispatcher thread along with it.
Such nodes declare `state["spawn"] = False` and run in the parent, in the same
level, with their failures captured identically.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from kgf.dag import (
    CyclePolicy,
    FailureClass,
    NodeFailure,
    NodeResult,
    NodeSpec,
    Outcome,
    RunReport,
    UPSTREAM_KEY,
    concurrency_cap,
    level_cap,
    run_dag,
)
from kgf.topology import Phase, Topology
from vishwakarma.engine.agent_runtime import AgentCoordinator
from vishwakarma.engine.calling import OnEvent, noop_event

__all__ = [
    "CoordinatorExecutor",
    "CyclePolicy",
    "FailureClass",
    "NodeFailure",
    "NodeResult",
    "NodeSpec",
    "Outcome",
    "Phase",
    "RunReport",
    "SPAWN_KEY",
    "Topology",
    "UPSTREAM_KEY",
    "concurrency_cap",
    "level_cap",
    "run_dag",
]

SPAWN_KEY = "spawn"
"""State key: False runs the node in the parent instead of a child process."""

NodeFunction = Callable[..., Any]
"""A node's work: (remote_llm, spec) in a child, (runtime, spec) in the parent.

The first parameter is always the handle through which the node reaches the
outside world, and which one it gets is decided by where it runs. A spawned
node receives a RemoteLLM because that is the coordinator's own convention --
spawn_agent passes one to every persona function it starts
(agent_runtime.py:103-107). An in-parent node receives the caller's runtime
object instead, which is how it reaches a Router, an LLMClient or a workdir
without any of those ever entering `spec.state` and therefore never being
handed to the pickler.
"""


class CoordinatorExecutor:
    """Runs a level's nodes as real OS processes through one AgentCoordinator.

    Construct per run, alongside the coordinator it wraps. The coordinator
    owns the shared request queue, dispatcher thread and RateLimiter, so every
    node's model call is admitted through the same budget no matter which
    process makes it.
    """

    def __init__(
        self,
        coordinator: AgentCoordinator,
        node_functions: Mapping[str, NodeFunction],
        runtime: Any = None,
        on_event: OnEvent = noop_event,
    ):
        for node_type, function in node_functions.items():
            qualname = getattr(function, "__qualname__", "")
            if getattr(function, "__name__", "<lambda>") == "<lambda>" or "<locals>" in qualname:
                raise ValueError(
                    f"node type {node_type!r} needs a module-level function; spawn pickles "
                    f"it by reference and {qualname or 'a lambda'} cannot be pickled"
                )
        self._coordinator = coordinator
        self._functions = dict(node_functions)
        self._runtime = runtime
        self._on_event = on_event

    def run_level(self, specs: Sequence[NodeSpec]) -> dict[str, Any]:
        """Run every spec, returning label -> result or captured exception."""
        results: dict[str, Any] = {}
        spawned: list[tuple[str, Any, str]] = []

        for spec in specs:
            function = self._functions.get(spec.node_type)
            if function is None:
                results[spec.label] = NodeFailure(
                    f"no node function registered for {spec.node_type!r}"
                )
                continue
            if not spec.state.get(SPAWN_KEY, True):
                continue
            try:
                process, agent_id = self._coordinator.spawn_agent(function, (spec,))
                spawned.append((spec.label, process, agent_id))
            except Exception as failure:
                results[spec.label] = failure

        for label, _process, agent_id in spawned:
            try:
                results[label] = self._coordinator.await_result(agent_id)
            except Exception as failure:
                results[label] = failure

        for _label, process, _agent_id in spawned:
            process.join()

        for spec in specs:
            if spec.label in results or spec.state.get(SPAWN_KEY, True):
                continue
            function = self._functions[spec.node_type]
            try:
                results[spec.label] = function(self._runtime, spec)
            except Exception as failure:
                results[spec.label] = failure

        for label in results:
            self._on_event({"type": "phase_finished", "phase": label})
        return results
