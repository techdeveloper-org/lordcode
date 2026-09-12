"""Unit tests for Milestone 8's parallel_generate.py.

_persona_generate_subset is replaced with a module-level fake (same
pattern as test_orchestrator.py) rather than driven through a keyword-
matched FakeClient, since every group's coder call shares the same system
prompt (only file_paths differs) -- a fake keyed on file_paths directly
tests generate_parallel's real job (merging, duplicate detection) without
depending on LLM response content. plan_file_manifest, which has a single
distinctive system prompt, is tested via the real FakeClient pattern used
elsewhere in this suite.
"""

from __future__ import annotations

import json

import pytest

from vishwakarma.config import ModelConfig, RoleCandidate
from vishwakarma.engine import parallel_generate
from vishwakarma.engine.generate import GenerationError
from vishwakarma.router import Router

_MANIFEST_KEYWORD = "planning the file structure"


class FakeClient:
    """Same distinctive-keyword FakeClient pattern used across this suite."""

    def __init__(self, response_by_keyword: dict[str, object]):
        self.response_by_keyword = response_by_keyword
        self.call_log: list[str] = []

    def chat_completion(self, provider, model, messages, priority="interactive", **kwargs):
        self.call_log.append(f"{provider}/{model}")
        system_content = messages[0]["content"]
        for keyword, response in self.response_by_keyword.items():
            if keyword in system_content:
                if isinstance(response, Exception):
                    raise response
                return response
        raise AssertionError(f"No fake response configured for: {system_content[:120]!r}")


def _models() -> ModelConfig:
    return ModelConfig(
        roles={
            "fallback_long_context": [RoleCandidate(provider="groq", model="long-context")],
            "primary_coder": [RoleCandidate(provider="groq", model="coder")],
        },
        max_heal_attempts=3,
        heal_timeout_seconds=300,
    )


# --- _parse_file_manifest ----------------------------------------------------


def test_parse_file_manifest_accepts_valid_json():
    raw = json.dumps({"files": [{"path": "a.py", "responsibility": "does a"}]})
    assert parallel_generate._parse_file_manifest(raw) == [{"path": "a.py", "responsibility": "does a"}]


def test_parse_file_manifest_rejects_empty_list():
    with pytest.raises(GenerationError, match="valid JSON list"):
        parallel_generate._parse_file_manifest(json.dumps({"files": []}))


def test_parse_file_manifest_rejects_malformed_json():
    with pytest.raises(GenerationError, match="valid JSON list"):
        parallel_generate._parse_file_manifest("not json")


def test_parse_file_manifest_rejects_missing_keys():
    with pytest.raises(GenerationError, match="valid JSON list"):
        parallel_generate._parse_file_manifest(json.dumps({"files": [{"path": "a.py"}]}))


# --- plan_file_manifest (real spawn + FakeClient) ---------------------------


def test_plan_file_manifest_end_to_end(tmp_path):
    response = json.dumps({"files": [{"path": "a.py", "responsibility": "a"}, {"path": "b.py", "responsibility": "b"}]})
    client = FakeClient({_MANIFEST_KEYWORD: response})
    router = Router(_models(), client)
    events = []

    manifest = parallel_generate.plan_file_manifest("build a thing", "python", None, router, client, on_event=events.append)

    assert manifest == [{"path": "a.py", "responsibility": "a"}, {"path": "b.py", "responsibility": "b"}]
    assert {"type": "file_manifest_planned", "file_count": 2} in events


def test_plan_file_manifest_raises_on_invalid_response():
    client = FakeClient({_MANIFEST_KEYWORD: "not json"})
    router = Router(_models(), client)

    with pytest.raises(GenerationError, match="valid JSON list"):
        parallel_generate.plan_file_manifest("build a thing", "python", None, router, client)


# --- _partition_manifest ------------------------------------------------------


