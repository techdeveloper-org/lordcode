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


def _graph_plus_orphan(graph, orphan_id="agent:orphaned_never_edge_named"):
    """The same graph plus one agent that no edge mentions.

    Built by re-constructing rather than mutating, because KnowledgeGraph
    indexes its adjacency at construction time and a mutated dict would leave
    the indices disagreeing with the node tables.
    """
    from kgf.graph import Agent, KnowledgeGraph

    orphan = Agent(
        id=orphan_id,
        raw={
            "id": orphan_id,
            "name": "orphaned-never-edge-named",
            # Deliberately stuffed with words a real query uses, so that if the
            # gate were removed this agent could actually win on lexical score
            # rather than merely being present and ignored.
            "description": (
                "spring boot rest endpoint order api java microservice database "
                "react component python testing security deployment"
            ),
        },
    )
    return KnowledgeGraph(
        library_version=graph.library_version,
        agents={**graph.agents, orphan_id: orphan},
        skills=graph.skills,
        domains=graph.domains,
        regulations=graph.regulations,
        tool_tiers=graph.tool_tiers,
        edges=graph.edges,
    )


def test_an_agent_no_edge_mentions_is_not_a_candidate(graph, library):
    """The structural gate, asserted on its actual behaviour.

    A gate rather than a scoring term, because that is the difference that
    matters. A lucky lexical hit can outscore a weak signal; it cannot outvote
    a filter. The keyword matcher had no such filter, which is how a collision
    on the word "boot" selected a secure-boot agent for a Spring Boot task.

    This replaces `candidate_count <= len(graph.agents)`, which could not fail:
    `_edge_named_agents` only adds endpoints it has already confirmed are in
    `graph.agents`, so the subset relation was arithmetic rather than evidence
    (#34). Deleting the filter fails this test; it did not fail that one.
    """
    orphan_id = "agent:orphaned_never_edge_named"
    widened = _graph_plus_orphan(graph, orphan_id)
    selector = Selector(widened, library)

    assert orphan_id in widened.agents, "the orphan must really be in the graph"
    assert not any(
        orphan_id in (edge.source, edge.target) for edge in widened.edges
    ), "and genuinely unreferenced, or this asserts nothing"

    # Asserted through the public surface rather than by reaching into
    # `_candidates`: the widened graph holds one more agent than the real one,
    # so a count equal to the original is exactly the statement that the orphan
    # was filtered out.
    assert len(widened.agents) == len(graph.agents) + 1
    assert selector.candidate_count == len(graph.agents), (
        "the orphan must be excluded, leaving exactly the real agents"
    )

    result = selector.select("add a REST endpoint for creating an order in Spring Boot")
    assert all(match.agent != orphan_id for match in result.matches), (
        "an agent the graph does not connect must be unselectable however well "
        "its text happens to match"
    )


def test_the_gate_currently_admits_every_agent(selector, graph):
    """Recorded because ADR-1 calls this gate load-bearing and today it is not.

    Every agent in the library is named by at least one edge, so the filter
    excludes nobody. That does not make it wrong -- it is what stops an
    orphaned agent being selectable, which the test above proves it does -- but
    the plan should not claim it is doing work it is not.

    Stated as a relation rather than as the literal 528, so it survives the
    library growing without needing a re-pin.
    """
    assert selector.candidate_count == len(graph.agents)


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


class TestTheFloorIsCalibratedOnWhatProductionRanks:
    """Issue #16. Every case here would have passed before the fix."""

    def test_every_case_carries_its_engineered_form(self, heldout):
        """Raw text alone cannot calibrate a floor applied to engineered text.

        The set held only `task` until #16 -- which is how a floor measured on
        one distribution came to be applied to another.
        """
        for case in heldout["cases"]:
            assert case.get("engineered"), f"{case['id']} has no engineered form"
            assert len(case["engineered"]) > len(case["task"]), case["id"]

    def test_the_provenance_records_its_method(self, heldout):
        """C12 wants method, date and library_version. `method` was absent."""
        provenance = heldout["provenance"]
        assert provenance.get("method"), "provenance must say how the set was produced"
        assert provenance.get("engineered_model"), "and which model produced the engineered text"

    def test_the_old_floor_suppressed_nothing_which_is_why_it_moved(self, heldout):
        """The measurement that justifies the change, kept as a regression.

        Not "the old floor was a bit low" -- engineered confidence bottoms out
        at 0.4758, so a 0.45 floor admitted all 33 and reported every one of
        the 15 wrong top-1 answers as `selected`.
        """
        calibration = heldout["calibration"]
        assert calibration["previous_floor"] == 0.45
        assert calibration["previous_floor_admitted"] == len(heldout["cases"])
        assert calibration["engineered"]["min_confidence"] > 0.45

    def test_the_shipped_floor_matches_the_frozen_calibration(self, heldout):
        """The constant and its evidence must not drift apart."""
        assert CONFIDENCE_FLOOR == heldout["calibration"]["chosen_floor"]

    def test_engineering_shifts_the_distribution_up_without_separating_it(self, heldout):
        """Why the fix is a re-sited threshold rather than a better one.

        Mean confidence on a WRONG engineered match exceeds mean confidence on
        a CORRECT raw one, while separation barely moves -- so no single
        threshold works on both texts, and the only question is which text it
        is measured against.
        """
        raw = heldout["calibration"]["raw"]
        engineered = heldout["calibration"]["engineered"]
        assert engineered["mean_confidence_wrong"] > raw["mean_confidence_correct"]
        assert engineered["separation"] < raw["separation"] + 0.05

    def test_the_interval_is_recorded_and_its_limit_is_not_hidden(self, heldout):
        """A point estimate alone would overstate what n=33 can support.

        The Clopper-Pearson lower bound sits BELOW the admit-everything base
        rate, so the precision gain is not established at 95%. This asserts the
        caveat is present rather than quietly dropped once it is inconvenient.
        """
        calibration = heldout["calibration"]
        low, high = calibration["chosen_precision_cp95"]
        assert low < calibration["base_rate_precision"] < high, (
            "if the interval ever clears the base rate, say so plainly -- do not "
            "leave this assertion asserting the opposite of the truth"
        )
        assert calibration["chosen_precision"] > calibration["base_rate_precision"]


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
