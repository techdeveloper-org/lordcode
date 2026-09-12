"""Git Integration milestone: local commit is the always-on core deliverable;
pushing a branch and opening a PR is opt-in and only attempted when the
workdir already has a configured GitHub remote -- Vishwakarma cannot
provision one itself (neither mcp-git-ops nor mcp-github-api exposes a
repo-creation tool), so it never tries.

Neither MCP server exposes a `git init` tool -- every tool assumes an
existing repo -- so ensure_git_repo() runs plain `git init` directly via
subprocess, not through either server.

commit_generated_code() and push_branch() each call mcp_client.call_mcp_tool
(the singular wrapper) twice in sequence with an explicit ok-check between
the two calls, rather than mcp_client.call_mcp_tools()'s batch form: that
batch form has no stop-on-first-failure (correct for documentation.py's
independent per-diagram calls, wrong for this module's sequentially
dependent pairs -- a failed git_branch_create must never be followed by an
unconditional git_push against the same branch name).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from vishwakarma.engine.calling import OnEvent, noop_event
from vishwakarma.engine.generate import GenerationError
from vishwakarma.mcp_client import MCP_SERVERS, call_mcp_tool

_NO_CHANGES_MESSAGE = "No changes to commit"


def ensure_git_repo(workdir: Path, on_event: OnEvent = noop_event) -> bool:
    """Initialize a git repo in workdir if one doesn't already exist.

    Returns:
        True if a fresh repo was initialized, False if one already existed.

    Raises:
        GenerationError: If `git init` itself fails (a real, actionable
            problem -- git is not an MCP server, so there is no fail-open
            convention here).
    """
    if (workdir / ".git").exists():
        on_event({"type": "git_repo_already_exists"})
        return False

    result = subprocess.run(
        ["git", "init"], cwd=str(workdir), capture_output=True, text=True
    )
    if result.returncode != 0:
        raise GenerationError(f"git init failed in {workdir}: {result.stderr.strip()}")

    on_event({"type": "git_repo_initialized"})
    return True


def commit_generated_code(
    workdir: Path, message: str, on_event: OnEvent = noop_event
) -> dict | None:
    """Stage and commit everything in workdir.

    Returns:
        The commit result dict (commit_hash, files_committed, ...) on a
        real commit, or None if there was nothing to commit.

    Raises:
        GenerationError: If git_status reports the repo is missing/invalid
            (should not happen if ensure_git_repo ran first), or if
            git_commit itself fails for a real reason.
    """
    abs_path = str(workdir.resolve())
    git_ops_server = MCP_SERVERS["git-ops"]

    status_result = call_mcp_tool(git_ops_server, "git_status", {"repo_path": abs_path})
    if not status_result.ok:
        raise GenerationError(f"git_status failed for {abs_path}: {status_result.error}")

    commit_result = call_mcp_tool(
        git_ops_server, "git_commit", {"message": message, "repo_path": abs_path}
    )
    if not commit_result.ok:
        raise GenerationError(f"git_commit failed for {abs_path}: {commit_result.error}")

    # Live-discovered: the real no-op response is {"repo_path": ..., "message":
    # "No changes to commit"}, not just {"message": ...} -- an exact-dict-equality
    # check against the smaller shape never matches. Distinguish the no-op case
    # by the presence of "message" and the absence of "commit_hash" instead.
    if commit_result.data.get("message") == _NO_CHANGES_MESSAGE and "commit_hash" not in commit_result.data:
        on_event({"type": "git_commit_skipped"})
        return None

    on_event({"type": "git_commit_created", **commit_result.data})
    return commit_result.data


def has_github_remote(workdir: Path) -> bool:
    """Check whether workdir's git remote origin points at GitHub."""
    result = call_mcp_tool(
        MCP_SERVERS["git-ops"], "git_get_origin_url", {"repo_path": str(workdir.resolve())}
    )
    return result.ok and bool(result.data.get("is_github", False))


def push_branch(
    workdir: Path,
    branch_name: str,
    base: str = "main",
    on_event: OnEvent = noop_event,
) -> None:
    """Create a local branch off base and push it to the remote.

    Raises:
        GenerationError: If git_branch_create fails (git_push is never
            attempted in that case), or if git_branch_create succeeds but
            git_push fails -- the local branch is left in place, not
            cleaned up, and the error says so.
    """
    abs_path = str(workdir.resolve())
    git_ops_server = MCP_SERVERS["git-ops"]

    branch_result = call_mcp_tool(
        git_ops_server,
        "git_branch_create",
        {"name": branch_name, "from_branch": base, "repo_path": abs_path},
    )
    if not branch_result.ok:
        raise GenerationError(
            f"git_branch_create failed for branch '{branch_name}' in {abs_path}: {branch_result.error}"
        )

    push_result = call_mcp_tool(
        git_ops_server, "git_push", {"branch": branch_name, "repo_path": abs_path}
    )
    if not push_result.ok:
        raise GenerationError(
            f"branch '{branch_name}' created locally but push failed: {push_result.error} "
            "-- inspect/retry manually"
        )

    on_event({"type": "git_branch_pushed", "branch": branch_name})


def create_pr(
    workdir: Path,
    branch_name: str,
    pr_title: str,
    pr_body: str,
    base: str = "main",
) -> dict:
    """Open a PR for an already-pushed branch.

    Raises:
        GenerationError: If github_create_pr fails. The branch is already
            pushed and safe to retry/inspect manually -- this function never
            re-attempts the push.
    """
    abs_path = str(workdir.resolve())
    result = call_mcp_tool(
        MCP_SERVERS["github-api"],
        "github_create_pr",
        {
            "title": pr_title,
            "body": pr_body,
            "head": branch_name,
            "base": base,
            "repo_path": abs_path,
        },
    )
    if not result.ok:
        raise GenerationError(
            f"branch '{branch_name}' was already pushed, but PR creation failed: {result.error} "
            "-- the branch is safe to retry/inspect manually"
        )
    return result.data


def push_and_create_pr(
    workdir: Path,
    branch_name: str,
    pr_title: str,
    pr_body: str,
    base: str = "main",
    on_event: OnEvent = noop_event,
) -> dict:
    """Commit any pending changes, push a branch, and open a PR.

    Composes commit_generated_code -> push_branch -> create_pr; any step's
    GenerationError propagates as-is (each already states what partial
    state was left behind).
    """
    commit_generated_code(workdir, f"Generated by Vishwakarma ({branch_name})", on_event)
    push_branch(workdir, branch_name, base, on_event)
    pr_data = create_pr(workdir, branch_name, pr_title, pr_body, base)
    on_event({"type": "pr_created", **pr_data})
    return pr_data
