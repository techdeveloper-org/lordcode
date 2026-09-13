"""Tests for expanding an agent into its graph-asserted working set."""

from __future__ import annotations

from kgf import ids
from kgf.closure import MAX_CLOSURE_SKILLS, MAX_REQUIREMENT_DEPTH, build_closure


def test_unknown_agent_returns_none(graph):
    assert build_closure(graph, "no-such-agent-anywhere") is None


def test_closure_is_larger_than_the_one_skill_injected_today(graph):
    """The defect being fixed: one skill per run against a median of 4 mandatory."""
    result = build_closure(graph, "spring-boot-microservices")
    assert result is not None
    assert len(result.mandatory_skills) > 1


def test_transitive_requirements_are_followed_where_they_add_anything(graph):
    """Measured: 251 of 528 agents gain skills from SKILL_REQUIRES_SKILL.

    The other 277 do not, and that is not a bug -- spring-boot-microservices is
    one of them because every requirement of its mandatory skills is ALREADY
    mandatory for it. The library curated those sets closed. So the assertion is
    that the traversal finds requirements where they exist, not that every
    closure grows.
    """
    grew = [
        agent_id
        for agent_id in graph.agents
        if build_closure(graph, agent_id).required_skills
    ]
    assert grew, "no closure gained a transitive requirement, so the traversal is not working"

    sample = build_closure(graph, grew[0])
    assert sample.size > len(sample.mandatory_skills)
    assert set(sample.required_skills).isdisjoint(sample.mandatory_skills)


def test_a_closure_already_closed_under_requirements_reports_none(graph):
    """The inverse case, asserted so it reads as intended rather than as a gap."""
    result = build_closure(graph, "spring-boot-microservices")
    for skill_id in result.mandatory_skills:
        for required in graph.neighbours(skill_id, "SKILL_REQUIRES_SKILL"):
            assert required in result.mandatory_skills, (
                "this agent is expected to be closed under its own requirements"
            )
    assert result.required_skills == ()


def test_every_closure_member_resolves_to_a_real_node(graph):
    for agent_id in list(graph.agents)[:60]:
        result = build_closure(graph, agent_id)
        assert result is not None
        for skill_id in result.all_skills:
            assert skill_id in graph.skills
        for other in result.math_agents + result.coordinating_agents:
            assert other in graph.agents
        for regulation in result.regulations:
            assert regulation in graph.regulations or regulation.startswith("reg:")


def test_ordering_puts_mandatory_before_optional(graph):
    """A caller trimming to a token budget drops from the end, so order matters."""
    result = build_closure(graph, "spring-boot-microservices")
    ordered = result.all_skills
    if result.mandatory_skills and result.optional_skills:
        last_mandatory = max(ordered.index(s) for s in result.mandatory_skills if s in ordered)
        first_optional = min(
            (ordered.index(s) for s in result.optional_skills if s in ordered), default=len(ordered)
        )
        assert last_mandatory < first_optional


def test_all_skills_has_no_duplicates(graph):
    for agent_id in list(graph.agents)[:40]:
        result = build_closure(graph, agent_id)
        assert len(result.all_skills) == len(set(result.all_skills))


def test_traversal_terminates_on_the_real_requirement_graph(graph):
    """SKILL_REQUIRES_SKILL is not a DAG here.

    A recursive walk without a visited set would not terminate, which is why the
    closure is breadth-first. Running it over every agent is the proof.
    """
    for agent_id in graph.agents:
        result = build_closure(graph, agent_id)
        assert result is not None


def test_depth_cap_is_respected(graph):
    for agent_id in list(graph.agents)[:60]:
        result = build_closure(graph, agent_id)
        assert result.depth_reached <= MAX_REQUIREMENT_DEPTH


def test_a_tighter_depth_yields_no_more_skills(graph):
    deep = build_closure(graph, "spring-boot-microservices", max_depth=3)
    shallow = build_closure(graph, "spring-boot-microservices", max_depth=1)
    assert shallow.size <= deep.size


def test_skill_budget_is_enforced_and_what_was_cut_is_recorded(graph):
    """A truncation that is not recorded is indistinguishable from a bug."""
    result = build_closure(graph, "spring-boot-microservices", max_skills=6)
    assert result is not None
    assert len(result.mandatory_skills) + len(result.required_skills) <= max(
        6, len(result.mandatory_skills)
    )
    if result.truncated:
        assert all(skill_id in graph.skills for skill_id in result.truncated)


def test_no_closure_exceeds_the_default_ceiling(graph):
    for agent_id in list(graph.agents)[:80]:
        result = build_closure(graph, agent_id)
        assert len(result.mandatory_skills) + len(result.required_skills) <= max(
            MAX_CLOSURE_SKILLS, len(result.mandatory_skills)
        )


def test_math_delegation_comes_from_edges(graph):
    """452 DELEGATES_MATH_TO edges resolve; the record's own field does not."""
    delegating = [
        agent_id
        for agent_id in graph.agents
        if graph.neighbours(agent_id, "DELEGATES_MATH_TO")
    ]
    assert delegating, "the library does declare math delegation"
    result = build_closure(graph, delegating[0])
    assert result.math_agents
    assert all(agent_id in graph.agents for agent_id in result.math_agents)


def test_closure_records_the_domain_from_the_membership_edge(graph):
    result = build_closure(graph, "spring-boot-microservices")
    assert result.domain in graph.domains


def test_names_are_slugs_for_display(graph):
    result = build_closure(graph, "spring-boot-microservices")
    assert all(":" not in name for name in result.names())
    assert ids.slug_of(result.mandatory_skills[0]) in result.names()
