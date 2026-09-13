"""Tests for node accessors and typed adjacency.

The accessor tests matter more than they look: only 11 of 90 agent fields and
7 of 116 skill fields are present on every record, so absence is the normal
case. A record class that raised KeyError would fail two layers into a
traversal on data the loader has already reported as fine.
"""

from __future__ import annotations

from kgf.graph import Agent, Skill


def test_text_returns_empty_string_for_absent_fields():
    record = Agent(id="agent:x", raw={})
    assert record.description == ""
    assert record.model == ""
    assert record.name == "x"


def test_strings_handles_both_list_and_comma_string_shapes():
    """74 of 569 allowed_tools values are comma-strings, not YAML lists."""
    as_list = Skill(id="skill:a", raw={"allowed_tools": ["Read", "Glob"]})
    as_string = Skill(id="skill:b", raw={"allowed_tools": "Read,Glob,Grep"})
    assert as_list.allowed_tools == ("Read", "Glob")
    assert as_string.allowed_tools == ("Read", "Glob", "Grep")


def test_strings_returns_empty_tuple_when_absent():
    assert Skill(id="skill:a", raw={}).allowed_tools == ()
    assert Agent(id="agent:a", raw={}).declared_tools == ()


def test_strings_drops_blank_entries():
    record = Skill(id="skill:a", raw={"allowed_tools": "Read, ,Glob,"})
    assert record.allowed_tools == ("Read", "Glob")


def test_flag_is_false_when_absent():
    assert Agent(id="agent:a", raw={}).is_math_master is False
    assert Agent(id="agent:a", raw={"is_math_master": True}).is_math_master is True


def test_real_records_never_raise_on_any_accessor(graph):
    """Exercised across all 1562 records, since raggedness is the point."""
    for agent in graph.agents.values():
        assert isinstance(agent.name, str)
        assert isinstance(agent.description, str)
        assert isinstance(agent.model, str)
        assert isinstance(agent.declared_tools, tuple)
        assert isinstance(agent.is_math_master, bool)
        assert isinstance(agent.declared_domain, str)
    for skill in graph.skills.values():
        assert isinstance(skill.name, str)
        assert isinstance(skill.allowed_tools, tuple)
        assert isinstance(skill.m_sections, tuple)
        assert isinstance(skill.declared_domain, str)


def test_lookup_accepts_any_reference_form(graph):
    agent = graph.agent("spring-boot-microservices")
    assert agent is not None
    assert agent is graph.agent("agent:spring_boot_microservices")
    assert agent is graph.agent("spring_boot_microservices")


def test_adjacency_is_type_scoped(graph):
    agent = graph.agent("spring-boot-microservices")
    assert agent is not None

    used = graph.neighbours(agent.id, "AGENT_USES_SKILL")
    assert used, "a backend agent must use at least one skill"
    assert all(target.startswith("skill:") for target in used)

    coordinates = graph.neighbours(agent.id, "COORDINATES_WITH")
    assert set(used).isdisjoint(coordinates), "types must not bleed into each other"


def test_in_and_out_edges_are_distinct_directions(graph):
    skill = graph.skill("java-spring-boot-microservices")
    assert skill is not None

    consumers = graph.in_edges(skill.id, "AGENT_USES_SKILL")
    assert consumers, "a core skill must be used by at least one agent"
    assert all(edge.target == skill.id for edge in consumers)
    assert graph.out_edges(skill.id, "AGENT_USES_SKILL") == []


def test_edge_weight_and_rationale_tolerate_absence(graph):
    for edge in graph.edges[:200]:
        assert isinstance(edge.weight, float)
        assert isinstance(edge.rationale, str)


def test_node_and_edge_counts_agree_with_the_registries(graph):
    assert graph.node_count == (
        len(graph.agents)
        + len(graph.skills)
        + len(graph.domains)
        + len(graph.regulations)
        + len(graph.tool_tiers)
    )
    assert graph.edge_count == len(graph.edges)
    assert sum(graph.edge_type_counts().values()) == graph.edge_count


def test_domain_membership_is_read_from_edges_not_from_the_record(graph):
    """A record's own `domain` field is a display name on 175 of 1034 skills.

    "India CA Suite", "Digital Advertising", "EdTech" -- so an id built from
    that field names no node. The membership edge is the authority, exactly as
    it is for math delegation.
    """
    from kgf import ids

    diverged = [
        skill
        for skill in graph.skills.values()
        if skill.declared_domain and ids.domain_id(skill.declared_domain) not in graph.domains
    ]
    assert diverged, (
        "expected some records to store a display name; if the library has "
        "normalised them, revisit graph.domain_of's docstring"
    )

    for skill in diverged:
        resolved = graph.domain_of(skill.id)
        assert resolved in graph.domains, f"{skill.id} has no resolvable domain edge"


def test_every_skill_and_agent_has_a_resolvable_domain(graph):
    """1702 skill edges and 885 agent edges, covering every node."""
    for skill_id in graph.skills:
        assert graph.domain_of(skill_id) in graph.domains, skill_id
    for agent_id in graph.agents:
        assert graph.domain_of(agent_id) in graph.domains, agent_id


def test_domains_of_returns_every_membership_without_duplicates(graph):
    for node_id in list(graph.skills)[:100]:
        memberships = graph.domains_of(node_id)
        assert len(memberships) == len(set(memberships))
        assert all(member in graph.domains for member in memberships)


def test_domain_of_returns_empty_string_for_an_unknown_node(graph):
    assert graph.domain_of("skill:does_not_exist_anywhere") == ""
