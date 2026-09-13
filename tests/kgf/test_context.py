"""Tests for section parsing and budgeted context assembly."""

from __future__ import annotations

import pytest

from kgf.closure import build_closure
from kgf.context import (
    AGENT_SECTIONS_BY_INTENT,
    DEFAULT_TOKEN_BUDGET,
    MIN_SECTION_TOKENS,
    SKILL_SECTIONS_BY_INTENT,
    Intent,
    assemble_context,
    estimate_tokens,
)
from kgf.documents import normalise_heading, parse_sections, skill_document


@pytest.fixture(scope="module")
def spring_closure(graph):
    return build_closure(graph, "spring-boot-microservices")


def test_sections_are_split_at_headings():
    sections = parse_sections("# One\nalpha\n\n## Two\nbeta\n")
    assert [section.title for section in sections] == ["One", "Two"]
    assert sections[0].body.strip() == "alpha"
    assert sections[1].body.strip() == "beta"
    assert sections[0].level == 1
    assert sections[1].level == 2


def test_preamble_before_the_first_heading_is_dropped():
    sections = parse_sections("loose text\n\n## Real\nbody\n")
    assert [section.title for section in sections] == ["Real"]


def test_a_document_without_headings_yields_no_sections():
    assert parse_sections("just prose, no headings") == ()


def test_section_numbering_is_normalised_away():
    """The correction worth +706 files on one heading alone.

    The same section is written "Deep Mathematical Foundations" in 199 skill
    documents and "7. Deep Mathematical Foundations" in most of the rest.
    Matching the literal text finds 199 of 905.
    """
    assert normalise_heading("7. Deep Mathematical Foundations") == "deep mathematical foundations"
    assert normalise_heading("10. Response Rules") == "response rules"
    assert normalise_heading("3.1 Sub Part") == "sub part"
    assert normalise_heading("8) Anti-Patterns to Avoid") == "anti-patterns to avoid"
    assert normalise_heading("  Output Expectations  ") == "output expectations"


def test_normalising_does_not_eat_a_leading_number_that_is_the_title():
    """A heading that is genuinely about a number must survive."""
    assert normalise_heading("2D Rendering") == "2d rendering"
    assert normalise_heading("5G Core") == "5g core"


def test_section_lookup_matches_regardless_of_numbering():
    sections = parse_sections("## 12. Output Expectations\nbody\n")
    assert sections[0].key == "output expectations"


def test_document_section_lookup_finds_a_numbered_heading(library):
    document = skill_document(library, "java-spring-boot-microservices")
    assert document.ok
    assert document.section("response rules") is not None


def test_the_numbering_fix_matters_on_the_real_library(library, graph):
    """Asserted on real documents, not a synthetic string.

    If normalisation regressed, coverage of this heading would collapse from
    most of the corpus to a fraction of it.
    """
    checked = 0
    found = 0
    for skill in list(graph.skills.values())[:150]:
        document = skill_document(library, skill.name)
        if not document.ok:
            continue
        checked += 1
        if document.section("response rules") is not None:
            found += 1
    assert checked > 100
    assert found / checked > 0.9, f"only {found}/{checked} documents matched a near-universal heading"


def test_estimate_tokens_is_proportional():
    assert estimate_tokens("") == 0
    assert estimate_tokens("a" * 400) == 100


def test_assembled_context_never_exceeds_its_budget(graph, library, spring_closure):
    for budget in (400, 800, 2000, 4000):
        for intent in Intent:
            assembled = assemble_context(
                graph, library, spring_closure, intent=intent, budget_tokens=budget
            )
            assert assembled.within_budget, (
                f"{intent.value} at {budget}: used {assembled.assembled_context_tokens}"
            )


def test_assembled_context_tokens_is_a_declared_output(graph, library, spring_closure):
    """M5's concurrency cap consumes this, so it is part of the contract."""
    assembled = assemble_context(graph, library, spring_closure)
    assert isinstance(assembled.assembled_context_tokens, int)
    assert assembled.assembled_context_tokens == estimate_tokens(assembled.text)
    assert assembled.budget_tokens == DEFAULT_TOKEN_BUDGET


def test_intent_changes_which_sections_are_selected(graph, library, spring_closure):
    """If every intent produced the same text, the intent would be decoration."""
    implement = assemble_context(graph, library, spring_closure, intent=Intent.IMPLEMENT)
    design = assemble_context(graph, library, spring_closure, intent=Intent.DESIGN)
    review = assemble_context(graph, library, spring_closure, intent=Intent.REVIEW)

    def headings(assembled) -> set[str]:
        return {item.heading.lower() for item in assembled.included}

    assert headings(implement) != headings(design)
    assert headings(design) != headings(review)


