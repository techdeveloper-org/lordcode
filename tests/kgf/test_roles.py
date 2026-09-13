"""Tests for role classification, with the two frozen fixtures.

Both fixtures are required. A positive fixture alone passes while mislabelling
distributed-consensus-engineer, which builds consensus protocols rather than
reviewing anything -- and mislabelling a builder as a reviewer is the same class
of defect as issue #2 item 3, just pointing the other way.
"""

from __future__ import annotations

from kgf import ids
from kgf.roles import (
    NEGATIVE_OVERRIDES,
    POSITIVE_OVERRIDES,
    REVIEWER_TOKENS,
    ROLE_PRIMARY_CODER,
    ROLE_REASONER,
    classify,
    classify_all,
    reviewers,
)

REVIEWER_FIXTURE = (
    "api-security-auditor",
    "architecture-conformance-auditor",
    "consensus-agent",
    "infrastructure-security-auditor",
    "interpretability-evaluation-auditor",
    "marketing-auditor",
    "production-readiness-reviewer",
    "reliability-auditor",
    "security-compliance-auditor",
    "security-lead-auditor",
    "video-code-reviewer",
)
"""FROZEN positive fixture: these must classify as reasoner.

Enumerated from the library at library_version 29.97.4 by matching the narrow
reviewer vocabulary. Every one reviews, audits or adjudicates other agents' work.
"""

BUILDER_FIXTURE = (
    "distributed-consensus-engineer",
    "2d-game-engine-architect",
    "3d-game-engine-architect",
    "cpu-architecture-specialist",
    "credit-risk-analyst",
    "data-analyst",
    "five-g-core-architect",
    "solution-architect",
    "foundation-model-architect",
    "quantitative-analyst",
    "reverse-engineering-analyst",
    "spring-boot-microservices",
    "react-engineer",
    "python-backend-engineer",
)
"""FROZEN negative fixture: these must classify as primary_coder.

Chosen adversarially. The first eleven all carry a word a broader rule would
read as reviewing -- consensus, architect, analyst, specialist -- and all of them
build things. A broad vocabulary matches 82 of 528 agents and sweeps every one of
these in, which is exactly why the vocabulary is three tokens wide and
distributed-consensus-engineer needs an explicit override on top.
"""


def test_reviewer_vocabulary_stays_narrow():
    """Widening this list is how builders start being classified as reviewers."""
    assert set(REVIEWER_TOKENS) == {"auditor", "reviewer", "consensus"}
    for excluded in ("architect", "analyst", "advisor", "specialist", "validator"):
        assert excluded not in REVIEWER_TOKENS


def test_every_fixture_reviewer_classifies_as_reasoner():
    for name in REVIEWER_FIXTURE:
        assignment = classify(name)
        assert assignment.role == ROLE_REASONER, f"{name}: {assignment.reason}"


def test_every_fixture_builder_classifies_as_primary_coder():
    for name in BUILDER_FIXTURE:
        assignment = classify(name)
        assert assignment.role == ROLE_PRIMARY_CODER, f"{name}: {assignment.reason}"


def test_the_two_fixtures_do_not_overlap():
    assert not set(REVIEWER_FIXTURE) & set(BUILDER_FIXTURE)


def test_the_named_false_positive_is_overridden_not_matched_by_luck():
    """distributed-consensus-engineer DOES match the name rule and must lose.

    If the override were removed this would classify as a reviewer, so the test
    checks the reason as well as the role -- a pass for the wrong reason would
    hide the override's removal.
    """
    assignment = classify("distributed-consensus-engineer")
    assert assignment.role == ROLE_PRIMARY_CODER
    assert "override" in assignment.reason
    assert "distributed-consensus-engineer" in NEGATIVE_OVERRIDES


def test_every_override_carries_a_reason():
    for name, reason in {**NEGATIVE_OVERRIDES, **POSITIVE_OVERRIDES}.items():
        assert reason.strip(), f"{name} has an empty justification"


def test_model_field_is_not_used_as_a_role_signal(graph):
    """The trap this module exists to avoid.

    model is 450 sonnet / 78 opus / 0 fable, and 77 of the 78 opus agents are
    math masters -- so it marks math mastery, not seniority. Every reviewer
    persona is sonnet, so any mapping from model to role would put reviewers
    back on the coder role, recreating the defect issue #2 fixed.
    """
    reviewer_models = {
        graph.agent(name).model
        for name in REVIEWER_FIXTURE
        if graph.agent(name) is not None
    }
    assert reviewer_models <= {"sonnet"}, (
        "reviewers are all sonnet, so model cannot distinguish them from coders"
    )


def test_classification_accepts_any_reference_form():
    for reference in (
        "api-security-auditor",
        "api_security_auditor",
        "agent:api_security_auditor",
    ):
        assert classify(reference).role == ROLE_REASONER


def test_classify_all_covers_every_agent(graph):
    assignments = classify_all(graph)
    assert set(assignments) == set(graph.agents)
    assert all(
        assignment.role in {ROLE_REASONER, ROLE_PRIMARY_CODER}
        for assignment in assignments.values()
    )


def test_reviewers_are_a_small_minority(graph):
    """A classifier that labels a large share of the library as reviewers is wrong.

    A broad rule matched 82 of 528. The narrow one should stay near a dozen: if
    this ever grows substantially, the vocabulary has drifted rather than the
    library.
    """
    found = reviewers(graph)
    assert 5 <= len(found) <= 20, f"{len(found)} reviewers is outside the expected band"
    assert all(agent_id in graph.agents for agent_id in found)


def test_the_fixture_reviewers_are_exactly_the_classified_reviewers(graph):
    """Keeps the fixture honest as the library changes.

    If the library adds a reviewer, this fails and the fixture is updated
    deliberately -- rather than the new persona silently landing on the coder
    role, which is the failure mode this whole module addresses.
    """
    classified = {ids.slug_of(agent_id).replace("_", "-") for agent_id in reviewers(graph)}
    expected = set(REVIEWER_FIXTURE)
    assert classified == expected, (
        f"only in library: {sorted(classified - expected)}; "
        f"only in fixture: {sorted(expected - classified)}"
    )
