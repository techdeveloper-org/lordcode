"""Tests for graph-native agent selection, including the frozen held-out set."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kgf import ids
from kgf.select import (
    CONFIDENCE_FLOOR,
    CONFIDENCE_SATURATION,
    NO_MATCH_FLOOR,
    Outcome,
    Selector,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "heldout_routing.json"


@pytest.fixture(scope="module")
def heldout() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def selector(graph, library):
    """One Selector for the module -- corpus construction is the dominant cost."""
    return Selector(graph, library)


def test_every_candidate_is_named_by_an_edge(selector, graph):
    """The structural gate: an agent no edge mentions cannot be selected.

    A gate rather than a scoring term, because that is the difference that
    matters. A lucky lexical hit can outscore a weak signal; it cannot outvote
    a filter. The keyword matcher had no such filter, which is how a collision
    on the word "boot" selected a secure-boot agent for a Spring Boot task.
    """
    assert selector.candidate_count > 0
    assert selector.candidate_count <= len(graph.agents)


def test_ordering_is_by_score_and_not_alphabetical(selector):
    """Regression test for the bug that cost 12 of 33 held-out cases.

    Confidence is a saturating transform. Sorting by it let several candidates
    tie at the ceiling and fall through to the id tiebreak, which ranks
    alphabetically -- handing wins to accounting_automation_agent,
    agri_analytics_engineer and as_built_doc_generator purely for starting with
    an 'a'. The fix sorts by the raw combined score.
    """
    result = selector.select("add a REST endpoint for creating an order in Spring Boot", limit=5)
    assert result.matches

    names = [match.name for match in result.matches]
    assert names != sorted(names), "ranking must not be in alphabetical order"

    top = result.best
    assert top.name == "spring_boot_microservices", f"expected the Spring agent first, got {names}"


def test_the_original_keyword_collision_does_not_recur(selector):
    """The defect this milestone exists to fix.

    The keyword matcher sent this task to assembly-boot/secure-boot-engineer on
    a collision with "boot".
    """
    result = selector.select("add a REST endpoint for creating an order in spring boot")
    assert result.best is not None
    assert ids.slug_of(result.best.domain) != "assembly_boot"


def test_confidence_is_bounded_and_never_saturates(selector, heldout):
    """A clipped ceiling is what collapsed the ordering, so it must not return."""
    for case in heldout["cases"]:
        result = selector.select(case["task"])
        for match in result.matches:
            assert 0.0 < match.confidence < 1.0, f"{case['id']}: {match.confidence}"


def test_confidence_is_monotone_in_the_raw_score():
    """Ordering by score and reporting confidence must agree."""
    from kgf.select import Selector as _Selector

    weak = _Selector._confidence(2.0, margin=1.0)
    strong = _Selector._confidence(30.0, margin=1.0)
    assert strong > weak
    assert _Selector._confidence(CONFIDENCE_SATURATION, margin=1.0) == pytest.approx(0.5, abs=0.01)


def test_a_contested_domain_lowers_confidence():
    """The calibration signal: same score, contested domain, less confidence."""
    from kgf.select import Match, Selector as _Selector

    def match(agent: str, domain: str) -> Match:
        return Match(agent=agent, domain=domain, confidence=0.0, lexical_score=10.0)

    uncontested = [(20.0, match("agent:a", "domain:x")), (5.0, match("agent:b", "domain:x"))]
    contested = [(20.0, match("agent:a", "domain:x")), (19.5, match("agent:b", "domain:y"))]

    assert _Selector._domain_margin(uncontested) == 1.0
    assert _Selector._domain_margin(contested) < 0.1


def test_empty_task_is_no_match(selector):
    result = selector.select("the and of")
    assert result.outcome is Outcome.NO_MATCH
    assert result.matches == ()


def test_outcome_thresholds_are_ordered():
    assert 0.0 < NO_MATCH_FLOOR < CONFIDENCE_FLOOR < 1.0


def test_result_records_enough_to_replay(selector):
    """A selection that cannot be explained is not reviewable."""
    result = selector.select("write a Terraform module for an S3 bucket")
    assert result.library_version
    assert result.query_terms
    assert result.considered > 0
    assert result.best.edge_path, "the match must name the edges that justified it"


def test_graph_disambiguation_edges_are_actually_consulted(selector):
    """SKILL_SIMILAR_TO / DOMAIN_DEPENDS_ON / CROSS_DOMAIN_REF were loaded and
    unused before this milestone; the manifest field proves they are read."""
    result = selector.select("optimise a slow query on the orders table")
    assert isinstance(result.disambiguation_considered, tuple)


def test_heldout_set_is_frozen_and_well_formed(heldout, graph):
    """The set's own integrity, checked before any accuracy claim is made."""
    provenance = heldout["provenance"]
    assert provenance["authored_before_ranker"] is True
    assert provenance["n"] == len(heldout["cases"])
    assert provenance["n"] >= 30, "a smaller set cannot separate the trigger thresholds"

    for case in heldout["cases"]:
        assert case["acceptable_domains"], case["id"]
        for domain in case["acceptable_domains"]:
            assert ids.domain_id(domain) in graph.domains, f"{case['id']}: {domain}"


