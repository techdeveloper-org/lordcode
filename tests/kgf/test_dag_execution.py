"""Tests for the execution half of kgf/dag.py.

Node executors must be module level, so every executor in this file is too --
which is also the point: a test that registered a closure would pass here and
fail inside a spawned child, exactly the failure mode the registry exists to
move forward in time.
"""

from __future__ import annotations

import threading

import pytest

from kgf.dag import (
    CyclePolicy,
    DependencyCycleError,
    FailureClass,
    InProcessExecutor,
    NodeFailure,
    NodeSpec,
    Outcome,
    clear_node_types,
    concurrency_cap,
    level_cap,
    node_type,
    register_node_type,
    registered_node_types,
    resolve_node_executor,
    run_dag,
    unpicklable_fields,
)

CALL_LOG: list[str] = []
ATTEMPTS: dict[str, int] = {}


def echo_node(spec: NodeSpec):
    """Succeed, recording that this node ran."""
    CALL_LOG.append(spec.label)
    return f"{spec.label}:done"


def permanent_node(spec: NodeSpec):
    """Fail in a way no retry could fix."""
    CALL_LOG.append(spec.label)
    raise NodeFailure("validation rejected the artefact", failure_class=FailureClass.PERMANENT)


def transient_node(spec: NodeSpec):
    """Fail transiently forever."""
    CALL_LOG.append(spec.label)
    raise NodeFailure("upstream timed out", failure_class=FailureClass.TRANSIENT)


def flaky_node(spec: NodeSpec):
    """Fail transiently once, then succeed."""
    CALL_LOG.append(spec.label)
    ATTEMPTS[spec.label] = ATTEMPTS.get(spec.label, 0) + 1
    if ATTEMPTS[spec.label] == 1:
        raise NodeFailure("429 from the provider", failure_class=FailureClass.TRANSIENT)
    return f"{spec.label}:recovered"


def exploding_node(spec: NodeSpec):
    """Raise something that is not a NodeFailure at all."""
    CALL_LOG.append(spec.label)
    raise RuntimeError("an exception nobody reasoned about")


@pytest.fixture(autouse=True)
def registry():
    """A clean registry and call log per test."""
    clear_node_types()
    CALL_LOG.clear()
    ATTEMPTS.clear()
    register_node_type("echo", echo_node)
    register_node_type("permanent", permanent_node)
    register_node_type("transient", transient_node)
    register_node_type("flaky", flaky_node)
    register_node_type("explode", exploding_node)
    yield
    clear_node_types()


def spec(label: str, kind: str = "echo", **kwargs) -> NodeSpec:
    """One NodeSpec, keeping the tests readable."""
    return NodeSpec(label=label, node_type=kind, **kwargs)


class TestTheRegistry:
    def test_a_registered_type_resolves(self):
        assert resolve_node_executor("echo") is echo_node

    def test_registering_the_same_function_twice_is_fine(self):
        register_node_type("echo", echo_node)
        assert resolve_node_executor("echo") is echo_node

    def test_rebinding_a_type_to_a_different_function_is_refused(self):
        with pytest.raises(ValueError, match="already registered"):
            register_node_type("echo", permanent_node)

    def test_a_lambda_is_refused(self):
        """It would pickle badly or not at all, inside a child process."""
        with pytest.raises(ValueError, match="not a lambda"):
            register_node_type("nope", lambda spec: None)

    def test_a_nested_function_is_refused(self):
        def inner(spec):
            return None

        with pytest.raises(ValueError, match="nested"):
            register_node_type("nope", inner)

    def test_an_unknown_type_names_what_is_registered(self):
        with pytest.raises(KeyError, match="echo"):
            resolve_node_executor("does-not-exist")

    def test_the_decorator_form_registers(self):
        """Applied to a module-level function, which is the only kind the
        registry accepts -- a decorator on a nested def is refused, as the
        test above asserts."""
        assert node_type("decorated")(echo_node) is echo_node
        assert "decorated" in registered_node_types()
        assert resolve_node_executor("decorated") is echo_node


