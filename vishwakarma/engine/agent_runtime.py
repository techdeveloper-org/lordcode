"""Real OS-process agent spawning, funneled through one rate-limited caller.

Milestone 1.5 of the full-SDLC roadmap: ORCHESTRATION_TEMPLATE.md assumes a
session that can spawn genuinely independent agents (their own process,
running concurrently where the task DAG allows). Vishwakarma's roles
(context-engineer, prompt-engineer, solution-architect, consensus-reviewer)
were previously just sequential in-process function calls sharing one
persona-switching system prompt each -- not literally separate agents.

This module makes the spawning real (multiprocessing.Process per agent)
while keeping exactly one Router/LLMClient/RateLimiter alive, in the
coordinator process, as the sole path that ever calls the Groq API. Every
spawned agent process sends its model-call requests back to the coordinator
over a multiprocessing.Queue instead of building its own LLMClient --
Router._active_index and RateLimiter's token bucket are both plain
in-process state (see engine/calling.py, engine/rate_limiter.py) that
cannot be safely shared or reconstructed per-process without silently
multiplying the account's real rpm_budget by the number of live processes.
"""

from __future__ import annotations

import multiprocessing
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from vishwakarma.engine.calling import OnEvent, call_role, noop_event
from vishwakarma.llm_client import LLMClient
from vishwakarma.router import Router

_POLL_TIMEOUT_SECONDS = 0.2


@dataclass
class AgentCallRequest:
    """One model-call request sent from a spawned agent process to the coordinator."""

    agent_id: str
    role: str
    purpose: str
    messages: list[dict[str, str]]
    priority: str = "interactive"
    light_reasoning: bool = False
    kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentCallResponse:
    """The coordinator's reply to one AgentCallRequest."""

    agent_id: str
    text: str | None = None
    error: str | None = None


class RemoteLLM:
    """Picklable proxy an agent process uses in place of a real Router/LLMClient.

    Holds only a shared request queue (into the coordinator) and this
    agent's own private reply queue -- both multiprocessing.Queue objects,
    which is the one kind of otherwise-unshareable object multiprocessing
    knows how to hand to a child process at spawn time.
    """

    def __init__(self, agent_id: str, request_queue: "multiprocessing.Queue[AgentCallRequest]", reply_queue: "multiprocessing.Queue[AgentCallResponse]"):
        self._agent_id = agent_id
        self._request_queue = request_queue
        self._reply_queue = reply_queue

    def call_role(
        self,
        role: str,
        purpose: str,
        messages: list[dict[str, str]],
        priority: str = "interactive",
        light_reasoning: bool = False,
        **kwargs: Any,
    ) -> str:
        """Same call shape as engine.calling.call_role, routed through the coordinator."""
        self._request_queue.put(
            AgentCallRequest(
                agent_id=self._agent_id,
                role=role,
                purpose=purpose,
                messages=messages,
                priority=priority,
                light_reasoning=light_reasoning,
                kwargs=kwargs,
            )
        )
        response = self._reply_queue.get()
        if response.error is not None:
            raise RuntimeError(response.error)
        return response.text


@dataclass
class AgentSpec:
    """One agent to spawn: a module-level persona function plus its arguments.

    persona_fn must be importable at module level (spawn pickles the
    target), and its first parameter must be a RemoteLLM.
    """

    label: str
    persona_fn: Callable[..., Any]
    args: tuple[Any, ...] = ()


def _agent_process_main(
    persona_fn: Callable[..., Any],
    remote_llm: RemoteLLM,
    args: tuple[Any, ...],
    agent_id: str,
    result_queue: "multiprocessing.Queue[tuple[str, str, Any]]",
) -> None:
    """Entry point run inside the spawned agent process."""
    try:
        result = persona_fn(remote_llm, *args)
        result_queue.put((agent_id, "ok", result))
    except Exception as exc:  # noqa: BLE001 -- deliberately broad: must reach the coordinator, not crash silently
        result_queue.put((agent_id, "error", str(exc)))


def _dispatcher_loop(
    request_queue: "multiprocessing.Queue[AgentCallRequest]",
    reply_queues: dict[str, "multiprocessing.Queue[AgentCallResponse]"],
    router: Router,
    client: LLMClient,
    on_event: OnEvent,
    stop_event: threading.Event,
) -> None:
    """Single funnel: every agent's model calls flow through here, in the
    coordinator process, against the one real Router/LLMClient/RateLimiter.
    """
    while not stop_event.is_set():
        try:
            request = request_queue.get(timeout=_POLL_TIMEOUT_SECONDS)
        except queue.Empty:
            continue
        try:
            text = call_role(
                request.role,
                request.purpose,
                request.messages,
                router,
                client,
                priority=request.priority,
                on_event=on_event,
                light_reasoning=request.light_reasoning,
                **request.kwargs,
            )
            response = AgentCallResponse(agent_id=request.agent_id, text=text)
        except Exception as exc:  # noqa: BLE001 -- must reach the waiting agent process, not crash the dispatcher
            response = AgentCallResponse(agent_id=request.agent_id, error=str(exc))
        reply_queues[request.agent_id].put(response)


