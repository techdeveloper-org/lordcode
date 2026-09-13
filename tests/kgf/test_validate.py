"""Tests for graph validation and the markdown half that JSON cannot see."""

from __future__ import annotations

import yaml

from kgf.errors import ProblemLog, Severity
from kgf.validate import (
    KNOWN_DANGLING_REGULATIONS,
    KNOWN_DANGLING_SKILLS,
    classify_yaml_fault,
    summarize,
    validate_graph,
    validate_markdown,
)


def test_every_dangling_endpoint_is_allowlisted(graph, problems):
    """Both allowlists together must cover all 21 distinct dangling ids.

    If a new one appears, UNEXPECTED_DANGLING fires -- that is the drift
    signal, and the reason the ceiling alone is not enough.
    """
    log = validate_graph(graph, ProblemLog())
    unexpected = [p for p in log.of(Severity.DEFECT) if p.code == "UNEXPECTED_DANGLING"]
    assert unexpected == [], f"un-allowlisted dangling endpoints: {[p.source for p in unexpected]}"


def test_the_allowlists_are_exhaustive_and_not_oversized(graph):
    """Every allowlisted id must actually still dangle.

    An entry that no longer occurs means the library fixed it, and keeping it
    would hide a future regression at that id.
    """
    dangling = set(graph.dangling_endpoints())
    allowed = KNOWN_DANGLING_REGULATIONS | KNOWN_DANGLING_SKILLS
    assert dangling <= allowed, f"dangling outside the allowlists: {sorted(dangling - allowed)}"

    stale = sorted(allowed - dangling)
    assert not stale, f"allowlist entries no longer dangling, remove them: {stale}"


def test_the_two_allowlists_are_kept_separate(graph):
    """They differ in provenance, which is why they are not one set.

    The 9 regulation ids are the library's own qa_report.json W-013 warnings.
    The 16 skill ids its QA does NOT flag -- kgf found those, and collapsing
    them together would lose that distinction.
    """
    dangling = graph.dangling_endpoints()
    reg_ids = {node for node in dangling if node.startswith("reg:")}
    skill_ids = {node for node in dangling if node.startswith("skill:")}

    assert reg_ids == set(KNOWN_DANGLING_REGULATIONS)
    assert skill_ids == set(KNOWN_DANGLING_SKILLS)
    assert not KNOWN_DANGLING_REGULATIONS & KNOWN_DANGLING_SKILLS


def test_dangling_occurrences_exceed_distinct_ids(graph):
    """9 regulation occurrences come from 5 distinct ids, so the two differ."""
    dangling = graph.dangling_endpoints()
    assert sum(dangling.values()) > len(dangling)


def test_tooltier_id_divergence_is_reported_not_hidden(graph):
    log = validate_graph(graph, ProblemLog())
    codes = {problem.code for problem in log.of(Severity.INFO)}
    assert "TOOLTIER_ID_DIVERGENCE" in codes


def test_markdown_is_validated_because_json_cannot_reveal_it(library, graph):
    """Every malformed document is a VALID record in the registries.

    That is the whole reason this half exists: a JSON-only validator reports a
    clean library while 18 documents cannot be read at all.
    """
    report = validate_markdown(library)
    assert report.failed, "expected the known malformed documents to be detected"

    for label in report.failed:
        in_registries = (
            graph.skill(label) is not None or graph.agent(label) is not None
        )
        assert in_registries, f"{label} should still be present in the registries"


def test_bom_only_files_are_recovered_not_counted_as_broken(library):
    """13 files are merely BOM'd; utf-8-sig recovers all of them."""
    report = validate_markdown(library)
    assert len(report.bom_stripped) > 0
    assert not set(report.bom_stripped) & set(report.failed), (
        "a BOM'd file must not also be reported as malformed"
    )


def test_fault_classes_distinguish_repairs_that_differ(library):
    """The classes exist because their fixes differ.

    A file with an opening quote and no closing one needs the terminator
    added; escaping its (non-existent) interior quotes repairs nothing. An
    earlier draft of this plan had those two diagnoses swapped.
    """
    report = validate_markdown(library)
    faults = report.by_fault()
    assert faults, "expected at least one fault class"
    assert set(faults) <= {
        "unquoted-scalar",
        "unterminated-quote",
        "unescaped-interior-quote",
        "no-frontmatter-block",
        "frontmatter-not-a-mapping",
        "other-yaml-fault",
    }
    assert "other-yaml-fault" not in faults, "an unclassified fault means the classifier needs a case"


def test_classify_yaml_fault_maps_each_real_error_shape():
    def fault_of(text: str) -> str:
        try:
            yaml.safe_load(text)
        except yaml.YAMLError as exc:
            return classify_yaml_fault(exc)
        raise AssertionError(f"expected {text!r} to fail parsing")

    assert fault_of('description: Act 1996: amended\n') == "unquoted-scalar"
    assert fault_of('description: "unterminated\n') == "unterminated-quote"
    assert fault_of('description: "has "interior" quotes"\nname: x\n') == "unescaped-interior-quote"


def test_summarize_reports_the_load_without_a_model_call(graph, problems):
    text = summarize(graph, problems, None)
    assert graph.library_version in text
    assert "FATAL: 0" in text
    assert "dangling endpoints:" in text
