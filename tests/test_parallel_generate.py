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


def _fake_persona_generate_subset(remote_llm, task, language, manifest, file_paths, context, skill, subagent):
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


def _duplicate_persona(remote_llm, task, language, manifest, file_paths, context, skill, subagent):
    # Both groups claim to have produced "a.py", regardless of which file_paths they were assigned.
    return json.dumps({"files": [{"path": "a.py", "content": "x"}]})


def test_generate_parallel_raises_on_duplicate_path(tmp_path, monkeypatch):
    monkeypatch.setattr(parallel_generate, "_persona_generate_subset", _duplicate_persona)

    manifest = [{"path": "a.py", "responsibility": "x"}, {"path": "b.py", "responsibility": "y"}]
    groups = [["a.py"], ["b.py"]]

    class _TripwireClient:
        def chat_completion(self, *a, **k):
            raise AssertionError("real LLM call should not happen")

    client = _TripwireClient()
    router = Router(_models(), client)

    with pytest.raises(GenerationError, match="Duplicate file path 'a.py'"):
        parallel_generate.generate_parallel("task", "python", manifest, groups, router, client)
