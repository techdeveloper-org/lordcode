"""M6a: kgf actually reaches a real run, and the boundary holds.

These tests exist because kgf was fully built and fully unreachable. Every
assertion here is about the wiring rather than about kgf's own behaviour, which
its 333 tests already cover: does a run get a graph-selected persona, is the
persona's system prompt the assembled context rather than a truncated
description, does the phase DAG replace the complexity branch, and can the
orchestrator still only see kgf through the two modules allowed to import it.

No LLM call happens. The phase functions that would spawn model calls are
replaced with module-level fakes -- module-level because pickle stores a
function by qualified name, so a nested fake would be resolved in the child as
the real thing and issue a live call.
"""

from __future__ import annotations

import pathlib

import pytest

from vishwakarma.config import ModelConfig, ProviderConfig, RoleCandidate
from vishwakarma.engine import knowledge, orchestrator, parallel_generate
from vishwakarma.engine.executor import ExecutionResult
from vishwakarma.engine.generate import FileSpec, GeneratedArtifact
from vishwakarma.router import Router

FORCED_AGENT = "spring-boot-microservices"
"""A real agent, so the closure and context come from the live library.

Forced rather than ranked because this file tests the wiring, and pinning
selection keeps it from failing when the ranker changes -- kgf's own held-out
fixture is where accuracy is measured.
"""


class _TripwireClient:
    """Fails loudly if any real chat_completion is attempted.

    Carries _providers because that is where the orchestrator reads the TPM
    ceiling from, so a fake client without it would exercise the cap-disabled
    path rather than the real one.
    """

    def __init__(self):
        self._providers = _providers()

    def chat_completion(self, *args, **kwargs):
        raise AssertionError("no real LLM call should happen in these tests")


def _models() -> ModelConfig:
    return ModelConfig(
        roles={
            "reasoner": [RoleCandidate(provider="groq", model="reasoner")],
            "router_fast": [RoleCandidate(provider="groq", model="fast")],
            "fallback_long_context": [RoleCandidate(provider="groq", model="long")],
            "primary_coder": [RoleCandidate(provider="groq", model="coder")],
        },
        max_heal_attempts=3,
        heal_timeout_seconds=300,
    )


def _providers() -> dict:
    """Providers live on Config and are held by the CLIENT, not the router.

    Worth stating because getting it wrong is silent: ModelConfig carries only
    roles and limits, so reading a tpm_budget off the router yields nothing and
    the budget cap quietly disables itself.
    """
    return {
        "groq": ProviderConfig(
            name="groq",
            base_url="https://example.invalid",
            api_key_env="GROQ_API_KEY",
            rpm_budget=30,
            tpm_budget=6000,
        )
    }


QA_RUNS: list[int] = []


def _exploding_implementation(runtime, spec):
    """A phase:B that fails permanently. Module level: CoordinatorExecutor
    refuses a nested function outright, since spawn pickles by reference."""
    raise RuntimeError("generation blew up")


def _watched_qa(runtime, spec):
    """A phase:D that records whether it was reached at all."""
    QA_RUNS.append(1)
    return {}


def _fake_architecture(remote_llm, spec):
    """phase:A without a model call."""
    return "FILES:\n- OrderController.java: REST entry point\n"


def _fake_validation(remote_llm, spec):
    """phase:2 without a model call, approving immediately."""
    return {
        "blueprint": spec.state.get("upstream", {}).get(orchestrator.PHASE_ARCHITECTURE, ""),
        "approved": True,
        "verdict": "VERDICT: APPROVED",
        "rounds": [{"round": 1, "approved": True, "verdict": "VERDICT: APPROVED"}],
    }


