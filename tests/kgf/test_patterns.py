"""Tests for decision-tree pattern resolution and phase pruning."""

from __future__ import annotations

import pytest

from kgf import ids
from kgf.patterns import (
    COMPLEXITY_ENTERPRISE,
    COMPLEXITY_SOLO,
    COMPLEXITY_SQUAD,
    load_decision_tree,
)


@pytest.fixture(scope="module")
def tree(library):
    return load_decision_tree(library)


def test_patterns_and_phases_load(tree):
    assert len(tree.patterns) > 100
    assert len(tree.phases) > 40


def test_pattern_records_have_only_the_fields_the_data_carries(tree):
    """patterns.json has exactly 5 keys: no steps, no ordering, no phase list.

    A richer object here would imply a workflow DAG that this data does not
    contain, which is precisely the overreach the plan scoped out.
    """
    pattern = next(iter(tree.patterns.values()))
    assert {"id", "title", "lead_agent", "lead_domain", "lead_math"} == set(vars(pattern))


def test_every_d14_branch_parses_into_a_domain_pattern_pair(tree, graph):
    """All 101 branches, not most of them.

    D14's conditions are not prose to be interpreted: each carries a structured
    `domain:X` token and each branch names its pattern in `emits`. Reading the
    prose instead is how a keyword matcher sent a Spring Boot task to
    assembly-boot.
    """
    assert len(tree.domain_to_pattern) >= 100
    for domain_id, pattern_id in tree.domain_to_pattern.items():
        assert domain_id in graph.domains, domain_id
        assert pattern_id in tree.patterns, pattern_id


def test_pattern_lead_references_resolve(tree, graph):
    for pattern in tree.patterns.values():
        if pattern.lead_agent:
            assert pattern.lead_agent in graph.agents, pattern.id
        if pattern.lead_domain:
            assert pattern.lead_domain in graph.domains, pattern.id
        if pattern.lead_math:
            assert pattern.lead_math in graph.agents, pattern.id


def test_routing_resolves_a_known_domain(tree):
    route = tree.route("backend-engineering")
    assert route.resolved
    assert route.pattern.lead_agent
    assert route.trace


def test_routing_accepts_any_domain_reference_form(tree):
    for reference in ("backend-engineering", "backend_engineering", "domain:backend-engineering"):
        assert tree.route(reference).resolved


def test_an_unmapped_domain_is_unresolved_rather_than_guessed(tree, graph):
    """4 of 104 domains have no D14 branch; they must report that, not improvise."""
    unmapped = [
        domain_id for domain_id in graph.domains if domain_id not in tree.domain_to_pattern
    ]
    if not unmapped:
        pytest.skip("every domain now has a D14 branch")
    route = tree.route(unmapped[0])
    assert not route.resolved
    assert any("no branch" in line for line in route.trace)


def test_solo_complexity_prunes_phases(tree):
    """D13::B2 is the reason the complexity signal is fed in rather than skipped.

    Entering the tree at D14 skips D13, and D13 is where pruning lives -- so
    without this the phase set is silently over-broad.
    """
    solo = tree.route("backend-engineering", COMPLEXITY_SOLO)
    squad = tree.route("backend-engineering", COMPLEXITY_SQUAD)

    assert len(solo.pruned) == 8
    assert len(solo.phases) < len(squad.phases)
    assert set(solo.pruned).isdisjoint({phase.id for phase in solo.phases})


def test_squad_and_enterprise_prune_nothing(tree):
    for complexity in (COMPLEXITY_SQUAD, COMPLEXITY_ENTERPRISE):
        route = tree.route("backend-engineering", complexity)
        assert route.pruned == ()


def test_an_absent_complexity_signal_prunes_nothing_rather_than_guessing(tree):
    route = tree.route("backend-engineering")
    assert route.pruned == ()
    assert any("no complexity signal" in line for line in route.trace)


def test_an_unrecognised_complexity_is_reported_not_silently_ignored(tree):
    route = tree.route("backend-engineering", "gigantic")
    assert route.pruned == ()
    assert any("not recognised" in line for line in route.trace)


def test_pruned_phase_ids_are_real_phases(tree):
    solo = tree.route("backend-engineering", COMPLEXITY_SOLO)
    known = {phase.id for phase in tree.phases}
    for phase_id in solo.pruned:
        assert phase_id in known, phase_id


def test_trace_explains_every_decision(tree):
    route = tree.route("cybersecurity", COMPLEXITY_SOLO)
    joined = " ".join(route.trace)
    assert "D14" in joined
    assert "D13" in joined


def test_a_library_without_a_decision_tree_degrades_rather_than_raising(tmp_path):
    """The tree enriches selection; its absence must not break selection."""
    from kgf.source import LibrarySource

    empty = LibrarySource(root=tmp_path, library_version="0.0.0")
    tree = load_decision_tree(empty)
    assert tree.patterns == {}
    assert tree.phases == ()
    assert not tree.route("backend-engineering").resolved