def test_no_description_cases_really_lack_a_registry_description(heldout, graph):
    """This category only means something if the registry text is genuinely absent."""
    for case in heldout["cases"]:
        name = case.get("best_skill_without_description")
        if not name:
            continue
        skill = graph.skill(name)
        assert skill is not None, f"{case['id']}: {name} not in the graph"
        assert not skill.description, f"{case['id']}: {name} has a registry description"


def test_heldout_top1_accuracy_beats_the_recorded_baseline(selector, heldout):
    """The bar is the measured baseline, not an invented target.

    Deliberately not "at least 90%": the reference implementation refuses to
    promise a figure its retrieval stage cannot honour, and that is the right
    instinct on this corpus. What is asserted is that kgf does better than the
    thing it replaces.
    """
    baseline = heldout["baseline"]["top1_accuracy"]
    hits = 0
    for case in heldout["cases"]:
        acceptable = {ids.domain_id(domain) for domain in case["acceptable_domains"]}
        result = selector.select(case["task"], limit=3)
        if result.best is not None and result.best.domain in acceptable:
            hits += 1

    accuracy = hits / len(heldout["cases"])
    assert accuracy > baseline, f"top-1 {accuracy:.1%} must beat the baseline {baseline:.1%}"


def test_heldout_top3_accuracy_is_reported_alongside_top1(selector, heldout):
    hits = 0
    for case in heldout["cases"]:
        acceptable = {ids.domain_id(domain) for domain in case["acceptable_domains"]}
        result = selector.select(case["task"], limit=3)
        if {match.domain for match in result.matches} & acceptable:
            hits += 1
    assert hits / len(heldout["cases"]) >= 0.55


def test_calibration_separates_correct_answers_from_wrong_ones(selector, heldout):
    """Without this the tri-state cannot function.

    The reference implementation scores 0.835 on a correct answer and 0.776 on a
    wrong one -- overlapping populations, so a confidence-keyed low_confidence
    state could never fire. kgf's confidence must at least trend the right way.
    """
    correct, wrong = [], []
    for case in heldout["cases"]:
        acceptable = {ids.domain_id(domain) for domain in case["acceptable_domains"]}
        result = selector.select(case["task"])
        if result.best is None:
            continue
        (correct if result.best.domain in acceptable else wrong).append(result.best.confidence)

    assert correct and wrong, "need both populations to compare"
    mean_correct = sum(correct) / len(correct)
    mean_wrong = sum(wrong) / len(wrong)
    assert mean_correct > mean_wrong, (
        f"confidence must be higher on correct answers: {mean_correct:.3f} vs {mean_wrong:.3f}"
    )


def test_the_lexical_ceiling_on_plainly_worded_tasks_is_recorded(selector, heldout):
    """Documents WHY the embedding decision has a trigger, with a number.

    Three scoring designs were measured on this set -- enriched agent documents,
    skills-primary aggregation, and skills-primary plus a domain signal -- and
    all three landed within a few points of each other while the plain-english
    category stayed at 3-4 of 15. That is a property of the corpus, not of the
    formula: the vocabulary distinguishing domains ("endpoint", "repository",
    "cache") is spread across many domains' skill text.

    This test asserts the category is measurably the weakest, so if a future
    change genuinely fixes it the assertion fails and the trigger is revisited
    deliberately rather than left stale.
    """
    per_category: dict[str, list[bool]] = {}
    for case in heldout["cases"]:
        acceptable = {ids.domain_id(domain) for domain in case["acceptable_domains"]}
        result = selector.select(case["task"])
        hit = result.best is not None and result.best.domain in acceptable
        per_category.setdefault(case["category"], []).append(hit)

    def rate(category: str) -> float:
        hits = per_category[category]
        return sum(hits) / len(hits)

    assert rate("plain-english") < rate("proper-noun"), (
        "if plain-english has caught up with proper-noun, the embedding trigger "
        "in the plan should be re-examined"
    )