class TestPicklability:
    def test_a_plain_spec_is_picklable(self):
        assert unpicklable_fields(spec("a", state={"language": "java", "budget": 2000})) == ()

    def test_an_unpicklable_state_value_is_named(self):
        """Stands in for the real hazard: a KnowledgeGraph or an open handle
        placed in state, which spawn would try to pickle per node."""
        assert unpicklable_fields(spec("a", state={"lock": threading.Lock()})) == ("state",)

    def test_the_executor_refuses_an_unpicklable_spec_rather_than_running_it(self):
        results = InProcessExecutor().run_level([spec("a", state={"lock": threading.Lock()})])
        assert isinstance(results["a"], NodeFailure)
        assert "unpicklable state" in str(results["a"])
        assert CALL_LOG == []


class TestInProcessExecutor:
    def test_it_returns_a_value_per_label(self):
        assert InProcessExecutor().run_level([spec("a"), spec("b")]) == {
            "a": "a:done",
            "b": "b:done",
        }

    def test_a_failure_comes_back_as_a_value_not_an_exception(self):
        """The port's MUST NOT: raising would lose every sibling's result."""
        results = InProcessExecutor().run_level([spec("a"), spec("b", "permanent"), spec("c")])
        assert results["a"] == "a:done"
        assert isinstance(results["b"], NodeFailure)
        assert results["c"] == "c:done"

    def test_events_are_emitted_per_node(self):
        seen: list[dict] = []
        InProcessExecutor(on_event=seen.append).run_level([spec("a"), spec("b")])
        assert [event["label"] for event in seen] == ["a", "b"]


class TestBudgetCap:
    def test_the_generate_node_floors_to_zero_and_is_clamped(self):
        """The measured case: MAX_CODER_TOKENS = 8000 alone exceeds ~6000 TPM,
        so this node is paced across minutes no matter the context size."""
        warnings: list[str] = []
        assert concurrency_cap(6000, 2000, 8000, on_warning=warnings.append) == 1
        assert len(warnings) == 1
        assert "minutes per call" in warnings[0]

    def test_a_cheap_node_admits_many(self):
        warnings: list[str] = []
        assert concurrency_cap(6000, 300, 60, on_warning=warnings.append) == 16
        assert warnings == []

    def test_a_zero_cost_node_does_not_divide_by_zero(self):
        assert concurrency_cap(6000, 0, 0) == 1

    def test_a_level_is_capped_by_its_most_expensive_node(self):
        specs = [
            spec("cheap", ctx_tokens=300, max_completion_tokens=60),
            spec("dear", ctx_tokens=2000, max_completion_tokens=8000),
        ]
        assert level_cap(specs, 6000) == 1

    def test_a_level_cap_never_exceeds_its_total_calls(self):
        specs = [spec("a", ctx_tokens=100, max_completion_tokens=50)]
        assert level_cap(specs, 6000) == 1

    def test_a_node_making_several_calls_counts_several_times(self):
        specs = [spec("a", calls=3, ctx_tokens=100, max_completion_tokens=50)]
        assert level_cap(specs, 6000) == 3

    def test_an_empty_level_caps_at_one(self):
        assert level_cap([], 6000) == 1


