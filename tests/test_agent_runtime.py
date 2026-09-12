"""Unit tests for Milestone 1.5's real OS-process agent spawning.

Uses a mocked LLM client (same FakeClient pattern as tests/test_sdlc.py) so
no real API calls are made. Persona functions must be module-level (not
closures) because multiprocessing's spawn start method pickles the target.
"""

from __future__ import annotations

import threading

import pytest

from vishwakarma.config import ModelConfig, RoleCandidate
from vishwakarma.engine.agent_runtime import AgentCoordinator, AgentSpec
from vishwakarma.router import Router


class FakeClient:
    """Returns queued responses in order, one per chat_completion call."""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.call_log: list[str] = []

    def chat_completion(
        self, provider: str, model: str, messages: list[dict], priority: str = "interactive", **kwargs
    ) -> str:
        self.call_log.append(f"{provider}/{model}")
        return self.responses.pop(0)


def _models() -> ModelConfig:
    return ModelConfig(
        roles={"reasoner": [RoleCandidate(provider="groq", model="reasoner")]},
        max_heal_attempts=3,
        heal_timeout_seconds=300,
    )


def _echo_persona(remote_llm, text: str) -> str:
    return remote_llm.call_role("reasoner", "echo", [{"role": "user", "content": text}])


def _pipeline_stage_persona(remote_llm, prev: str | None) -> str:
    suffix = remote_llm.call_role("reasoner", "stage", [{"role": "user", "content": str(prev)}])
    return f"{prev}->{suffix}" if prev else suffix


def _dispatcher_error_persona(remote_llm, text: str) -> str:
    # "reasoner-missing" has no configured candidates -- Router.resolve raises
    # KeyError inside the dispatcher, which must surface here as RuntimeError,
    # not a hang on reply_queue.get().
    return remote_llm.call_role("reasoner-missing", "x", [{"role": "user", "content": text}])


def _raises_locally_persona(remote_llm, _unused: str) -> str:
    raise ValueError("boom from inside the agent process")


def _large_echo_persona(remote_llm, text: str) -> str:
    return remote_llm.call_role("reasoner", "echo large", [{"role": "user", "content": text}])


def test_remote_llm_call_role_round_trips(tmp_path):
    client = FakeClient(["hello back"])
    router = Router(_models(), client)
    coordinator = AgentCoordinator(router, client)
    try:
        process, agent_id = coordinator.spawn_agent(_echo_persona, ("hello",))
        process.join(timeout=30)
        result = coordinator._await_result(agent_id)
        assert result == "hello back"
    finally:
        coordinator.stop()


def test_run_agents_pipeline_feeds_stage_output_into_next(tmp_path):
    client = FakeClient(["A", "B", "C"])
    router = Router(_models(), client)
    coordinator = AgentCoordinator(router, client)
    try:
        result = coordinator.run_agents_pipeline(
            [
                (_pipeline_stage_persona, lambda _prev: (None,)),
                (_pipeline_stage_persona, lambda prev: (prev,)),
                (_pipeline_stage_persona, lambda prev: (prev,)),
            ]
        )
        assert result == "A->B->C"
    finally:
        coordinator.stop()


def test_run_agents_parallel_returns_all_results_keyed_by_label(tmp_path):
    client = FakeClient(["one", "two"])
    router = Router(_models(), client)
    coordinator = AgentCoordinator(router, client)
    try:
        results = coordinator.run_agents_parallel(
            [
                AgentSpec(label="first", persona_fn=_echo_persona, args=("x",)),
                AgentSpec(label="second", persona_fn=_echo_persona, args=("y",)),
            ]
        )
        assert set(results.keys()) == {"first", "second"}
        assert set(results.values()) == {"one", "two"}
    finally:
        coordinator.stop()


def test_run_agents_parallel_does_not_deadlock_on_large_payloads(tmp_path):
    """Live-discovered regression (Milestone 8): run_agents_parallel used to
    join every process before reading any result from the shared result
    queue -- a classic multiprocessing deadlock once combined payload size
    exceeds the OS pipe buffer (each child's Queue feeder thread blocks
    writing, while the parent blocks in process.join() waiting for a child
    that can never finish exiting). Every prior real caller only ever
    returned small payloads (diagram text, verdict strings), so this was
    never triggered until Milestone 8's parallel code-generation calls
    pushed genuinely large (tens of KB) results through this same path.

    Bounded via a background thread + timeout so a regression fails this
    test cleanly instead of hanging the whole suite.
    """
    large_payload = "x" * 200_000  # comfortably exceeds a typical OS pipe buffer
    client = FakeClient([large_payload, large_payload, large_payload, large_payload])
    router = Router(_models(), client)
    coordinator = AgentCoordinator(router, client)

    outcome: dict = {}

    def run():
        try:
            outcome["results"] = coordinator.run_agents_parallel(
                [AgentSpec(label=f"group-{i}", persona_fn=_large_echo_persona, args=(f"text-{i}",)) for i in range(4)]
            )
        except Exception as exc:  # noqa: BLE001 -- surfaced via outcome, not raised in this thread
            outcome["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(timeout=30)

    try:
        assert not thread.is_alive(), "run_agents_parallel deadlocked on large payloads"
        assert "error" not in outcome, outcome.get("error")
        assert len(outcome["results"]) == 4
        assert all(v == large_payload for v in outcome["results"].values())
    finally:
        coordinator.stop()


def test_dispatcher_side_error_surfaces_without_hanging(tmp_path):
    client = FakeClient([])
    router = Router(_models(), client)
    coordinator = AgentCoordinator(router, client)
    try:
        process, agent_id = coordinator.spawn_agent(_dispatcher_error_persona, ("x",))
        process.join(timeout=30)
        with pytest.raises(RuntimeError):
            coordinator._await_result(agent_id)
    finally:
        coordinator.stop()


def test_persona_local_error_surfaces_without_hanging(tmp_path):
    client = FakeClient([])
    router = Router(_models(), client)
    coordinator = AgentCoordinator(router, client)
    try:
        process, agent_id = coordinator.spawn_agent(_raises_locally_persona, ("x",))
        process.join(timeout=30)
        with pytest.raises(RuntimeError, match="boom from inside the agent process"):
            coordinator._await_result(agent_id)
    finally:
        coordinator.stop()
