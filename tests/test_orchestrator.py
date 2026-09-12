"""Unit tests for Milestone 8's orchestrator.run_task branching:
complex-task manifest planning -> parallel or single-call generation,
simple tasks entirely untouched, and a manifest-planning failure falling
back to the single-call path instead of failing the whole task.

Every spawned persona (solution architect, consensus review, file-manifest
planning, subset generation) is replaced with a module-level fake that
never calls remote_llm.call_role at all -- proving these tests exercise
run_task's own branching logic, not the LLM call machinery already covered
by other test files. AgentCoordinator still requires a constructible
Router/LLMClient, so a FakeClient that raises on any chat_completion call
is used as a tripwire: if a test ever accidentally reaches a real call
site, it fails loudly instead of hanging on real network I/O.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vishwakarma.config import ModelConfig, RoleCandidate
from vishwakarma.engine import orchestrator, parallel_generate
from vishwakarma.engine.executor import ExecutionResult
from vishwakarma.engine.generate import FileSpec, GeneratedArtifact, GenerationError
from vishwakarma.router import Router


class _TripwireClient:
    """Raises if any real chat_completion call is ever attempted."""

    def chat_completion(self, *args, **kwargs):
        raise AssertionError("No real LLM call should happen in these tests")


def _models() -> ModelConfig:
    return ModelConfig(
        roles={
            "reasoner": [RoleCandidate(provider="groq", model="reasoner")],
            "router_fast": [RoleCandidate(provider="groq", model="fast")],
            "fallback_long_context": [RoleCandidate(provider="groq", model="long-context")],
            "primary_coder": [RoleCandidate(provider="groq", model="coder")],
        },
        max_heal_attempts=3,
        heal_timeout_seconds=300,
    )


def _fake_persona_solution_architect(remote_llm, task, language, context, revision_feedback):
    return "FILES:\n- app.py: main entrypoint\n"


def _fake_persona_consensus_review(remote_llm, task, blueprint, round_number):
    return True, "VERDICT: APPROVED\nREASON: fine."


@pytest.fixture(autouse=True)
def _stub_pipeline_scaffolding(monkeypatch):
    """Bypass everything upstream/downstream of the generation call site
    that Milestone 8's branching logic doesn't touch."""
    monkeypatch.setattr(orchestrator, "engineer_context", lambda *a, **k: "context block")
    monkeypatch.setattr(orchestrator, "engineer_prompt", lambda *a, **k: "engineered task")
    monkeypatch.setattr(orchestrator, "detect_language", lambda *a, **k: "python")
    monkeypatch.setattr(orchestrator, "load_all_skills", lambda: [])
    monkeypatch.setattr(orchestrator, "load_all_agents", lambda: [])
    monkeypatch.setattr(orchestrator, "match_skill", lambda *a, **k: None)
    monkeypatch.setattr(orchestrator, "route_persona", lambda *a, **k: None)
    monkeypatch.setattr(orchestrator, "_persona_solution_architect", _fake_persona_solution_architect)
    monkeypatch.setattr(orchestrator, "_persona_consensus_review", _fake_persona_consensus_review)
    monkeypatch.setattr(orchestrator, "write_files", lambda *a, **k: None)
    monkeypatch.setattr(
        orchestrator, "run_tests", lambda *a, **k: ExecutionResult(passed=True, stdout="", stderr="", returncode=0)
    )


def _run(task_text: str, workdir: Path, complexity: str, monkeypatch):
    monkeypatch.setattr(orchestrator, "classify_complexity", lambda *a, **k: complexity)
    client = _TripwireClient()
    router = Router(_models(), client)
    return orchestrator.run_task(task_text, workdir, router, client)


def test_simple_task_never_calls_plan_file_manifest(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(parallel_generate, "plan_file_manifest", lambda *a, **k: called.append(1))
    monkeypatch.setattr(
        orchestrator.generate_module, "generate",
        lambda *a, **k: GeneratedArtifact(files=[FileSpec(path="app.py", content="pass")]),
    )

    result = _run("a simple task", tmp_path, "simple", monkeypatch)

    assert called == []
    assert result.complexity == "simple"
    assert result.passed is True


def test_complex_task_with_small_manifest_falls_back_to_single_call(tmp_path, monkeypatch):
    monkeypatch.setattr(
        parallel_generate, "plan_file_manifest",
        lambda *a, **k: [{"path": "app.py", "responsibility": "main"}],
    )
    parallel_called = []
    monkeypatch.setattr(
        parallel_generate, "generate_parallel", lambda *a, **k: parallel_called.append(1)
    )
    monkeypatch.setattr(
        orchestrator.generate_module, "generate",
        lambda *a, **k: GeneratedArtifact(files=[FileSpec(path="app.py", content="pass")]),
    )

    result = _run("a complex task", tmp_path, "complex", monkeypatch)

    assert parallel_called == []
    assert result.passed is True


def test_complex_task_with_large_manifest_uses_generate_parallel(tmp_path, monkeypatch):
    manifest = [{"path": f"f{i}.py", "responsibility": "x"} for i in range(6)]
    monkeypatch.setattr(parallel_generate, "plan_file_manifest", lambda *a, **k: manifest)
    single_call_used = []
    monkeypatch.setattr(
        orchestrator.generate_module, "generate", lambda *a, **k: single_call_used.append(1)
    )
    monkeypatch.setattr(
        parallel_generate, "generate_parallel",
        lambda *a, **k: GeneratedArtifact(files=[FileSpec(path=f"f{i}.py", content="x") for i in range(6)]),
    )

    result = _run("a complex task with many files", tmp_path, "complex", monkeypatch)

    assert single_call_used == []
    assert result.passed is True
    assert len(result.final_files) == 6


def test_manifest_planning_failure_falls_back_to_single_call(tmp_path, monkeypatch):
    monkeypatch.setattr(
        parallel_generate, "plan_file_manifest",
        lambda *a, **k: (_ for _ in ()).throw(GenerationError("manifest boom")),
    )
    monkeypatch.setattr(
        orchestrator.generate_module, "generate",
        lambda *a, **k: GeneratedArtifact(files=[FileSpec(path="app.py", content="pass")]),
    )
    events = []

    client = _TripwireClient()
    router = Router(_models(), client)
    monkeypatch.setattr(orchestrator, "classify_complexity", lambda *a, **k: "complex")

    result = orchestrator.run_task("a complex task", tmp_path, router, client, on_event=events.append)

    assert result.passed is True
    assert any(e["type"] == "manifest_planning_failed" and "manifest boom" in e["reason"] for e in events)
