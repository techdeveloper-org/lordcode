"""kgf's own MCP surface: four stdio servers over the knowledge graph.

ADR-9. These live inside the kgf package rather than as four sibling repos,
which is where this workspace's other 25 MCP servers live. The reason is
clean-architecture's Dependency Rule: these servers are ADAPTERS, and the
sibling-repo convention would have each one import another repository's
vendored `base/` package -- horizontal coupling between adapters rather than a
dependency pointing inward. ADR-2's one-way rule is a consequence of that
principle, not a separate preference.

Accepted cost, stated rather than discovered: these four do not appear in
`~/.claude/settings.json` or any Claude-side listing, and the workspace gains
a second server convention. That is the point -- kgf is its own tool with its
own settings, and nothing here routes through Claude Code.

Four servers, split by concern:

    kgf-graph      what the library says      (read-only)
    kgf-selection  what work should run       (read-only)
    kgf-context    what text to send          (read-only)
    kgf-tools      what may touch the disk    (the only mutating surface)

The split costs about 1.1s per compose, because each server is its own process
and pays its own graph build. It buys back context headroom on every call: a
caller loads one server's 4-6 tool schemas rather than all 17, and
ai-agents-core M5 prices a tool schema at 100-500 tokens.
"""

from kgf.mcp.settings import McpSettings, load_settings, settings_path

__all__ = ["McpSettings", "load_settings", "settings_path", "server_path", "SERVERS"]

SERVERS = ("kgf-graph", "kgf-selection", "kgf-context", "kgf-tools")
"""The four server names, in the order the concerns compose."""

_MODULES = {
    "kgf-graph": "graph_server.py",
    "kgf-selection": "selection_server.py",
    "kgf-context": "context_server.py",
    "kgf-tools": "tools_server.py",
}


def server_path(name: str):
    """Absolute path to one server's stdio entry point.

    Resolved from the INSTALLED package location rather than relative to a
    workspace root, so the registry survives an install outside this
    repository -- which vishwakarma's own `mcp_client.MCP_SERVERS` does not,
    since it resolves its six siblings from `_WORKSPACE_ROOT`.

    Raises:
        KeyError: naming the four valid servers, since a typo here otherwise
            surfaces as a missing file much later.
    """
    from pathlib import Path

    if name not in _MODULES:
        raise KeyError(f"unknown server {name!r}; known: {', '.join(SERVERS)}")
    return Path(__file__).resolve().parent / _MODULES[name]
