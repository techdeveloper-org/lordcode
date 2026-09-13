"""Tests for reading the markdown behind the registries, and the backfill.

The finding this module exists for: 147 agent records and 134 skill records
carry no description in the registries, and their markdown frontmatter carries
one for all 281. The text was never missing, the registry build dropped it.
"""

from __future__ import annotations

from kgf.documents import agent_document, backfilled_descriptions, parse_document, skill_document


def test_a_well_formed_document_parses(library):
    document = skill_document(library, "java-spring-boot-microservices")
    assert document.ok
    assert document.description
    assert document.body
    assert document.frontmatter.get("name")


def test_keywords_are_extracted_from_the_description_tail(library):
    document = skill_document(library, "java-spring-boot-microservices")
    assert document.keywords
    assert all(keyword for keyword in document.keywords)


def test_declared_tools_parse_from_both_shapes(library):
    """Agents use a YAML list, skills often a comma-separated string."""
    agent = agent_document(library, "spring-boot-microservices")
    skill = skill_document(library, "java-spring-boot-microservices")
    assert agent.declared_tools()
    assert skill.declared_tools()
    assert all("," not in tool for tool in skill.declared_tools())


def test_a_missing_document_is_reported_not_raised(library):
    document = skill_document(library, "no-such-skill-exists-here")
    assert not document.ok
    assert document.error == "missing"
    assert document.description == ""


def test_a_malformed_document_is_reported_not_raised(library, tmp_path):
    """18 library documents are genuinely malformed.

    One appearing in a closure must degrade that entry, not abort the run.
    """
    broken = tmp_path / "SKILL.md"
    broken.write_text('---\ndescription: "unterminated\n---\nbody\n', encoding="utf-8")
    document = parse_document(library, broken)
    assert not document.ok
    assert "yaml" in document.error


def test_a_document_without_frontmatter_is_reported(library, tmp_path):
    plain = tmp_path / "SKILL.md"
    plain.write_text("no frontmatter here\n", encoding="utf-8")
    assert parse_document(library, plain).error == "no-frontmatter-block"


def test_a_bom_prefixed_document_still_parses(library, tmp_path):
    """13 library files are BOM'd; utf-8-sig is why they are readable at all."""
    bommed = tmp_path / "SKILL.md"
    bommed.write_bytes("---\nname: x\ndescription: y\n---\nbody\n".encode("utf-8-sig"))
    document = parse_document(library, bommed)
    assert document.ok
    assert document.description == "y"


def test_the_backfill_recovers_descriptions_the_registries_lost(library, graph):
    recovered = backfilled_descriptions(library)
    assert len(recovered) > 200, f"expected ~281 recovered descriptions, got {len(recovered)}"

    missing_in_registry = [
        record.name
        for record in list(graph.skills.values()) + list(graph.agents.values())
        if not record.description
    ]
    assert missing_in_registry
    covered = sum(1 for name in missing_in_registry if name in recovered)
    assert covered / len(missing_in_registry) > 0.95, (
        "nearly every registry-missing description should be recoverable from markdown"
    )


def test_recovered_descriptions_are_substantial_not_placeholders(library):
    recovered = backfilled_descriptions(library)
    lengths = [len(text) for text in recovered.values()]
    assert min(lengths) > 40
    assert sum(lengths) / len(lengths) > 200


def test_the_backfill_is_cached_across_calls(library):
    first = backfilled_descriptions(library)
    second = backfilled_descriptions(library)
    assert first is second
