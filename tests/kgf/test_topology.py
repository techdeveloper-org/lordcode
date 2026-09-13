"""Tests for kgf's authored phase topology.

The topology is kgf's own data, not the library's, so almost nothing about it
can be checked against an external source. The three things that CAN be are
checked hard: every authored id still exists in phases.json, every one of
traversal.md#6.3's seven MUST constraints holds transitively, and the seeded
Enterprise order is honoured link by link. Everything else asserts an
invariant of the graph itself -- acyclicity, splice-correct pruning, and the
two loops the library explicitly says must not become edges.
"""

from __future__ import annotations

import pytest

from kgf import topology as T
from kgf.dag import DependencyCycleError
from kgf.errors import ProblemLog, Severity
from kgf.source import locate_library

SOLO_PRUNED = ("phase:A.6", "phase:A.6.1", "phase:H")
"""What D13::B2 and D21::B2/B3 prune, per traversal.md#6.5."""


@pytest.fixture(scope="module")
def topo() -> T.Topology:
    return T.load_topology()


@pytest.fixture(scope="module")
def library():
    return locate_library(None)


class TestAgreementWithTheLibrary:
    """The only external checks available on a self-authored graph."""

    def test_every_authored_phase_exists_in_the_library(self, topo, library):
        """An authored id the library dropped means kgf schedules a phase that
        no longer exists -- the drift ADR-5 accepted responsibility for."""
        declared = set(T.library_phase_ids(library))
        assert set(topo.phases) - declared == set()

    def test_every_library_phase_is_authored(self, topo, library):
        """The other direction matters too: a new library phase that kgf never
        authored would be silently skipped rather than scheduled."""
        declared = set(T.library_phase_ids(library))
        assert declared - set(topo.phases) == set()

    def test_the_phase_count_is_44(self, topo, library):
        assert len(topo.phases) == 44
        assert len(set(T.library_phase_ids(library))) == 44

    def test_phase_F_still_does_not_exist(self, topo, library):
        """The trap the alias table exists for. If the library ever adds a bare
        phase:F this test fails and the alias must be reconsidered."""
        declared = set(T.library_phase_ids(library))
        assert "phase:F" not in declared
        assert all(f"phase:F.{n}" in declared for n in range(1, 7))

    def test_all_seven_library_precedence_constraints_hold(self, topo):
        """traversal.md#6.3 states these as MUST. They are the only dependency
        facts the library provides, so an authoring slip here is invisible
        without this assertion."""
        assert T.unsatisfied_library_precedence(topo) == ()

    def test_the_seeded_enterprise_order_is_honoured_link_by_link(self, topo):
        """13 phase references expand to 22 real links through the alias table;
        taken literally the chain would fail on phase:F alone."""
        links = T.seed_chain_links(topo)
        assert len(links) == 22
        assert T.unsatisfied_seed_chain(topo) == ()

    def test_check_against_library_is_clean_and_records_nothing(self, topo, library):
        log = ProblemLog()
        report = T.check_against_library(topo, library, log)
        assert report.ok
        assert report.authored_count == report.library_count == 44
        assert log.problems == []