@pytest.fixture
def captured(monkeypatch):
    """Run the pipeline with every model call stubbed, capturing generate()'s kwargs."""
    seen: dict = {}

    def fake_generate(task, language, router, client, **kwargs):
        seen.update(kwargs)
        seen["task"] = task
        return GeneratedArtifact(files=[FileSpec(path="OrderController.java", content="// x")])

    monkeypatch.setattr(orchestrator, "engineer_context", lambda *a, **k: "context block")
    monkeypatch.setattr(orchestrator, "engineer_prompt", lambda *a, **k: "add a REST endpoint for orders")
    monkeypatch.setattr(orchestrator, "detect_language", lambda *a, **k: "java")
    monkeypatch.setattr(orchestrator, "classify_complexity", lambda *a, **k: "complex")
    monkeypatch.setitem(orchestrator.PHASE_FUNCTIONS, orchestrator.PHASE_ARCHITECTURE, _fake_architecture)
    monkeypatch.setitem(orchestrator.PHASE_FUNCTIONS, orchestrator.PHASE_VALIDATION, _fake_validation)
    monkeypatch.setattr(
        parallel_generate,
        "plan_file_manifest",
        lambda *a, **k: [{"path": "OrderController.java", "responsibility": "REST entry point"}],
    )
    monkeypatch.setattr(orchestrator.generate_module, "generate", fake_generate)
    monkeypatch.setattr(orchestrator, "write_files", lambda *a, **k: None)
    monkeypatch.setattr(
        orchestrator,
        "run_tests",
        lambda *a, **k: ExecutionResult(passed=True, stdout="", stderr="", returncode=0),
    )
    return seen


def _run(tmp_path, events=None, **kwargs):
    client = _TripwireClient()
    router = Router(_models(), client)
    return orchestrator.run_task(
        "add a REST endpoint for creating an order",
        tmp_path,
        router,
        client,
        agent_name=FORCED_AGENT,
        on_event=(events.append if events is not None else (lambda event: None)),
        **kwargs,
    )


class TestTheGraphReachesTheRun:
    def test_the_selected_agent_is_recorded_on_the_result(self, tmp_path, captured):
        result = _run(tmp_path)
        assert result.agent_used == FORCED_AGENT

    def test_the_coder_receives_a_persona_with_the_graph_s_role(self, tmp_path, captured):
        """plugins.py defaulted every agent to primary_coder because 0 of 1562
        documents declare `role:`. The role now comes from kgf's classifier."""
        _run(tmp_path)
        subagent = captured["subagent"]
        assert subagent is not None
        assert subagent.name == FORCED_AGENT
        assert subagent.role == "primary_coder"

    def test_the_persona_prompt_is_assembled_context_not_a_truncated_description(
        self, tmp_path, captured
    ):
        """The defect this replaces: an 800-char position-blind head cut of one
        document, whose window ended at offset 796 while the section that
        matters began at 802."""
        _run(tmp_path)
        prompt = captured["subagent"].system_prompt
        assert len(prompt) > 800
        assert " :: " in prompt, "assembled context labels every section with its source"

    def test_the_context_covers_several_documents_not_one(self, tmp_path, captured):
        """One skill per run was the old ceiling, against a graph-asserted
        median of 4 mandatory skills."""
        _run(tmp_path)
        prompt = captured["subagent"].system_prompt
        sources = {line.split(" :: ")[0] for line in prompt.splitlines() if " :: " in line}
        assert len(sources) >= 2

    def test_the_assembled_context_is_not_truncated_by_the_caller(self, tmp_path, captured):
        """run_task's MUST NOT: it may not truncate AssembledContext.text."""
        _run(tmp_path)
        selection = knowledge.resolve(
            "add a REST endpoint for creating an order",
            forced_agent=FORCED_AGENT,
            budget_tokens=2000,
        )
        assert captured["subagent"].system_prompt == selection.context_text

    def test_selection_is_reported_as_an_event(self, tmp_path, captured):
        events = []
        _run(tmp_path, events=events)
        selections = [e for e in events if e.get("type") == "kgf_selection"]
        assert len(selections) == 1
        assert selections[0]["agent"] == FORCED_AGENT
        assert selections[0]["skills"] >= 1
        assert selections[0]["context_tokens"] > 0