class TestRunDag:
    def test_nodes_run_in_dependency_order(self):
        report = run_dag(
            [spec("a"), spec("b"), spec("c")],
            {"b": {"a"}, "c": {"b"}},
            InProcessExecutor(),
        )
        assert report.ok
        assert CALL_LOG == ["a", "b", "c"]
        assert report.levels == [["a"], ["b"], ["c"]]

    def test_completed_values_are_returned(self):
        report = run_dag([spec("a"), spec("b")], {"b": {"a"}}, InProcessExecutor())
        assert report.values() == {"a": "a:done", "b": "b:done"}

    def test_a_failure_skips_only_its_dependents(self):
        report = run_dag(
            [spec("a", "permanent"), spec("b"), spec("dependent"), spec("sibling")],
            {"dependent": {"a"}, "sibling": {"b"}},
            InProcessExecutor(),
        )
        assert report.failed == ("a",)
        assert report.skipped == ("dependent",)
        assert set(report.completed) == {"b", "sibling"}

    def test_skipping_is_transitive(self):
        report = run_dag(
            [spec("a", "permanent"), spec("b"), spec("c")],
            {"b": {"a"}, "c": {"b"}},
            InProcessExecutor(),
        )
        assert report.skipped == ("b", "c")
        assert report.results["c"].skipped_because == "b"

    def test_a_skipped_node_is_never_executed(self):
        run_dag([spec("a", "permanent"), spec("b")], {"b": {"a"}}, InProcessExecutor())
        assert CALL_LOG == ["a"]

    def test_completed_work_is_retained_when_a_later_node_fails(self):
        """Rollback scope is nothing, deliberately: a node that wrote files
        cannot be un-run, and a rerun resumes from this set."""
        report = run_dag(
            [spec("a"), spec("b", "permanent")],
            {"b": {"a"}},
            InProcessExecutor(),
        )
        assert report.values() == {"a": "a:done"}
        assert not report.ok

    def test_a_transient_failure_is_retried_and_can_recover(self):
        report = run_dag([spec("a", "flaky")], {}, InProcessExecutor(), transient_retries=1)
        assert report.completed == ("a",)
        assert report.results["a"].attempts == 2
        assert report.results["a"].value == "a:recovered"

    def test_only_the_failed_node_is_retried_not_its_level(self):
        """Re-running the level would spend budget recomputing known values."""
        run_dag(
            [spec("a", "flaky"), spec("b")],
            {},
            InProcessExecutor(),
            transient_retries=1,
        )
        assert CALL_LOG == ["a", "b", "a"]

    def test_a_persistent_transient_failure_eventually_fails(self):
        report = run_dag([spec("a", "transient")], {}, InProcessExecutor(), transient_retries=2)
        assert report.failed == ("a",)
        assert report.results["a"].failure_class is FailureClass.TRANSIENT
        assert CALL_LOG == ["a", "a", "a"]

    def test_a_permanent_failure_is_not_retried(self):
        report = run_dag([spec("a", "permanent")], {}, InProcessExecutor(), transient_retries=3)
        assert report.results["a"].attempts == 1
        assert CALL_LOG == ["a"]

    def test_an_unexpected_exception_is_treated_as_permanent(self):
        """Retrying a fault nobody reasoned about is how a bounded loop becomes
        an unbounded one."""
        report = run_dag([spec("a", "explode")], {}, InProcessExecutor(), transient_retries=3)
        assert report.results["a"].failure_class is FailureClass.PERMANENT
        assert CALL_LOG == ["a"]

    def test_transient_retries_zero_means_no_retry(self):
        report = run_dag([spec("a", "flaky")], {}, InProcessExecutor(), transient_retries=0)
        assert report.failed == ("a",)

    def test_duplicate_labels_are_refused(self):
        with pytest.raises(ValueError, match="unique label"):
            run_dag([spec("a"), spec("a")], {}, InProcessExecutor())

    def test_a_cycle_is_fatal_by_default(self):
        with pytest.raises(DependencyCycleError):
            run_dag([spec("a"), spec("b")], {"a": {"b"}, "b": {"a"}}, InProcessExecutor())

    def test_the_cycle_policy_is_forwarded(self):
        report = run_dag(
            [spec("a"), spec("b")],
            {"a": {"b"}, "b": {"a"}},
            InProcessExecutor(),
            cycle_policy=CyclePolicy.COLLAPSE,
        )
        assert report.levels == [["a", "b"]]

    def test_a_budget_warning_is_recorded_on_the_report(self):
        report = run_dag(
            [spec("a", ctx_tokens=2000, max_completion_tokens=8000)],
            {},
            InProcessExecutor(),
            tpm_budget=6000,
        )
        assert len(report.warnings) == 1
        assert "6000 TPM budget" in report.warnings[0]

    def test_no_budget_means_no_cap_computation(self):
        report = run_dag([spec("a", ctx_tokens=2000, max_completion_tokens=8000)], {}, InProcessExecutor())
        assert report.warnings == []

    def test_events_report_the_level_cap_and_retries(self):
        seen: list[dict] = []
        run_dag(
            [spec("a", "flaky", ctx_tokens=100, max_completion_tokens=50)],
            {},
            InProcessExecutor(),
            tpm_budget=6000,
            transient_retries=1,
            on_event=seen.append,
        )
        kinds = [event["type"] for event in seen]
        assert "level_cap" in kinds
        assert "node_retry" in kinds

    def test_an_executor_that_returns_nothing_for_a_node_fails_that_node(self):
        """A silently missing result must not read as success."""

        class Forgetful:
            def run_level(self, specs):
                return {}

        report = run_dag([spec("a")], {}, Forgetful())
        assert report.failed == ("a",)
        assert "no result" in report.results["a"].error