@pytest.mark.parametrize(
    "file_count,expected_group_count,expected_max_group_size",
    [
        (1, 1, 3),
        (3, 1, 3),
        (6, 2, 3),
        (9, 3, 3),
        (12, 4, 3),
        (20, 4, 5),  # exceeds MAX_PARALLEL_GROUPS*MAX_FILES_PER_GROUP -> groups grow, not multiply
    ],
)
def test_partition_manifest_respects_bounds(file_count, expected_group_count, expected_max_group_size):
    manifest = [{"path": f"f{i}.py", "responsibility": "x"} for i in range(file_count)]
    groups = parallel_generate._partition_manifest(manifest)

    assert len(groups) <= parallel_generate.MAX_PARALLEL_GROUPS
    assert len(groups) == expected_group_count
    assert max(len(g) for g in groups) <= expected_max_group_size
    assert sorted(p for g in groups for p in g) == sorted(item["path"] for item in manifest)


# --- generate_parallel --------------------------------------------------------


def _fake_persona_generate_subset(
    remote_llm, task, language, manifest, file_paths, context, skill, subagent, dependency_content=None
):
    return json.dumps({"files": [{"path": p, "content": f"content for {p}"} for p in file_paths]})


def test_generate_parallel_merges_groups_and_uses_run_agents_parallel(tmp_path, monkeypatch):
    monkeypatch.setattr(parallel_generate, "_persona_generate_subset", _fake_persona_generate_subset)

    manifest = [{"path": p, "responsibility": "x"} for p in ["a.py", "b.py", "c.py", "d.py"]]
    groups = [["a.py", "b.py"], ["c.py", "d.py"]]

    class _TripwireClient:
        def chat_completion(self, *a, **k):
            raise AssertionError("real LLM call should not happen")

    client = _TripwireClient()
    router = Router(_models(), client)

    artifact = parallel_generate.generate_parallel("task", "python", manifest, groups, router, client)

    assert sorted(f.path for f in artifact.files) == ["a.py", "b.py", "c.py", "d.py"]
    assert all(f.content == f"content for {f.path}" for f in artifact.files)


def test_generate_parallel_raises_on_duplicate_path_within_assigned_paths(tmp_path, monkeypatch):
    """A path both groups are actually assigned (a genuine partitioning bug,
    since _partition_manifest should never produce overlapping groups) must
    still raise -- unlike an unassigned over-generated file (see
    test_generate_parallel_drops_unassigned_files_instead_of_raising), which
    is safe to drop because the path's real owner group still produces it."""
    monkeypatch.setattr(parallel_generate, "_persona_generate_subset", _fake_persona_generate_subset)

    manifest = [{"path": "a.py", "responsibility": "x"}, {"path": "b.py", "responsibility": "y"}]
    groups = [["a.py"], ["a.py", "b.py"]]  # overlapping on purpose -- not a real _partition_manifest output

    class _TripwireClient:
        def chat_completion(self, *a, **k):
            raise AssertionError("real LLM call should not happen")

    client = _TripwireClient()
    router = Router(_models(), client)

    with pytest.raises(GenerationError, match="Duplicate file path 'a.py'"):
        parallel_generate.generate_parallel("task", "python", manifest, groups, router, client)


def _over_generating_persona(
    remote_llm, task, language, manifest, file_paths, context, skill, subagent, dependency_content=None
):
    # Ignores the "generate ONLY these files" instruction and returns every
    # file in the manifest regardless of its own assigned file_paths --
    # reproduces the real Groq behavior seen in GitHub issue #1.
    return json.dumps({"files": [{"path": item["path"], "content": f"content for {item['path']}"} for item in manifest]})