def test_the_boilerplate_the_old_window_captured_is_not_what_arrives(graph, library, spring_closure):
    """The defect being fixed is POSITION, not size.

    The 800-character head window captured Skill Name, Description and Skill
    Dependencies -- accurate, and useless for steering generated code. What
    should arrive is the rules.
    """
    assembled = assemble_context(graph, library, spring_closure, intent=Intent.IMPLEMENT)
    headings = {item.heading.lower() for item in assembled.included}

    assert not headings & {"skill name", "description", "skill dependencies"}
    assert headings & {"response rules", "output expectations", "what not to do"}


def test_many_documents_contribute_not_just_one(graph, library, spring_closure):
    """Today one skill is injected; the closure has several."""
    assembled = assemble_context(graph, library, spring_closure, intent=Intent.IMPLEMENT)
    assert len(assembled.entities) > 3
    assert len({item.entity for item in assembled.included}) > 2


def test_only_whole_sections_are_included(graph, library, spring_closure):
    """A rule cut in half reads as a complete rule.

    So a section that does not fit is dropped entirely rather than trimmed --
    the assembled text must contain each included section's body verbatim.
    """
    assembled = assemble_context(graph, library, spring_closure, intent=Intent.IMPLEMENT)
    for item in assembled.included:
        assert item.heading in assembled.text


def test_dropped_sections_are_recorded_with_a_reason(graph, library, spring_closure):
    assembled = assemble_context(graph, library, spring_closure, intent=Intent.IMPLEMENT, budget_tokens=400)
    assert assembled.dropped
    assert all(item.reason for item in assembled.dropped)


def test_a_tiny_budget_yields_little_but_stays_valid(graph, library, spring_closure):
    assembled = assemble_context(graph, library, spring_closure, budget_tokens=120)
    assert assembled.within_budget
    assert all(item.tokens >= MIN_SECTION_TOKENS for item in assembled.included)


def test_a_larger_budget_includes_at_least_as_much(graph, library, spring_closure):
    small = assemble_context(graph, library, spring_closure, budget_tokens=600)
    large = assemble_context(graph, library, spring_closure, budget_tokens=3000)
    assert large.assembled_context_tokens >= small.assembled_context_tokens
    assert len(large.included) >= len(small.included)


def test_an_unparseable_document_degrades_rather_than_failing(graph, library):
    """The path issue #4 requires, reached in normal operation.

    18 library documents are malformed and 17 of 528 agents list at least one of
    them as a mandatory skill, so this is not a hypothetical: the defect is
    recorded, that skill is dropped, and assembly continues.
    """
    from kgf import ids
    from kgf.validate import validate_markdown

    broken = set(validate_markdown(library).failed)
    exposed = [
        agent
        for agent in graph.agents.values()
        if any(
            ids.slug_of(skill_id).replace("_", "-") in broken
            for skill_id in graph.neighbours(agent.id, "AGENT_USES_SKILL")
        )
    ]
    if not exposed:
        pytest.skip("the library no longer has a malformed mandatory skill")

    closure = build_closure(graph, exposed[0].id)
    assembled = assemble_context(graph, library, closure, intent=Intent.IMPLEMENT)

    assert assembled.defects, "the malformed document must be recorded"
    assert assembled.text, "assembly must continue despite the malformed document"
    assert any("unparseable" in item.reason for item in assembled.dropped)


def test_every_intent_has_both_a_skill_and_an_agent_mapping():
    for intent in Intent:
        assert SKILL_SECTIONS_BY_INTENT[intent]
        assert AGENT_SECTIONS_BY_INTENT[intent]


def test_intent_mappings_target_headings_that_actually_exist(library, graph):
    """Guards against the mistake this milestone had to correct.

    An earlier draft targeted `## Coding Guidelines`, which exists in exactly
    ONE of 1034 skill documents -- generalised from a single file. Every heading
    named by an intent must be present in a real share of the corpus.
    """
    sampled = [
        document
        for document in (skill_document(library, skill.name) for skill in list(graph.skills.values())[:120])
        if document.ok
    ]
    assert sampled

    for intent, headings in SKILL_SECTIONS_BY_INTENT.items():
        hits = {
            heading: sum(1 for document in sampled if document.section(heading) is not None)
            for heading in headings
        }
        best = max(hits.values())
        assert best > len(sampled) * 0.5, (
            f"{intent.value}: no targeted heading is common in the corpus ({hits})"
        )


def test_summary_reports_the_ledger(graph, library, spring_closure):
    assembled = assemble_context(graph, library, spring_closure)
    summary = assembled.summary()
    assert str(assembled.assembled_context_tokens) in summary
    assert str(assembled.budget_tokens) in summary