class TestThePhaseDagReplacesTheComplexityBranch:
    def test_a_complex_task_runs_all_four_phases(self, tmp_path, captured):
        events = []
        _run(tmp_path, events=events)
        completed = [e for e in events if e.get("type") == "phases_completed"]
        assert len(completed) == 1
        assert set(completed[0]["completed"]) == {
            orchestrator.PHASE_ARCHITECTURE,
            orchestrator.PHASE_VALIDATION,
            orchestrator.PHASE_IMPLEMENTATION,
            orchestrator.PHASE_QA,
        }
        assert completed[0]["failed"] == []
        assert completed[0]["skipped"] == []

    def test_a_simple_task_prunes_architecture_and_validation(self, tmp_path, captured, monkeypatch):
        """Complexity now selects a subgraph instead of a code path, which is
        what the library's own D13::B2 branch does."""
        monkeypatch.setattr(orchestrator, "classify_complexity", lambda *a, **k: "simple")
        events = []
        _run(tmp_path, events=events)
        completed = [e for e in events if e.get("type") == "phases_completed"][0]
        assert set(completed["completed"]) == {
            orchestrator.PHASE_IMPLEMENTATION,
            orchestrator.PHASE_QA,
        }

    def test_the_blueprint_reaches_implementation_through_the_dag(self, tmp_path, captured):
        """Phases connect, not merely order: the context handed to the coder
        carries the blueprint phase:A produced two levels earlier."""
        _run(tmp_path)
        assert "Implementation plan:" in captured["context"]
        assert "OrderController.java: REST entry point" in captured["context"]

    def test_a_pruned_phase_does_not_strand_implementation(self, tmp_path, captured, monkeypatch):
        """Pruning splices: with validation gone, implementation must still run
        rather than wait on a dependency that no longer exists."""
        monkeypatch.setattr(orchestrator, "classify_complexity", lambda *a, **k: "simple")
        result = _run(tmp_path)
        assert result.passed is True
        assert result.plan is None

    def test_the_levels_are_reported_in_order(self, tmp_path, captured):
        events = []
        _run(tmp_path, events=events)
        levels = [e for e in events if e.get("type") == "phases_completed"][0]["levels"]
        assert levels == [
            [orchestrator.PHASE_ARCHITECTURE],
            [orchestrator.PHASE_VALIDATION],
            [orchestrator.PHASE_IMPLEMENTATION],
            [orchestrator.PHASE_QA],
        ]


class TestFailureHandling:
    def test_an_unreadable_library_is_a_hard_error_naming_the_path(self, tmp_path, captured):
        """The fourth outcome exists so a missing library cannot look like a
        hard task. Collapsing it into no_match is the bug class M6a replaces."""
        knowledge.reset_cache()
        try:
            with pytest.raises(knowledge.KnowledgeUnavailable) as raised:
                _run(tmp_path, library=tmp_path / "not-a-library")
            assert "not-a-library" in str(raised.value)
        finally:
            knowledge.reset_cache()

    def test_a_failed_phase_names_itself_and_its_reason(self, tmp_path, captured, monkeypatch):
        """The first version of this message reported only the QA and
        implementation phases' own error, and a SKIPPED phase carries none --
        so an upstream failure surfaced as "did not complete:" with nothing
        after the colon."""
        monkeypatch.setitem(
            orchestrator.PHASE_FUNCTIONS, orchestrator.PHASE_IMPLEMENTATION, _exploding_implementation
        )
        with pytest.raises(Exception) as raised:
            _run(tmp_path)
        message = str(raised.value)
        assert "phase:B failed" in message
        assert "generation blew up" in message
        assert "phase:D skipped because phase:B did not complete" in message

    def test_a_failed_implementation_skips_qa_rather_than_testing_nothing(
        self, tmp_path, captured, monkeypatch
    ):
        QA_RUNS.clear()
        monkeypatch.setitem(
            orchestrator.PHASE_FUNCTIONS, orchestrator.PHASE_IMPLEMENTATION, _exploding_implementation
        )
        monkeypatch.setitem(orchestrator.PHASE_FUNCTIONS, orchestrator.PHASE_QA, _watched_qa)
        with pytest.raises(Exception):
            _run(tmp_path)
        assert QA_RUNS == []