def test_generate_parallel_drops_unassigned_files_instead_of_raising(monkeypatch):
    monkeypatch.setattr(parallel_generate, "_persona_generate_subset", _over_generating_persona)

    manifest = [{"path": p, "responsibility": "x"} for p in ["a.py", "b.py", "c.py", "d.py"]]
    groups = [["a.py", "b.py"], ["c.py", "d.py"]]

    class _TripwireClient:
        def chat_completion(self, *a, **k):
            raise AssertionError("real LLM call should not happen")

    client = _TripwireClient()
    router = Router(_models(), client)
    events = []

    artifact = parallel_generate.generate_parallel(
        "task", "python", manifest, groups, router, client, on_event=events.append
    )

    # Each path is kept exactly once, attributed to the group it was
    # actually assigned to -- not silently dropped, not fatal.
    assert sorted(f.path for f in artifact.files) == ["a.py", "b.py", "c.py", "d.py"]
    dropped = [e for e in events if e["type"] == "parallel_generation_unassigned_file_dropped"]
    assert len(dropped) == 4  # each group over-generated the other group's 2 files
    assert {"type": "parallel_generation_group_completed", "label": "group-0", "file_count": 2} in events
    assert {"type": "parallel_generation_group_completed", "label": "group-1", "file_count": 2} in events


# --- _extract_manifest_dependencies (Milestone 9) ----------------------------


def test_extract_manifest_dependencies_naming_convention_edge():
    manifest = [
        {"path": "models.py", "responsibility": "define the data model"},
        {"path": "test_models.py", "responsibility": "test the data model"},
    ]

    dependencies = parallel_generate._extract_manifest_dependencies(manifest)

    assert dependencies == {"test_models.py": {"models.py"}}


def test_extract_manifest_dependencies_empty_for_unrelated_manifest():
    manifest = [{"path": "a.py", "responsibility": "x"}, {"path": "b.py", "responsibility": "y"}]

    assert parallel_generate._extract_manifest_dependencies(manifest) == {}


# --- generate_parallel wave-based dependency content passing (Milestone 9) --


def _dependency_echoing_persona(
    remote_llm, task, language, manifest, file_paths, context, skill, subagent, dependency_content=None
):
    """Persona whose returned content encodes the dependency_content it was
    given, so a monkeypatch running across AgentCoordinator's real
    multiprocessing boundary can still be asserted on from the parent
    process (a plain side-effect list would not survive that boundary)."""
    encoded_deps = json.dumps(dependency_content) if dependency_content else "no-deps"
    return json.dumps({"files": [{"path": p, "content": encoded_deps} for p in file_paths]})


def test_generate_parallel_passes_earlier_wave_content_to_dependent_group(monkeypatch):
    """A cross-group dependency (via naming convention) must place the
    dependent file's group in a later wave, and that later group's persona
    call must receive the earlier wave's actual generated content -- not
    just the manifest's one-line description."""
    monkeypatch.setattr(parallel_generate, "_persona_generate_subset", _dependency_echoing_persona)

    manifest = [
        {"path": "models.py", "responsibility": "define the data model"},
        {"path": "test_models.py", "responsibility": "test the data model"},
    ]
    # Forced into separate groups so the naming-convention dependency edge
    # (test_models.py -> models.py) becomes a cross-group edge.
    groups = [["models.py"], ["test_models.py"]]

    class _TripwireClient:
        def chat_completion(self, *a, **k):
            raise AssertionError("real LLM call should not happen")

    client = _TripwireClient()
    router = Router(_models(), client)
    events = []

    artifact = parallel_generate.generate_parallel(
        "task", "python", manifest, groups, router, client, on_event=events.append
    )

    assert {"type": "generation_wave_completed", "wave": 0, "group_count": 1} in events
    assert {"type": "generation_wave_completed", "wave": 1, "group_count": 1} in events

    files_by_path = {f.path: f.content for f in artifact.files}
    # Wave 0 (models.py) has no dependency content yet.
    assert files_by_path["models.py"] == "no-deps"
    # Wave 1 (test_models.py) receives wave 0's real generated content,
    # not just the manifest's one-line description.
    assert files_by_path["test_models.py"] == json.dumps({"models.py": "no-deps"})