class TestGraphInvariants:
    def test_the_full_topology_is_acyclic(self, topo):
        """levels() uses CyclePolicy.FATAL, so this raising is the test."""
        assert len(topo.levels()) == 30

    def test_no_dependency_names_an_unauthored_phase(self, topo):
        """kgf.dag ignores an edge leaving the node set, which is right for
        pruning and would silently swallow a typo here."""
        assert topo.unknown_dependencies() == {}

    def test_there_is_exactly_one_entry_point(self, topo):
        assert topo.entry_points() == ("phase:execution-plan",)

    def test_every_dependency_sits_in_a_strictly_earlier_level(self, topo):
        level_of = {p: i for i, level in enumerate(topo.levels()) for p in level}
        for phase_id, phase in topo.phases.items():
            for dependency in phase.depends_on:
                assert level_of[dependency] < level_of[phase_id], f"{dependency} !< {phase_id}"

    def test_levels_are_a_partition_of_all_44(self, topo):
        flattened = [p for level in topo.levels() for p in level]
        assert sorted(flattened) == sorted(topo.phases)

    def test_levels_are_stable_across_calls(self, topo):
        assert topo.levels() == topo.levels()

    def test_every_phase_carries_a_provenance_and_a_rationale(self, topo):
        """ADR-5 requires both on every node, because two thirds of this graph
        is kgf's judgement and an unexplained edge cannot be reviewed."""
        for phase_id, phase in topo.phases.items():
            assert phase.provenance, phase_id
            assert phase.rationale.strip(), phase_id

    def test_provenance_is_one_of_the_three_declared_kinds(self, topo):
        allowed = {T.PROVENANCE_TRAVERSAL, T.PROVENANCE_TITLE, T.PROVENANCE_AUTHORED}
        assert {phase.provenance for phase in topo.phases.values()} <= allowed

    def test_the_library_sourced_share_is_what_the_docstring_claims(self, topo):
        """The module docstring states 13/3/28. A number in prose that nothing
        checks is how the plan's earlier counts went stale."""
        counts: dict[str, int] = {}
        for phase in topo.phases.values():
            counts[phase.provenance] = counts.get(phase.provenance, 0) + 1
        assert counts[T.PROVENANCE_TRAVERSAL] == 13
        assert counts[T.PROVENANCE_TITLE] == 3
        assert counts[T.PROVENANCE_AUTHORED] == 28

    def test_a_cycle_in_an_authored_table_is_fatal_not_collapsed(self):
        """The whole reason dag.levels took a policy argument."""
        cyclic = T.Topology(
            phases={
                "a": T.Phase(id="a", group="g", depends_on=frozenset({"b"})),
                "b": T.Phase(id="b", group="g", depends_on=frozenset({"a"})),
            }
        )
        with pytest.raises(DependencyCycleError):
            cyclic.levels()


class TestTheTwoLoopsThatMustNotBeEdges:
    """Both are library statements, and both would cycle the graph."""

    def test_self_correction_does_not_depend_on_the_gates_it_recovers(self, topo):
        """traversal.md:312 -- the loop is a RUNTIME loop in the adapter, not a
        graph edge. If SC.1 depended on its gates it could not run until all of
        them had passed, which is the opposite of what it is for."""
        sc1 = topo.get("phase:SC.1")
        assert sc1.triggered_by
        assert not (sc1.depends_on & set(sc1.triggered_by))
        for gate in sc1.triggered_by:
            assert not topo.precedes(gate, "phase:SC.1")

    def test_the_gate_rerun_is_recorded_but_is_not_a_dependency(self, topo):
        sc2 = topo.get("phase:SC.2")
        assert sc2.reruns_on_success
        assert sc2.depends_on == frozenset({"phase:SC.1"})

    def test_ops5_does_not_feed_phase_6(self, topo):
        """Its title says it closes the loop back into Sprint Planning. As an
        edge that is a cycle through the entire pipeline, so the feedback is
        the NEXT cycle's input and not a dependency."""
        assert "phase:6" not in topo.get("phase:Ops.5").depends_on
        assert not topo.precedes("phase:Ops.5", "phase:6")
        assert topo.precedes("phase:6", "phase:Ops.5")


class TestPruning:
    def test_a_solo_run_drops_exactly_the_three_harness_phases(self, topo):
        selected = topo.select(SOLO_PRUNED)
        assert len(selected) == 41
        assert not set(selected) & set(SOLO_PRUNED)

    def test_pruning_splices_rather_than_dropping(self, topo):
        """The defect this fixture exists for: with A.6/A.6.1/H merely removed,
        phase:B lost its only main-pipeline dependency and phase:F.1 floated to
        level 0, putting the security audit before implementation."""
        edges = topo.effective_edges(SOLO_PRUNED)
        assert "phase:A.5" in edges["phase:IV.1"]
        assert "phase:A.5" in edges["phase:B"]
        assert edges["phase:F.1"] == frozenset({"phase:D"})

    def test_the_pruned_schedule_preserves_every_ordering(self, topo):
        levels = topo.levels(SOLO_PRUNED)
        level_of = {p: i for i, level in enumerate(levels) for p in level}
        for before, after in (
            ("phase:A.5", "phase:B"),
            ("phase:B", "phase:C"),
            ("phase:C", "phase:D"),
            ("phase:D", "phase:F.1"),
            ("phase:F.6", "phase:E"),
            ("phase:E", "phase:G"),
            ("phase:G", "phase:Ops.1"),
        ):
            assert level_of[before] < level_of[after], f"{before} !< {after}"

    def test_pruning_shortens_the_schedule(self, topo):
        assert len(topo.levels(SOLO_PRUNED)) == 27
        assert len(topo.levels()) == 30

    def test_pruning_an_entry_point_leaves_its_dependents_schedulable(self, topo):
        levels = topo.levels(("phase:execution-plan",))
        assert "phase:0" in levels[0]
        assert "phase:execution-plan" not in {p for level in levels for p in level}

    def test_pruning_a_whole_chain_still_splices_to_a_survivor(self, topo):
        """Two adjacent pruned nodes must not leave a dependent orphaned."""
        edges = topo.effective_edges(("phase:A.6", "phase:A.6.1"))
        assert edges["phase:IV.1"] == frozenset({"phase:A.5"})


