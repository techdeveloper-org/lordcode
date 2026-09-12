"""Unit tests for the Git Integration milestone's git_ops.py.

Mocks git_ops.call_mcp_tool (monkeypatched at the git_ops module namespace,
same pattern as test_documentation.py's docs.call_mcp_tools patching) so no
real mcp-git-ops/mcp-github-api server process is ever spawned. ensure_git_repo
mocks subprocess.run since it never goes through MCP at all.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from vishwakarma.engine import git_ops
from vishwakarma.engine.generate import GenerationError
from vishwakarma.mcp_client import MCPToolResult


def _events() -> list[dict]:
    return []


# --- ensure_git_repo ------------------------------------------------------


def test_ensure_git_repo_runs_git_init_when_absent(tmp_path, monkeypatch):
    calls = []

    def fake_run(cmd, cwd, capture_output, text):
        calls.append((cmd, cwd))
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(git_ops.subprocess, "run", fake_run)
    events = _events()

    result = git_ops.ensure_git_repo(tmp_path, on_event=events.append)

    assert result is True
    assert calls == [(["git", "init"], str(tmp_path))]
    assert events == [{"type": "git_repo_initialized"}]


def test_ensure_git_repo_skips_when_already_present(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    called = []
    monkeypatch.setattr(git_ops.subprocess, "run", lambda *a, **k: called.append(1))
    events = _events()

    result = git_ops.ensure_git_repo(tmp_path, on_event=events.append)

    assert result is False
    assert called == []
    assert events == [{"type": "git_repo_already_exists"}]


def test_ensure_git_repo_raises_on_nonzero_exit(tmp_path, monkeypatch):
    def fake_run(cmd, cwd, capture_output, text):
        return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="fatal: boom")

    monkeypatch.setattr(git_ops.subprocess, "run", fake_run)

    with pytest.raises(GenerationError, match="fatal: boom"):
        git_ops.ensure_git_repo(tmp_path)


# --- commit_generated_code -------------------------------------------------


def test_commit_generated_code_returns_commit_dict_on_success(tmp_path, monkeypatch):
    responses = [
        MCPToolResult(ok=True, data={"branch": "main"}),
        MCPToolResult(ok=True, data={"commit_hash": "abc1234", "files_committed": ["a.py"]}),
    ]
    call_log = []

    def fake_call_mcp_tool(server_script, tool_name, arguments):
        call_log.append(tool_name)
        return responses.pop(0)

    monkeypatch.setattr(git_ops, "call_mcp_tool", fake_call_mcp_tool)
    events = _events()

    result = git_ops.commit_generated_code(tmp_path, "msg", on_event=events.append)

    assert result == {"commit_hash": "abc1234", "files_committed": ["a.py"]}
    assert call_log == ["git_status", "git_commit"]
    assert {"type": "git_commit_created", "commit_hash": "abc1234", "files_committed": ["a.py"]} in events


def test_commit_generated_code_returns_none_on_no_changes(tmp_path, monkeypatch):
    responses = [
        MCPToolResult(ok=True, data={}),
        # Real server response includes repo_path alongside message -- not
        # just {"message": ...} -- per the live-discovered bug this fixture
        # reproduces exactly.
        MCPToolResult(ok=True, data={"repo_path": "/some/repo", "message": "No changes to commit"}),
    ]
    monkeypatch.setattr(git_ops, "call_mcp_tool", lambda *a: responses.pop(0))
    events = _events()

    result = git_ops.commit_generated_code(tmp_path, "msg", on_event=events.append)

    assert result is None
    assert {"type": "git_commit_skipped"} in events


def test_commit_generated_code_raises_when_git_status_fails_and_never_calls_git_commit(tmp_path, monkeypatch):
    call_log = []

    def fake_call_mcp_tool(server_script, tool_name, arguments):
        call_log.append(tool_name)
        return MCPToolResult(ok=False, error="not a repo")

    monkeypatch.setattr(git_ops, "call_mcp_tool", fake_call_mcp_tool)

    with pytest.raises(GenerationError, match="git_status failed"):
        git_ops.commit_generated_code(tmp_path, "msg")

    assert call_log == ["git_status"]


def test_commit_generated_code_raises_when_git_commit_fails_for_real_reason(tmp_path, monkeypatch):
    responses = [
        MCPToolResult(ok=True, data={}),
        MCPToolResult(ok=False, error="Please tell me who you are"),
    ]
    monkeypatch.setattr(git_ops, "call_mcp_tool", lambda *a: responses.pop(0))

    with pytest.raises(GenerationError, match="Please tell me who you are"):
        git_ops.commit_generated_code(tmp_path, "msg")


# --- has_github_remote ------------------------------------------------------


def test_has_github_remote_true(tmp_path, monkeypatch):
    monkeypatch.setattr(
        git_ops, "call_mcp_tool", lambda *a: MCPToolResult(ok=True, data={"is_github": True})
    )
    assert git_ops.has_github_remote(tmp_path) is True


def test_has_github_remote_false_when_not_github(tmp_path, monkeypatch):
    monkeypatch.setattr(
        git_ops, "call_mcp_tool", lambda *a: MCPToolResult(ok=True, data={"is_github": False})
    )
    assert git_ops.has_github_remote(tmp_path) is False


def test_has_github_remote_false_when_ok_false(tmp_path, monkeypatch):
    monkeypatch.setattr(git_ops, "call_mcp_tool", lambda *a: MCPToolResult(ok=False, error="no remote"))
    assert git_ops.has_github_remote(tmp_path) is False


# --- push_branch ------------------------------------------------------------


def test_push_branch_calls_branch_create_then_push_with_explicit_from_branch(tmp_path, monkeypatch):
    call_log = []

    def fake_call_mcp_tool(server_script, tool_name, arguments):
        call_log.append((tool_name, arguments))
        return MCPToolResult(ok=True, data={})

    monkeypatch.setattr(git_ops, "call_mcp_tool", fake_call_mcp_tool)
    events = _events()

    git_ops.push_branch(tmp_path, "feature-x", base="develop", on_event=events.append)

    assert call_log[0][0] == "git_branch_create"
    assert call_log[0][1]["from_branch"] == "develop"
    assert call_log[1][0] == "git_push"
    assert {"type": "git_branch_pushed", "branch": "feature-x"} in events


def test_push_branch_never_calls_git_push_when_branch_create_fails(tmp_path, monkeypatch):
    call_log = []

    def fake_call_mcp_tool(server_script, tool_name, arguments):
        call_log.append(tool_name)
        return MCPToolResult(ok=False, error="branch already exists")

    monkeypatch.setattr(git_ops, "call_mcp_tool", fake_call_mcp_tool)

    with pytest.raises(GenerationError, match="git_branch_create failed"):
        git_ops.push_branch(tmp_path, "feature-x")

    assert call_log == ["git_branch_create"]
    assert "git_push" not in call_log


def test_push_branch_raises_naming_branch_as_created_when_push_fails(tmp_path, monkeypatch):
    responses = [
        MCPToolResult(ok=True, data={}),
        MCPToolResult(ok=False, error="network timeout"),
    ]
    monkeypatch.setattr(git_ops, "call_mcp_tool", lambda *a: responses.pop(0))

    with pytest.raises(GenerationError, match="created locally but push failed"):
        git_ops.push_branch(tmp_path, "feature-x")


# --- create_pr ---------------------------------------------------------------


def test_create_pr_raises_on_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(git_ops, "call_mcp_tool", lambda *a: MCPToolResult(ok=False, error="422"))
    with pytest.raises(GenerationError, match="already pushed"):
        git_ops.create_pr(tmp_path, "feature-x", "Title", "Body")


def test_create_pr_returns_data_on_success(tmp_path, monkeypatch):
    monkeypatch.setattr(
        git_ops,
        "call_mcp_tool",
        lambda *a: MCPToolResult(ok=True, data={"pr_number": 5, "pr_url": "https://example/5"}),
    )
    result = git_ops.create_pr(tmp_path, "feature-x", "Title", "Body")
    assert result == {"pr_number": 5, "pr_url": "https://example/5"}


# --- push_and_create_pr -------------------------------------------------------


def test_push_and_create_pr_composes_all_three_steps(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        git_ops,
        "commit_generated_code",
        lambda *a, **k: calls.append("commit") or None,
    )
    monkeypatch.setattr(
        git_ops,
        "push_branch",
        lambda *a, **k: calls.append("push"),
    )
    monkeypatch.setattr(
        git_ops,
        "create_pr",
        lambda *a, **k: calls.append("pr") or {"pr_number": 1, "pr_url": "u"},
    )
    events = _events()

    result = git_ops.push_and_create_pr(tmp_path, "feature-x", "Title", "Body", on_event=events.append)

    assert calls == ["commit", "push", "pr"]
    assert result == {"pr_number": 1, "pr_url": "u"}
    assert {"type": "pr_created", "pr_number": 1, "pr_url": "u"} in events


def test_push_and_create_pr_stops_if_push_branch_fails(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(git_ops, "commit_generated_code", lambda *a, **k: calls.append("commit") or None)

    def failing_push(*a, **k):
        calls.append("push")
        raise GenerationError("push failed")

    monkeypatch.setattr(git_ops, "push_branch", failing_push)
    monkeypatch.setattr(git_ops, "create_pr", lambda *a, **k: calls.append("pr"))

    with pytest.raises(GenerationError, match="push failed"):
        git_ops.push_and_create_pr(tmp_path, "feature-x", "Title", "Body")

    assert calls == ["commit", "push"]


# --- absolute-path discipline --------------------------------------------


def test_all_repo_paths_and_cwd_are_absolute(tmp_path, monkeypatch):
    relative_workdir = tmp_path
    subprocess_calls = []
    mcp_calls = []

    def fake_run(cmd, cwd, capture_output, text):
        subprocess_calls.append(cwd)
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    def fake_call_mcp_tool(server_script, tool_name, arguments):
        if "repo_path" in arguments:
            mcp_calls.append(arguments["repo_path"])
        return MCPToolResult(ok=True, data={"message": "No changes to commit"} if tool_name == "git_commit" else {})

    monkeypatch.setattr(git_ops.subprocess, "run", fake_run)
    monkeypatch.setattr(git_ops, "call_mcp_tool", fake_call_mcp_tool)

    git_ops.ensure_git_repo(relative_workdir)
    git_ops.commit_generated_code(relative_workdir, "msg")
    git_ops.has_github_remote(relative_workdir)

    for cwd in subprocess_calls:
        assert Path(cwd).is_absolute()
    for repo_path in mcp_calls:
        assert Path(repo_path).is_absolute()
