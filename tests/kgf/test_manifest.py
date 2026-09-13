"""Tests for ADR-7's run manifest and replay.

Round-tripping is the least interesting property here and the easiest to pass,
so most of these assert the opposite: that a CHANGED library, ranker or context
is reported rather than absorbed. A manifest that cannot detect drift would
satisfy ADR-7's letter and none of its purpose.

Windows-safe: ASCII only.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from kgf import manifest as manifest_module
from kgf.closure import build_closure
from kgf.context import Intent, assemble_context
from kgf.loader import load_graph
from kgf.select import Selector
from kgf.source import locate_library

TASK = "build a spring boot REST service with JPA"


@pytest.fixture(scope="module")
def recorded():
    """A manifest built from a real selection, closure and assembled context."""
    source = locate_library(None)
    graph, _log = load_graph(None)
    selection = Selector(graph, source).select(TASK)
    closure = build_closure(graph, selection.best.agent)
    assembled = assemble_context(
        graph, source, closure, intent=Intent.IMPLEMENT, budget_tokens=2000
    )
    return manifest_module.build(
        TASK, source, selection, closure, assembled, intent="implement", budget_tokens=2000
    )


class TestWhatIsRecorded:
    def test_the_library_is_identified_by_content_not_mtime(self, recorded):
        """fingerprint() returned mtime_ns until this needed it, and mtime is
        wrong here: a fresh clone gives every file a new mtime, so a replay
        could never succeed on another machine."""
        assert len(recorded.registry_digests) == 5
        for name, digest in recorded.registry_digests:
            assert name.endswith(".json")
            assert len(digest) == 64, f"{name} digest is not a sha256"

    def test_the_decision_and_its_evidence_are_recorded(self, recorded):
        assert recorded.agent.startswith("agent:")
        assert recorded.outcome in {"selected", "low_confidence", "no_match"}
        assert recorded.confidence > 0
        assert recorded.edge_path
        assert recorded.query_terms

    def test_disambiguation_considered_is_recorded(self, recorded):
        """The plan calls M11's third embedding trigger unfalsifiable without
        this field. SelectionResult always carried it; nothing recorded it."""
        assert isinstance(recorded.disambiguation_considered, tuple)

    def test_the_closure_is_recorded(self, recorded):
        assert recorded.mandatory_skills
        assert recorded.depth_reached >= 0

    def test_the_context_ledger_is_recorded(self, recorded):
        assert recorded.context_tokens > 0
        assert recorded.included
        assert all(" :: " in label for label in recorded.included)

    def test_the_context_text_is_hashed_not_stored(self, recorded):
        """A manifest records a decision; it is not a cache of its output."""
        assert len(recorded.context_sha256) == 64
        blob = recorded.to_json()
        assert "Response Rules" not in blob or len(blob) < 20000

    def test_a_manifest_stays_small(self, recorded):
        assert len(recorded.to_json()) < 20000


class TestRoundTrip:
    def test_write_then_load_is_lossless(self, recorded, tmp_path):
        path = recorded.write(tmp_path / "m.json")
        assert manifest_module.load(path) == recorded

    def test_unknown_keys_are_ignored(self, recorded, tmp_path):
        """A manifest from a newer kgf must still be readable by an older one."""
        path = tmp_path / "m.json"
        payload = json.loads(recorded.to_json())
        payload["a_field_from_the_future"] = 1
        path.write_text(json.dumps(payload), encoding="utf-8")

        assert manifest_module.load(path) == recorded

    def test_a_missing_required_field_names_itself(self, tmp_path):
        """Letting the dataclass raise would describe kgf's internals instead
        of the file the caller is holding."""
        path = tmp_path / "bad.json"
        path.write_text("{}", encoding="utf-8")

        with pytest.raises(ValueError, match="missing manifest field"):
            manifest_module.load(path)

    def test_a_json_array_is_refused(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("[]", encoding="utf-8")

        with pytest.raises(ValueError, match="not a manifest object"):
            manifest_module.load(path)


class TestReplayDetectsDrift:
    """Each case is the honest answer a manifest exists to give."""

    def test_an_unchanged_library_replays_clean(self, recorded):
        report = manifest_module.replay(recorded)
        assert report.matches, report.summary()
        assert "no differences" in report.summary()

    def test_a_new_library_version_is_reported(self, recorded):
        report = manifest_module.replay(dataclasses.replace(recorded, library_version="29.98.0"))
        assert not report.matches
        assert any("library_version" in difference for difference in report.differences)

    def test_changed_registry_bytes_are_reported(self, recorded):
        """The case library_version alone cannot catch: an unreleased local
        edit does not move the version."""
        tampered = (("agents_all.json", "0" * 64),) + recorded.registry_digests[1:]
        report = manifest_module.replay(dataclasses.replace(recorded, registry_digests=tampered))

        assert not report.matches
        assert any("agents_all.json" in difference for difference in report.differences)

    def test_a_different_selected_agent_is_reported(self, recorded):
        report = manifest_module.replay(dataclasses.replace(recorded, agent="agent:somebody_else"))
        assert any(difference.startswith("agent:") for difference in report.differences)

    def test_a_moved_confidence_is_reported(self, recorded):
        report = manifest_module.replay(
            dataclasses.replace(recorded, confidence=recorded.confidence + 0.05)
        )
        assert any("confidence" in difference for difference in report.differences)

    def test_a_confidence_within_float_tolerance_is_not_reported(self, recorded):
        """Scoring is deterministic, so the tolerance absorbs representation
        noise and nothing else."""
        report = manifest_module.replay(
            dataclasses.replace(recorded, confidence=recorded.confidence + 1e-9)
        )
        assert not any("confidence" in difference for difference in report.differences)

    def test_a_smaller_context_is_reported(self, recorded):
        report = manifest_module.replay(
            dataclasses.replace(recorded, context_tokens=recorded.context_tokens - 300)
        )
        assert any("context_tokens" in difference for difference in report.differences)

    def test_changed_context_text_is_reported(self, recorded):
        report = manifest_module.replay(dataclasses.replace(recorded, context_sha256="f" * 64))
        assert any("context_sha256" in difference for difference in report.differences)

    def test_a_lost_mandatory_skill_is_reported_with_its_name(self, recorded):
        missing = recorded.mandatory_skills[-1]
        report = manifest_module.replay(
            dataclasses.replace(recorded, mandatory_skills=recorded.mandatory_skills[:-1])
        )
        assert any(missing in difference for difference in report.differences)

    def test_an_unresolvable_agent_is_reported_rather_than_crashing(self, recorded):
        report = manifest_module.replay(
            dataclasses.replace(recorded, forced_agent=True, agent="agent:deleted_from_the_library")
        )
        assert any("no longer resolves" in difference for difference in report.differences)

    def test_the_summary_lists_every_difference(self, recorded):
        report = manifest_module.replay(
            dataclasses.replace(recorded, library_version="29.98.0", context_sha256="f" * 64)
        )
        summary = report.summary()
        assert "2 difference(s)" in summary
        assert "library_version" in summary and "context_sha256" in summary


class TestReplayOfAForcedAgent:
    def test_ranking_is_skipped(self):
        """Re-ranking a forced-agent manifest would compare a decision that was
        never made."""
        source = locate_library(None)
        graph, _log = load_graph(None)
        closure = build_closure(graph, "as-built-doc-generator")
        forced = manifest_module.build(
            "anything at all", source, None, closure, None, forced_agent=True
        )

        report = manifest_module.replay(forced)

        assert report.matches, report.summary()
        assert not any("agent" in difference for difference in report.differences)


class TestSelectionOnlyManifest:
    def test_route_can_record_without_paying_for_context(self):
        """kgf route writes one of these; forcing it to assemble context just to
        record a selection would make the cheap command expensive."""
        source = locate_library(None)
        graph, _log = load_graph(None)
        selection = Selector(graph, source).select(TASK)

        recorded = manifest_module.build(TASK, source, selection)

        assert recorded.agent
        assert recorded.context_sha256 == ""
        assert recorded.mandatory_skills == ()

    def test_it_still_replays_and_checks_the_closure(self):
        source = locate_library(None)
        graph, _log = load_graph(None)
        selection = Selector(graph, source).select(TASK)

        report = manifest_module.replay(manifest_module.build(TASK, source, selection))

        assert report.matches, report.summary()
