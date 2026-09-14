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


def _synthetic_library(tmp_path, documents):
    """A LibrarySource over documents this test writes.

    `validate_markdown` only globs `skills_dir` and `agents_dir`, so a source
    pointed at a temporary root exercises the validator without depending on
    the live library holding any particular defect.
    """
    from kgf.source import LibrarySource

    root = tmp_path / "library"
    (root / "agents").mkdir(parents=True, exist_ok=True)
    for name, content in documents.items():
        target = root / "skills" / name / "SKILL.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")
    return LibrarySource(root=root, library_version="synthetic")


def test_markdown_is_validated_because_json_cannot_reveal_it(tmp_path):
    """A malformed document can be a VALID record in the registries.

    That is the whole reason this half exists: a JSON-only validator reports a
    clean library while documents cannot be read at all. Asserted against a
    document written here -- the live library had 18 such files until they were
    repaired at source (their #160), and resting this on them meant the repair
    would have retired the test.
    """
    source = _synthetic_library(
        tmp_path,
        {
            "good-core": "---\ndescription: fine\n---\n\nbody\n",
            "broken-core": '---\ndescription: "unterminated\n---\n\nbody\n',
        },
    )
    report = validate_markdown(source)

    assert set(report.failed) == {"broken-core"}
    assert report.parsed == 1, "the well-formed document must still be counted"


def test_bom_only_files_are_recovered_not_counted_as_broken(tmp_path):
    """A BOM'd file parses under utf-8-sig and is reported, not failed.

    Reported rather than ignored because any consumer reading plain utf-8 still
    drops it -- which is why the library's 13 were repaired at source even
    though kgf itself could already read them.
    """
    source = _synthetic_library(
        tmp_path,
        {
            "bommed-core": b"\xef\xbb\xbf---\ndescription: fine\n---\n\nbody\n",
            "plain-core": "---\ndescription: fine\n---\n\nbody\n",
        },
    )
    report = validate_markdown(source)

    assert report.bom_stripped == ["bommed-core"]
    assert report.failed == {}, "a BOM alone is not a parse failure"
    assert not set(report.bom_stripped) & set(report.failed)


def test_the_live_library_has_no_unreadable_documents(library, at_pinned_version):
    """The regression guard for the repair, and the only live-library claim here.

    Separated from the three behavioural tests above on purpose: those own the
    validator, this owns the data. If the library regresses, exactly one test
    fails and it names the file.
    """
    report = validate_markdown(library)
    if at_pinned_version:
        assert report.failed == {}, f"unreadable documents returned: {sorted(report.failed)}"
        assert report.bom_stripped == [], f"BOM returned in: {report.bom_stripped}"
        assert report.parsed == 1562
    else:
        assert report.parsed > 1500


def test_fault_classes_distinguish_repairs_that_differ(tmp_path):
    """The classes exist because their fixes differ, so each must be separable.

    A file with an opening quote and no closing one needs the terminator added;
    escaping its (non-existent) interior quotes repairs nothing. An earlier
    draft of the plan had those two diagnoses swapped, and the repair that
    actually landed proved the distinction real: `elixir-language-core` needed a
    backslash ADDED while `jenkins-pipeline` needed one REMOVED.

    Written against synthetic documents because the live library no longer has
    any -- one of each class, so a classifier that collapses two of them fails
    here rather than silently mis-advising a future repair.
    """
    source = _synthetic_library(
        tmp_path,
        {
            "unquoted-core": "---\ndescription: has Keywords: a colon\n---\n\nbody\n",
            "unterminated-core": '---\ndescription: "no closing quote\n---\n\nbody\n',
            "interior-core": '---\ndescription: "an "interior" quote"\n---\n\nbody\n',
            "nofrontmatter-core": "# no frontmatter at all\n\nbody\n",
        },
    )
    faults = validate_markdown(source).by_fault()

    assert set(faults) <= {
        "unquoted-scalar",
        "unterminated-quote",
        "unescaped-interior-quote",
        "no-frontmatter-block",
        "frontmatter-not-a-mapping",
        "other-yaml-fault",
    }
    assert "other-yaml-fault" not in faults, "an unclassified fault means the classifier needs a case"
    assert len(faults) >= 3, f"the classes must separate, got {faults}"
    assert "no-frontmatter-block" in faults


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
