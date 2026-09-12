"""Milestone 3: a thin, fail-open client for the local stdio MCP servers this
workspace already runs (mcp-uml-diagram, mcp-drawio-diagram, mcp-jira-api,
mcp-figma, mcp-git-ops, ...) -- the first genuine `mcp`-SDK-based client in
this workspace (no ClientSession/stdio_client precedent existed anywhere
else to crib from).

`mcp` is a required dependency (see pyproject.toml) -- imported at module
top, not deferred -- so importing this module never itself fails on a
correctly installed environment. Fail-open behavior lives entirely inside
call_mcp_tools()'s try/except around the actual session/subprocess/tool-call
work, mirroring engine/kg_routing.py's fail-open convention for the
sibling claude-workflow-engine dependency: any error here (server missing,
ImportError inside the server process, timeout, malformed response) yields
a per-call MCPToolResult(ok=False, ...) rather than raising, so callers can
fall back to their own non-MCP path exactly as documentation.py already
falls back to LLM-generated diagrams when this returns ok=False.

One ClientSession is opened per call_mcp_tools() invocation and reused for
every (tool_name, arguments) pair in that call's batch -- spawning the
server process fresh per single tool call would pay a full cold interpreter
start + module re-import + MCP handshake for every call, which for a
same-server multi-call batch (e.g. documentation.py's class/component/
sequence sequence) dominates the actual tool-call cost.
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

_WORKSPACE_ROOT = Path(__file__).resolve().parents[2]

MCP_SERVERS: dict[str, Path] = {
    "uml-diagram": _WORKSPACE_ROOT / "mcp-uml-diagram" / "server.py",
    "drawio-diagram": _WORKSPACE_ROOT / "mcp-drawio-diagram" / "server.py",
    "git-ops": _WORKSPACE_ROOT / "mcp-git-ops" / "server.py",
    "github-api": _WORKSPACE_ROOT / "mcp-github-api" / "server.py",
    "figma": _WORKSPACE_ROOT / "mcp-figma" / "server.py",
    "jira": _WORKSPACE_ROOT / "mcp-jira-api" / "server.py",
}
"""Registry of known sibling MCP servers, resolved workspace-root-relative --
same sibling-detection convention as engine/kg_routing.py's
_ensure_workflow_engine_on_path() (mcp_client.py sits one directory
shallower than kg_routing.py, hence parents[2] here vs kg_routing.py's
parents[3] -- both resolve to the same workspace root)."""


@dataclass
class MCPToolResult:
    """One tool call's outcome: either its returned data, or a fail-open error."""

    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


def _extract_result_data(call_result: Any) -> dict[str, Any]:
    """Pull the tool's returned dict out of a CallToolResult.

    Prefers structuredContent (the MCP spec's typed-output field); falls
    back to parsing the first text content block as JSON for servers that
    only populate the legacy `content` field.
    """
    structured = getattr(call_result, "structuredContent", None)
    if structured:
        return dict(structured)

    for block in getattr(call_result, "content", None) or []:
        text = getattr(block, "text", None)
        if text:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"text": text}
    return {}


async def _call_mcp_tools_async(
    server_script: Path, calls: list[tuple[str, dict]], env: dict[str, str] | None = None
) -> list[MCPToolResult]:
    params = StdioServerParameters(command=sys.executable, args=[str(server_script)], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            results = []
            for tool_name, arguments in calls:
                call_result = await session.call_tool(tool_name, arguments)
                data = _extract_result_data(call_result)
                if call_result.isError:
                    results.append(MCPToolResult(ok=False, error=data.get("error") or str(data)))
                else:
                    results.append(MCPToolResult(ok=True, data=data))
            return results


def call_mcp_tools(
    server_script: Path, calls: list[tuple[str, dict]], env: dict[str, str] | None = None
) -> list[MCPToolResult]:
    """Call a sequence of tools on one server over a single session.

    Fail-open: any exception (server process failed to start, an
    ImportError inside the server for a missing dependency, a timeout, a
    malformed response) yields one MCPToolResult(ok=False, ...) per
    remaining/attempted call rather than propagating, so a caller can
    always safely fall back to its own non-MCP path.

    Args:
        server_script: Path to the target server's stdio entry point.
        calls: Ordered (tool_name, arguments) pairs to call over one session.
        env: Environment variables for the spawned server process. The
            underlying `mcp` SDK does NOT inherit the caller's full
            environment when this is omitted -- it uses a small, fixed
            allowlist (PATH, USERPROFILE, ...) that excludes any
            credential env var a server might need (e.g. FIGMA_ACCESS_TOKEN).
            Pass an explicit dict (commonly `{**os.environ}`) for any server
            that needs a credential from the caller's own environment.

    Returns:
        One MCPToolResult per entry in calls, same order. On a session-level
        failure (couldn't even start/initialize), every entry gets the same
        ok=False result.
    """
    if not server_script.is_file():
        error = f"MCP server script not found at {server_script}"
        return [MCPToolResult(ok=False, error=error) for _ in calls]

    try:
        return asyncio.run(_call_mcp_tools_async(server_script, calls, env=env))
    except Exception as exc:  # noqa: BLE001 -- any MCP/session/subprocess failure must fail open
        return [MCPToolResult(ok=False, error=str(exc)) for _ in calls]


def call_mcp_tool(
    server_script: Path, tool_name: str, arguments: dict, env: dict[str, str] | None = None
) -> MCPToolResult:
    """Convenience wrapper around call_mcp_tools() for a single tool call."""
    return call_mcp_tools(server_script, [(tool_name, arguments)], env=env)[0]