class AgentCoordinator:
    """Owns the shared request queue and dispatcher thread for one run.

    Construct once per pipeline run (mirrors how `router`/`client` are
    already constructed once and threaded through run_task/sdlc.py), spawn
    agents through it, and call stop() when the run finishes.
    """

    def __init__(self, router: Router, client: LLMClient, on_event: OnEvent = noop_event):
        self._router = router
        self._client = client
        self._on_event = on_event
        self._mp_context = multiprocessing.get_context("spawn")
        self._request_queue: "multiprocessing.Queue[AgentCallRequest]" = self._mp_context.Queue()
        self._result_queue: "multiprocessing.Queue[tuple[str, str, Any]]" = self._mp_context.Queue()
        self._reply_queues: dict[str, "multiprocessing.Queue[AgentCallResponse]"] = {}
        self._pending_results: dict[str, tuple[str, Any]] = {}
        self._stop_event = threading.Event()
        self._dispatcher_thread = threading.Thread(
            target=_dispatcher_loop,
            args=(self._request_queue, self._reply_queues, router, client, on_event, self._stop_event),
            daemon=True,
        )
        self._dispatcher_thread.start()

    def stop(self) -> None:
        """Stop the dispatcher thread. Call once the run is complete."""
        self._stop_event.set()
        self._dispatcher_thread.join(timeout=5)

    def spawn_agent(self, persona_fn: Callable[..., Any], args: tuple[Any, ...]) -> tuple["multiprocessing.Process", str]:
        """Start one real OS process running persona_fn(RemoteLLM, *args)."""
        agent_id = uuid.uuid4().hex
        reply_queue: "multiprocessing.Queue[AgentCallResponse]" = self._mp_context.Queue()
        self._reply_queues[agent_id] = reply_queue
        remote_llm = RemoteLLM(agent_id, self._request_queue, reply_queue)
        process = self._mp_context.Process(
            target=_agent_process_main,
            args=(persona_fn, remote_llm, args, agent_id, self._result_queue),
        )
        started = time.monotonic()
        process.start()
        self._on_event(
            {"type": "agent_spawned", "agent_id": agent_id, "persona": persona_fn.__name__, "pid": process.pid}
        )
        self._spawn_times = getattr(self, "_spawn_times", {})
        self._spawn_times[agent_id] = started
        return process, agent_id

    def await_result(self, agent_id: str) -> Any:
        """Block until agent_id's spawned process has a result, then return it.

        Public so callers needing branching logic (e.g. run_task's bounded
        2-round consensus loop) can spawn/await one stage at a time instead
        of going through run_agents_pipeline's straight-line chain shape.
        """
        return self._await_result(agent_id)

    def _await_result(self, agent_id: str) -> Any:
        while agent_id not in self._pending_results:
            arrived_id, status, payload = self._result_queue.get()
            self._pending_results[arrived_id] = (status, payload)
        status, payload = self._pending_results.pop(agent_id)
        started = getattr(self, "_spawn_times", {}).pop(agent_id, None)
        duration_ms = int((time.monotonic() - started) * 1000) if started is not None else None
        self._on_event({"type": "agent_completed", "agent_id": agent_id, "duration_ms": duration_ms})
        self._reply_queues.pop(agent_id, None)
        if status == "error":
            raise RuntimeError(payload)
        return payload

    def run_agents_pipeline(self, specs: list[tuple[Callable[..., Any], Callable[[Any], tuple[Any, ...]]]]) -> Any:
        """Spawn one agent process per stage, feeding stage N's output into stage N+1's args.

        Args:
            specs: (persona_fn, args_builder) pairs, in order. args_builder
                receives the prior stage's result (None for the first stage)
                and returns the args tuple for the next persona_fn.
        """
        result: Any = None
        for persona_fn, args_builder in specs:
            args = args_builder(result)
            process, agent_id = self.spawn_agent(persona_fn, args)
            process.join()
            result = self._await_result(agent_id)
        return result

    def run_agents_parallel(self, specs: list[AgentSpec]) -> dict[str, Any]:
        """Spawn every spec as its own OS process simultaneously; wait for all.

        Reads each agent's result from the shared result queue BEFORE
        joining any process -- joining first is a classic multiprocessing
        deadlock: a child blocks inside its Queue's feeder thread once the
        OS pipe buffer fills (e.g. several large generated-code payloads
        written to the one shared result queue with no reader yet), while
        the parent blocks in process.join() waiting for a child that can
        never finish exiting until someone drains the queue. Draining first
        unblocks every child's feeder thread; the subsequent join() calls
        then return immediately since the children have already finished.
        """
        spawned = [(spec.label, *self.spawn_agent(spec.persona_fn, spec.args)) for spec in specs]
        results = {label: self._await_result(agent_id) for label, _process, agent_id in spawned}
        for _label, process, _agent_id in spawned:
            process.join()
        return results
