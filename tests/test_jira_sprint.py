"""Unit tests for the Sprint Planning milestone's jira_sprint.py.

Mocks jira_sprint.call_mcp_tool (monkeypatched at the module namespace, same
pattern as test_git_ops.py/test_figma_design.py) so no real mcp-jira-api
server process is ever spawned. The FR-extraction persona call runs through
a real AgentCoordinator/spawned process but with a FakeClient, same pattern
as tests/test_api_contract.py.
"""

from __future__ import annotations

import json

import pytest

from vishwakarma.config import ModelConfig, RoleCandidate
from vishwakarma.engine import jira_sprint
from vishwakarma.engine.generate import GenerationError
from vishwakarma.mcp_client import MCPToolResult
from vishwakarma.router import Router

VALID_SRS = """## 1. Purpose
Builds a todo app.

## 3. Requirements
### 3.1 Functional Requirements
FR-001: Add a todo item.
FR-002: List all todo items.
"""

_FR_JSON = json.dumps([
    {"id": "FR-001", "summary": "Add a todo item"},
    {"id": "FR-002", "summary": "List all todo items"},
])

_EXTRACTION_KEYWORD = "extracting a machine-readable list"


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
        roles={"fallback_long_context": [RoleCandidate(provider="groq", model="long-context")]},
        max_heal_attempts=3,
        heal_timeout_seconds=300,
    )


def _router(client) -> Router:
    return Router(_models(), client)


# --- has_jira_credentials / _jira_env ---------------------------------------