class TestGatesAndArtefacts:
    def test_the_gates_the_library_names_are_marked_as_gates(self, topo):
        """Each of these is a gate by the library's own words, not by kgf's
        reading: a BLOCKING or BINARY gate in its own title, or a member of
        D22's wraps_gates list in traversal.md."""
        for phase_id in (
            "phase:7",
            "phase:8",
            "phase:A.6",
            "phase:C",
            "phase:D",
            "phase:H",
            "phase:E",
            "phase:F.6",
            "phase:IV.2",
            "phase:Ops.1",
        ):
            assert topo.get(phase_id).is_gate, phase_id

    def test_blocking_implies_gate(self, topo):
        for phase in topo.phases.values():
            if phase.blocking:
                assert phase.is_gate, phase.id

    def test_every_non_entry_phase_consumes_something(self, topo):
        """A phase with a dependency but no declared input means the artefact
        contract was not thought through for that node."""
        for phase_id, phase in topo.phases.items():
            if phase.depends_on and phase_id != "phase:SC.1":
                assert phase.consumes, phase_id

    def test_every_phase_produces_something(self, topo):
        for phase_id, phase in topo.phases.items():
            assert phase.produces, phase_id

    def test_consumed_artefacts_are_produced_by_some_earlier_phase(self, topo):
        """Not per-edge -- an artefact may come from a pruned or parallel
        branch -- but nothing may consume an artefact no phase ever produces."""
        produced = {artefact for phase in topo.phases.values() for artefact in phase.produces}
        for phase_id, phase in topo.phases.items():
            for artefact in phase.consumes:
                assert artefact in produced, f"{phase_id} consumes unproduced {artefact}"


class TestDescribe:
    def test_describe_lists_every_phase_once(self, topo):
        text = T.describe(topo)
        for phase_id in topo.phases:
            assert text.count(phase_id + " ") + text.count(phase_id + "\n") >= 1

    def test_describe_marks_blocking_gates(self, topo):
        assert "BLOCKING gate" in T.describe(topo)


class TestReportAndDefects:
    def test_a_phase_the_library_dropped_is_reported_as_a_defect(self, topo, library, monkeypatch):
        """Simulated rather than waited for: the whole point of the check is
        that it fires on a future library bump."""
        real = T.library_phase_ids(library)
        monkeypatch.setattr(T, "library_phase_ids", lambda src: tuple(i for i in real if i != "phase:G"))
        log = ProblemLog()
        report = T.check_against_library(topo, library, log)
        assert report.missing_from_library == ("phase:G",)
        assert not report.ok
        assert [p.code for p in log.of(Severity.DEFECT)] == ["TOPOLOGY_PHASE_GONE"]

    def test_a_new_library_phase_is_reported_as_unauthored(self, topo, library, monkeypatch):
        real = T.library_phase_ids(library)
        monkeypatch.setattr(T, "library_phase_ids", lambda src: real + ("phase:Z.9",))
        log = ProblemLog()
        report = T.check_against_library(topo, library, log)
        assert report.missing_from_topology == ("phase:Z.9",)
        assert [p.code for p in log.of(Severity.DEFECT)] == ["TOPOLOGY_PHASE_UNAUTHORED"]

    def test_an_unknown_dependency_is_fatal(self, library):
        broken = T.Topology(
            phases={"a": T.Phase(id="a", group="g", depends_on=frozenset({"nope"}))}
        )
        log = ProblemLog()
        T.check_against_library(broken, library, log)
        assert [p.code for p in log.fatals] == ["TOPOLOGY_UNKNOWN_DEPENDENCY"]