class TestTheRealTopology:
    """The two halves of M5 composed: the authored 44-phase graph, executed."""

    def test_all_44_phases_run_in_a_valid_order(self):
        from kgf.topology import load_topology

        topo = load_topology()
        specs = [spec(phase_id) for phase_id in topo.phases]
        report = run_dag(specs, topo.edges(), InProcessExecutor())

        assert report.ok
        assert len(report.completed) == 44
        ran_at = {label: index for index, label in enumerate(CALL_LOG)}
        for phase_id, phase in topo.phases.items():
            for dependency in phase.depends_on:
                assert ran_at[dependency] < ran_at[phase_id], f"{dependency} ran after {phase_id}"

    def test_a_failed_gate_skips_its_downstream_and_keeps_the_rest(self):
        """phase:D failing must strand the security audits and everything after,
        while the pre-processing and reverse-engineering work already done stays
        in the report -- rollback scope is nothing."""
        from kgf.topology import load_topology

        topo = load_topology()
        specs = [
            spec(phase_id, "permanent" if phase_id == "phase:D" else "echo")
            for phase_id in topo.phases
        ]
        report = run_dag(specs, topo.edges(), InProcessExecutor())

        assert report.failed == ("phase:D",)
        assert set(report.skipped) >= {
            "phase:F.1",
            "phase:F.6",
            "phase:E",
            "phase:G",
            "phase:Ops.1",
            "phase:Ops.5",
        }
        assert "phase:B" in report.completed
        assert "phase:re-c.3" in report.completed
        assert "phase:H" in report.skipped

    def test_a_solo_run_executes_the_pruned_schedule(self):
        from kgf.topology import load_topology

        topo = load_topology()
        pruned = ("phase:A.6", "phase:A.6.1", "phase:H")
        specs = [spec(phase_id) for phase_id in topo.select(pruned)]
        report = run_dag(specs, topo.effective_edges(pruned), InProcessExecutor())

        assert report.ok
        assert len(report.completed) == 41
        ran_at = {label: index for index, label in enumerate(CALL_LOG)}
        assert ran_at["phase:A.5"] < ran_at["phase:B"]
        assert ran_at["phase:D"] < ran_at["phase:F.1"]


UPSTREAM_SEEN: dict[str, dict] = {}


def upstream_reading_node(spec: NodeSpec):
    """Record what this node could see of its dependencies, then succeed."""
    CALL_LOG.append(spec.label)
    UPSTREAM_SEEN[spec.label] = dict(spec.state.get("upstream", {}))
    return f"{spec.label}:done"


class TestUpstreamValues:
    """A node must be able to see what it depends on.

    Without this the DAG can order work but not connect it: NodeSpec.state is
    frozen at construction, so a consensus phase could not receive the
    blueprint an architecture phase produced.
    """

    @pytest.fixture(autouse=True)
    def _register(self):
        UPSTREAM_SEEN.clear()
        register_node_type("reader", upstream_reading_node)
        yield

    def test_a_dependent_sees_its_dependency_value(self):
        run_dag(
            [spec("a"), spec("b", "reader")],
            {"b": {"a"}},
            InProcessExecutor(),
        )
        assert UPSTREAM_SEEN["b"] == {"a": "a:done"}

    def test_a_node_with_no_dependencies_gets_no_upstream_key(self):
        run_dag([spec("a", "reader")], {}, InProcessExecutor())
        assert UPSTREAM_SEEN["a"] == {}

    def test_every_dependency_is_present_not_just_one(self):
        run_dag(
            [spec("a"), spec("b"), spec("c", "reader")],
            {"c": {"a", "b"}},
            InProcessExecutor(),
        )
        assert UPSTREAM_SEEN["c"] == {"a": "a:done", "b": "b:done"}

    def test_only_completed_dependencies_are_injected(self):
        """A skipped or failed dependency contributes nothing rather than a
        None that a node would have to distinguish from a real value."""
        run_dag(
            [spec("a"), spec("bad", "permanent"), spec("c", "reader")],
            {"c": {"a"}},
            InProcessExecutor(),
        )
        assert UPSTREAM_SEEN["c"] == {"a": "a:done"}

    def test_injection_does_not_mutate_the_caller_s_spec(self):
        original = spec("b", "reader")
        run_dag([spec("a"), original], {"b": {"a"}}, InProcessExecutor())
        assert "upstream" not in original.state

    def test_the_injected_state_survives_a_retry(self):
        run_dag(
            [spec("a"), spec("b", "flaky")],
            {"b": {"a"}},
            InProcessExecutor(),
            transient_retries=1,
        )
        assert CALL_LOG == ["a", "b", "b"]
