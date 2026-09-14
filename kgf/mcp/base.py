"""Shared plumbing for the four servers: SDK probe, annotations, graph access.

The tool-registration SHAPE is copied from this workspace's other 25 servers --
the `MCPServer`/`FastMCP` probe, `ToolAnnotations` on every tool, JSON text out,
`mcp.run(transport="stdio")` -- so the two conventions look alike to anyone
reading both. What is deliberately NOT copied is their vendored `base/` package:
importing another repository's framework is the cross-repo coupling ADR-2
exists to prevent, and this file is the forty lines that avoid it.

Every server loads the graph once per process and holds it. `cached_graph`
already memoises per process, so repeated tool calls in one session are free;
the cost is one cold build per server per spawn -- see `kgf.loader`'s module
docstring, which is the single place these figures live -- so a four-server
compose pays roughly four times that, on the order of 0.6s. That is Decision 1's
price, recorded rather than hidden.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# mcp 2.0 renamed FastMCP to MCPServer and moved it to mcp.server.mcpserver.
# Both names are probed so a server runs under either major version; the API
# used here (tool decorator, run(transport=...)) is identical in both.
try:  # pragma: no cover - exercised by whichever mcp version is installed
    from mcp.server.mcpserver import MCPServer
except ImportError:  # mcp < 2.0
    from mcp.server.fastmcp import FastMCP as MCPServer

try:  # pragma: no cover - older mcp lacks annotations
    from mcp.types import ToolAnnotations
except ImportError:  # pragma: no cover
    ToolAnnotations = None

from kgf.errors import LibraryNotFoundError
from kgf.loader import cached_graph
from kgf.mcp.settings import McpSettings, McpSettingsError, load_settings
from kgf.source import locate_library

READ_ONLY = dict(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
"""Every kgf tool except one. The graph is a file the server only ever reads."""

MUTATING = dict(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True)
"""`kgf_tool_call` alone.

destructiveHint is True because a granted `Write` or `Bash` genuinely changes
the filesystem, and openWorldHint is True because a granted `WebFetch` reaches
the internet. Declaring these honestly is the point: the MCP spec's per-hint
defaults all point at the more dangerous value, so an unannotated tool is
indistinguishable from an explicit worst case, and a host may auto-approve a
tool whose safety was never actually established.
"""


def annotations(**hints: bool):
    """Build ToolAnnotations, degrading to no annotations on older mcp."""
    if ToolAnnotations is None:  # pragma: no cover
        return None
    return ToolAnnotations(**hints)


def make_server(name: str, instructions: str) -> Any:
    """Construct one stdio MCP server."""
    return MCPServer(name, instructions=instructions)


class ServerContext:
    """One server's library, graph and posture, resolved once at startup.

    Resolved eagerly rather than per call so a missing library or an unusable
    settings file stops the server at LAUNCH. A server that starts and then
    fails every call looks like a working server with a broken graph, which is
    strictly harder to diagnose than one that refused to start and said why.
    """

    def __init__(self, settings_file: Path | None = None):
        self.settings: McpSettings = load_settings(settings_file)
        self.source = locate_library(self.settings.library_root)
        self.graph, self.log = cached_graph(
            str(self.settings.library_root) if self.settings.library_root else None
        )
        self._fingerprint: tuple | None = None

    @property
    def library_version(self) -> str:
        """The located library's release label."""
        return self.source.library_version

    def fingerprint(self) -> tuple:
        """Per-registry sha256, computed once and reused.

        Content rather than mtime, which is what makes the value comparable
        ACROSS the four processes of one compose and across machines -- mtimes
        would agree on one machine and be meaningless anywhere else.
        """
        if self._fingerprint is None:
            _version, digests = self.source.fingerprint()
            self._fingerprint = digests
        return self._fingerprint


def settings_from_argv(argv: list[str] | None = None) -> Path | None:
    """Read `--settings PATH` off the command line, or None for the default.

    Posture is refused from the environment and accepted from argv, and the
    difference is worth stating because it looks inconsistent and is not.

    Neither is a boundary against the launcher. In stdio MCP the client chooses
    the interpreter, the script and the environment, so a launcher can already
    put this process wherever it likes; pretending otherwise was the error the
    plan's first draft made. The property that actually holds is narrower and
    still useful: **the model driving an already-open session cannot change
    posture**, because argv is fixed before the first tool call and no tool
    accepts a posture argument.

    Given that, argv is the better channel of the two. It is explicit and never
    implicitly inherited, whereas an environment variable arrives invisibly and
    a single `KGF_MCP_ALLOW_BASH=1` in a spawn dict flips a control with nothing
    on disk to audit. `--settings` points at a FILE whose contents can be read
    after the fact.

    It also makes the property testable. A test must be able to spawn a real
    server with `allow_bash` on to prove the deny-by-default path is the
    default rather than the only behaviour, and a security control that cannot
    be exercised is a claim rather than a control.
    """
    import sys

    args = list(argv if argv is not None else sys.argv[1:])
    for index, item in enumerate(args):
        if item == "--settings" and index + 1 < len(args):
            return Path(args[index + 1])
        if item.startswith("--settings="):
            return Path(item.split("=", 1)[1])
    return None


def start(context_factory, server, settings_file: Path | None = None) -> None:
    """Resolve the context, then serve on stdio, or exit non-zero saying why.

    Exits rather than raising so the failure reaches a launcher as a process
    status it can act on, with the reason on stderr where a human will see it.
    """
    import sys

    try:
        context_factory(settings_file if settings_file is not None else settings_from_argv())
    except (LibraryNotFoundError, McpSettingsError) as exc:
        print(f"kgf mcp: cannot start: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    except Exception as exc:
        # A sandbox root that does not exist, or that contains the library,
        # raises from M4's own constructor check. It has to stop the server
        # here: a process that starts and then denies every filesystem call
        # looks like a working server with a broken graph.
        print(f"kgf mcp: cannot start: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    server.run(transport="stdio")