def test_has_jira_credentials_true_when_all_set(monkeypatch):
    monkeypatch.setenv("JIRA_URL", "https://x.atlassian.net")
    monkeypatch.setenv("JIRA_USER", "a@b.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "tok")
    assert jira_sprint.has_jira_credentials() is True


@pytest.mark.parametrize("missing", ["JIRA_URL", "JIRA_USER", "JIRA_API_TOKEN"])
def test_has_jira_credentials_false_when_any_missing(monkeypatch, missing):
    monkeypatch.setenv("JIRA_URL", "https://x.atlassian.net")
    monkeypatch.setenv("JIRA_USER", "a@b.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "tok")
    monkeypatch.delenv(missing, raising=False)
    assert jira_sprint.has_jira_credentials() is False


# --- _parse_functional_requirements -----------------------------------------


def test_parse_functional_requirements_accepts_unfenced_json():
    result = jira_sprint._parse_functional_requirements(_FR_JSON)
    assert result == [
        {"id": "FR-001", "summary": "Add a todo item"},
        {"id": "FR-002", "summary": "List all todo items"},
    ]


def test_parse_functional_requirements_accepts_fenced_json():
    fenced = f"```\n{_FR_JSON}\n```"
    assert jira_sprint._parse_functional_requirements(fenced) == json.loads(_FR_JSON)


def test_parse_functional_requirements_rejects_empty_list():
    with pytest.raises(GenerationError, match="valid JSON list"):
        jira_sprint._parse_functional_requirements("[]")


def test_parse_functional_requirements_rejects_malformed_json():
    with pytest.raises(GenerationError, match="valid JSON list"):
        jira_sprint._parse_functional_requirements("not json")


def test_parse_functional_requirements_rejects_missing_keys():
    with pytest.raises(GenerationError, match="valid JSON list"):
        jira_sprint._parse_functional_requirements('[{"id": "FR-001"}]')


# --- create_sprint_plan ------------------------------------------------------


def test_create_sprint_plan_happy_path_creates_epic_and_linked_stories(tmp_path, monkeypatch):
    client = FakeClient({_EXTRACTION_KEYWORD: _FR_JSON})
    router = _router(client)

    responses = [
        MCPToolResult(ok=True, data={"epic_key": "PROJ-1", "epic_url": "https://x/PROJ-1"}),
        MCPToolResult(ok=True, data={"issue_key": "PROJ-2"}),
        MCPToolResult(ok=True, data={"issue_key": "PROJ-2", "linked": True}),
        MCPToolResult(ok=True, data={"issue_key": "PROJ-3"}),
        MCPToolResult(ok=True, data={"issue_key": "PROJ-3", "linked": True}),
    ]
    call_log = []

    def fake_call_mcp_tool(server_script, tool_name, arguments, env=None):
        call_log.append((tool_name, arguments))
        return responses.pop(0)

    monkeypatch.setattr(jira_sprint, "call_mcp_tool", fake_call_mcp_tool)
    events = []

    state = jira_sprint.create_sprint_plan(
        VALID_SRS, tmp_path, "PROJ", router, client, on_event=events.append
    )

    assert state["epic"]["key"] == "PROJ-1"
    assert [s["issue_key"] for s in state["stories"]] == ["PROJ-2", "PROJ-3"]
    assert all(s["linked"] for s in state["stories"])

    written = json.loads(jira_sprint.jira_tickets_path_for(tmp_path).read_text(encoding="utf-8"))
    assert written == state

    assert call_log[0] == (
        "jira_create_epic",
        {
            "project_key": "PROJ",
            "name": "PROJ feature",
            "summary": "## 1. Purpose",
            "idempotency_key": "PROJ:epic",
        },
    )
    assert call_log[1][1]["idempotency_key"] == "PROJ:FR-001"
    assert call_log[3][1]["idempotency_key"] == "PROJ:FR-002"


def test_create_sprint_plan_stops_on_story_creation_failure_but_persists_partial_state(tmp_path, monkeypatch):
    client = FakeClient({_EXTRACTION_KEYWORD: _FR_JSON})
    router = _router(client)

    responses = [
        MCPToolResult(ok=True, data={"epic_key": "PROJ-1", "epic_url": "u"}),
        MCPToolResult(ok=True, data={"issue_key": "PROJ-2"}),
        MCPToolResult(ok=True, data={"issue_key": "PROJ-2", "linked": True}),
        MCPToolResult(ok=False, error="rate limited"),
    ]
    monkeypatch.setattr(jira_sprint, "call_mcp_tool", lambda *a, **k: responses.pop(0))

    with pytest.raises(GenerationError, match="rate limited"):
        jira_sprint.create_sprint_plan(VALID_SRS, tmp_path, "PROJ", router, client)

    written = json.loads(jira_sprint.jira_tickets_path_for(tmp_path).read_text(encoding="utf-8"))
    assert written["epic"]["key"] == "PROJ-1"
    assert [s["issue_key"] for s in written["stories"]] == ["PROJ-2"]


def test_create_sprint_plan_link_failure_is_non_fatal(tmp_path, monkeypatch):
    client = FakeClient({_EXTRACTION_KEYWORD: _FR_JSON})
    router = _router(client)

    responses = [
        MCPToolResult(ok=True, data={"epic_key": "PROJ-1", "epic_url": "u"}),
        MCPToolResult(ok=True, data={"issue_key": "PROJ-2"}),
        MCPToolResult(ok=False, error="link error"),  # link fails, non-fatal
        MCPToolResult(ok=True, data={"issue_key": "PROJ-3"}),
        MCPToolResult(ok=True, data={"issue_key": "PROJ-3", "linked": True}),
    ]
    monkeypatch.setattr(jira_sprint, "call_mcp_tool", lambda *a, **k: responses.pop(0))
    events = []

    state = jira_sprint.create_sprint_plan(VALID_SRS, tmp_path, "PROJ", router, client, on_event=events.append)

    assert state["stories"][0]["linked"] is False
    assert state["stories"][1]["linked"] is True
    assert any(e["type"] == "jira_epic_link_failed" and e["issue_key"] == "PROJ-2" for e in events)


def test_create_sprint_plan_with_sprint_uses_scrum_filter_and_board_id_field(tmp_path, monkeypatch):
    client = FakeClient({_EXTRACTION_KEYWORD: _FR_JSON})
    router = _router(client)

    responses = [
        MCPToolResult(ok=True, data={"epic_key": "PROJ-1", "epic_url": "u"}),
        MCPToolResult(ok=True, data={"issue_key": "PROJ-2"}),
        MCPToolResult(ok=True, data={"issue_key": "PROJ-2", "linked": True}),
        MCPToolResult(ok=True, data={"issue_key": "PROJ-3"}),
        MCPToolResult(ok=True, data={"issue_key": "PROJ-3", "linked": True}),
        MCPToolResult(ok=True, data={"boards": [{"board_id": 42, "board_type": "scrum"}]}),
        MCPToolResult(ok=True, data={"sprint_id": 7}),
        MCPToolResult(ok=True, data={"moved": True}),
    ]
    call_log = []

    def fake_call_mcp_tool(server_script, tool_name, arguments, env=None):
        call_log.append((tool_name, arguments))
        return responses.pop(0)

    monkeypatch.setattr(jira_sprint, "call_mcp_tool", fake_call_mcp_tool)

    state = jira_sprint.create_sprint_plan(
        VALID_SRS, tmp_path, "PROJ", router, client, create_sprint=True, sprint_name="Sprint 1"
    )

    boards_call = next(c for c in call_log if c[0] == "jira_get_boards")
    assert boards_call[1] == {"project_key": "PROJ", "board_type": "scrum"}

    sprint_call = next(c for c in call_log if c[0] == "jira_create_sprint")
    assert sprint_call[1]["board_id"] == 42
    assert sprint_call[1]["idempotency_key"] == "PROJ:sprint:Sprint 1"

    move_call = next(c for c in call_log if c[0] == "jira_move_issues_to_sprint")
    assert move_call[1] == {"sprint_id": 7, "issue_keys": "PROJ-2,PROJ-3"}

    assert state["sprint"] == {"sprint_id": 7, "name": "Sprint 1"}


def test_create_sprint_plan_passes_full_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("JIRA_URL", "https://x.atlassian.net")
    monkeypatch.setenv("JIRA_USER", "a@b.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "tok")

    client = FakeClient({_EXTRACTION_KEYWORD: _FR_JSON})
    router = _router(client)

    responses = [
        MCPToolResult(ok=True, data={"epic_key": "PROJ-1", "epic_url": "u"}),
        MCPToolResult(ok=True, data={"issue_key": "PROJ-2"}),
        MCPToolResult(ok=True, data={"issue_key": "PROJ-2", "linked": True}),
        MCPToolResult(ok=True, data={"issue_key": "PROJ-3"}),
        MCPToolResult(ok=True, data={"issue_key": "PROJ-3", "linked": True}),
    ]
    captured_envs = []

    def fake_call_mcp_tool(server_script, tool_name, arguments, env=None):
        captured_envs.append(env)
        return responses.pop(0)

    monkeypatch.setattr(jira_sprint, "call_mcp_tool", fake_call_mcp_tool)

    jira_sprint.create_sprint_plan(VALID_SRS, tmp_path, "PROJ", router, client)

    assert len(captured_envs) == 5
    for env in captured_envs:
        assert env["JIRA_URL"] == "https://x.atlassian.net"
        assert env["JIRA_USER"] == "a@b.com"
        assert env["JIRA_API_TOKEN"] == "tok"
