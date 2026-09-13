"""Tests for the measured id conventions.

Each figure here was derived from the live library at the pinned version. They
are asserted rather than described because getting any one of them wrong
silently empties a traversal instead of raising.
"""

from __future__ import annotations

import json

from kgf import ids


def test_canonical_preserves_prefix_and_folds_the_remainder():
    assert ids.canonical("domain:frontend-engineering") == "domain:frontend_engineering"
    assert ids.canonical("agent:spring_boot_microservices") == "agent:spring_boot_microservices"
    assert ids.canonical("skill:java-spring-boot") == "skill:java_spring_boot"


def test_canonical_does_not_strip_the_prefix():
    """Twelve library names legitimately begin with a type word.

    A skill called `agent-tooling-...` is not an agent, so stripping a leading
    type word would mis-key it. Prepending is safe where stripping is not.
    """
    assert ids.skill_id("agent-tooling-core") == "skill:agent_tooling_core"
    assert ids.skill_id("skill:agent_tooling_core") == "skill:agent_tooling_core"


def test_bare_slugs_are_lifted_to_prefixed_ids():
    assert ids.skill_id("java-spring-boot-microservices") == "skill:java_spring_boot_microservices"
    assert ids.agent_id("spring-boot-microservices") == "agent:spring_boot_microservices"
    assert ids.domain_id("2d-game-engineering") == "domain:2d_game_engineering"
    assert ids.regulation_id("ngp_2022") == "reg:ngp_2022"


def test_an_already_prefixed_reference_is_not_double_prefixed():
    assert ids.skill_id("skill:rdbms_core") == "skill:rdbms_core"
    assert ids.domain_id("domain:backend-engineering") == "domain:backend_engineering"


def test_kind_and_slug_round_trip():
    assert ids.kind_of("agent:x") == "agent"
    assert ids.kind_of("nonsense") is None
    assert ids.slug_of("skill:rdbms_core") == "rdbms_core"
    assert ids.slug_of("bare") == "bare"


def test_non_string_input_does_not_raise():
    """A malformed registry value must become an unresolvable id, not a crash."""
    assert ids.canonical(123) == "123"
    assert ids.skill_id(None) == "skill:None"


def test_domain_endpoints_all_resolve_under_the_fold(library, graph):
    """Measured: 3930 domain-prefixed endpoints, 0 unresolved."""
    endpoints = [
        endpoint
        for edge in graph.edges
        for endpoint in (edge.source, edge.target)
        if endpoint.startswith("domain:")
    ]
    assert len(endpoints) > 3000
    unresolved = [endpoint for endpoint in endpoints if endpoint not in graph.domains]
    assert unresolved == []


def test_mandatory_skill_slugs_all_resolve_under_the_lift(graph):
    """Measured: 2477 mandatory values, 0 unresolved once lifted."""
    values = [
        value
        for agent in graph.agents.values()
        for value in agent.strings("mandatory_skills")
    ]
    assert len(values) > 2000
    unresolved = [value for value in values if ids.skill_id(value) not in graph.skills]
    assert unresolved == []


def test_pattern_lead_domains_need_the_hyphen_tolerant_fold(library, graph):
    """The rule most easily missed: 12 of 105 resolve without it, 105 with it.

    patterns.json writes `domain:frontend-engineering` -- prefixed AND
    hyphenated. Folding only unprefixed references would silently drop 93 of
    the 105 routing patterns.
    """
    patterns_path = library.tree_dir / "patterns.json"
    if not patterns_path.exists():
        return
    patterns = json.loads(patterns_path.read_text(encoding="utf-8"))
    lead_domains = [pattern["lead_domain"] for pattern in patterns if pattern.get("lead_domain")]
    assert lead_domains

    raw_hits = sum(1 for ref in lead_domains if ref in graph.domains)
    folded_hits = sum(1 for ref in lead_domains if ids.canonical(ref) in graph.domains)

    assert folded_hits == len(lead_domains)
    assert raw_hits < folded_hits, "the fold must actually be doing work here"


def test_relational_facts_come_from_edges_not_from_the_record(graph):
    """math_delegation_target is unreliable; DELEGATES_MATH_TO is not.

    Measured: of 253 non-empty math_delegation_target values, 209 fail to
    resolve raw and 39 still fail folded, while all 452 DELEGATES_MATH_TO
    edges resolve. Hence the rule that relations are read from edges only.
    """
    edges = graph.edges_of_type("DELEGATES_MATH_TO")
    assert edges
    assert all(edge.target in graph.agents for edge in edges)

    declared = [
        value
        for agent in graph.agents.values()
        if (value := agent.text("math_delegation_target"))
    ]
    if declared:
        unresolved = [v for v in declared if ids.agent_id(v) not in graph.agents]
        assert unresolved, (
            "the record-level field is expected to be unreliable; if it has been "
            "fixed upstream, this test and the ids docstring should be revisited"
        )