class TestTheBoundary:
    """ADR-2 and M6a's MUST NOT, enforced rather than intended."""

    def test_only_the_boundary_modules_import_kgf(self):
        """parallel_generate.py is on this list on purpose: M5.1 moved the
        union-find, Tarjan SCC, depth-tier and wave machinery into kgf/dag.py
        precisely so that module would consume it instead of keeping a second
        copy. It is a kgf consumer by design, not a boundary leak."""
        allowed = {"knowledge.py", "dag_executor.py", "parallel_generate.py"}
        offenders = []
        for path in pathlib.Path("vishwakarma").rglob("*.py"):
            if path.name in allowed:
                continue
            text = path.read_text(encoding="utf-8")
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith(("import kgf", "from kgf")):
                    offenders.append(f"{path}: {stripped}")
        assert offenders == [], offenders

    def test_the_orchestrator_reaches_kgf_only_through_those_two(self):
        text = pathlib.Path("vishwakarma/engine/orchestrator.py").read_text(encoding="utf-8")
        assert "from vishwakarma.engine import knowledge" in text
        assert "from vishwakarma.engine.dag_executor import" in text
        assert "import kgf" not in text

    def test_the_dead_routing_path_is_no_longer_called(self):
        """kg_routing.py still exists -- deleting it is M6b, gated on this
        passing live -- but run_task must no longer reach for it."""
        text = pathlib.Path("vishwakarma/engine/orchestrator.py").read_text(encoding="utf-8")
        assert "route_persona" not in text
        assert "match_skill" not in text


class TestTheTriStateOutcomes:
    """All four selection outcomes are consumed as four outcomes.

    The dominant one in practice is low_confidence, not selected: on kgf's
    frozen 33-case set only 7 tasks clear the 0.45 confidence floor, so most
    real runs take the middle path asserted here. Collapsing it into either
    neighbour would either steer the coder with a match kgf does not trust, or
    throw away a correct closure -- and 4 of those 26 low-confidence answers
    were measured correct at the domain level.
    """

    def _selection(self, outcome, **kwargs):
        return knowledge.Knowledge(
            outcome=outcome,
            library_version="test",
            agent="agent:x",
            agent_name="x",
            domain="domain:d",
            confidence=0.4,
            role="primary_coder",
            context_text="--- x :: Coding Guidelines ---\nrule one\n",
            **kwargs,
        )

    def test_low_confidence_contributes_context_but_no_persona(self, tmp_path, captured, monkeypatch):
        monkeypatch.setattr(
            knowledge, "resolve", lambda *a, **k: self._selection("low_confidence")
        )
        _run(tmp_path)
        assert captured["subagent"] is None
        assert "Coding Guidelines" in captured["context"]

    def test_selected_contributes_a_persona_and_keeps_context_separate(
        self, tmp_path, captured, monkeypatch
    ):
        monkeypatch.setattr(knowledge, "resolve", lambda *a, **k: self._selection("selected"))
        _run(tmp_path)
        assert captured["subagent"] is not None
        assert "Coding Guidelines" in captured["subagent"].system_prompt
        assert "Coding Guidelines" not in (captured["context"] or "")

    def test_no_match_contributes_neither(self, tmp_path, captured, monkeypatch):
        monkeypatch.setattr(
            knowledge,
            "resolve",
            lambda *a, **k: knowledge.Knowledge(outcome="no_match", library_version="test"),
        )
        result = _run(tmp_path)
        assert captured["subagent"] is None
        assert result.agent_used is None
        assert result.passed is True

    def test_a_low_confidence_run_still_records_no_agent_used(self, tmp_path, captured, monkeypatch):
        """The match is reported through the event stream, not by pretending a
        persona was applied."""
        monkeypatch.setattr(
            knowledge, "resolve", lambda *a, **k: self._selection("low_confidence")
        )
        result = _run(tmp_path)
        assert result.agent_used is None
