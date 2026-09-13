"""kgf-tools: what a persona may touch, and the one place that touches it.

`kgf_tool_call` is the only non-read-only tool in the entire kgf MCP surface,
which is exactly the boundary worth being able to see from a tool listing.

Read the security position plainly, because the prose version of it reads like
reassurance and the numbers do not. cloud-security-core's least-privilege score
is `|used| / |granted|`: a read-only compose uses Read, Glob and Grep, while
the graph grants a typical agent all eight tools. **0.375 against a >0.8
target.** So this server fails least-privilege by design, and the mitigation is
NOT the grant -- it is the sandbox root plus two opt-ins that default to False,
which is microsegmentation: the compromise radius is one confined directory
rather than the machine.

Posture is launch-time, from `~/.kgf/mcp.json`, and no tool here accepts
`allow_bash`, `allow_network` or a sandbox root as an argument. If they were
arguments, M4's denial reason -- "granted by the graph, but Bash requires
explicit opt-in" -- would be escalation instructions for the model reading it.

And the honest limit of that: these flags are not a boundary against whoever
LAUNCHES the server, because in stdio MCP the client spawns the process and
chooses its environment. They bound the model driving an already-open session,
which is the untrusted party in the loop.
"""

from __future__ import annotations

from pathlib import Path

from kgf.closure import build_closure
from kgf.mcp.base import MUTATING, READ_ONLY, ServerContext, annotations, make_server, start
from kgf.mcp.responses import envelope, tool_handler
from kgf.tools import Sandbox, SandboxConfigError, SandboxViolation, ToolRuntime, grant_for

mcp = make_server(
    "kgf-tools",
    instructions=(
        "Derive an agent's effective tool grant from the graph, and run a granted tool "
        "inside a sandbox. The only mutating surface in kgf's MCP servers; Bash and "
        "network access are off unless enabled in ~/.kgf/mcp.json."
    ),
)

_context: ServerContext | None = None
_runtimes: dict[str, ToolRuntime] = {}


def _ctx() -> ServerContext:
    """The process's resolved context, built at launch by start()."""
    global _context
    if _context is None:
        _context = ServerContext()
    return _context


def _build(settings_file: Path | None = None) -> ServerContext:
    """Resolve the context AND the sandbox before serving.

    The sandbox is constructed here, at launch, so a root that does not exist
    or that contains the library refuses the SERVER rather than the first call.
    A server that starts and then denies everything looks like a working server
    with a broken graph.
    """
    global _context, _runtimes
    _context = ServerContext(settings_file)
    _runtimes = {}
    if _context.settings.sandbox_root is not None:
        _sandbox_for(_context)
    return _context


def _sandbox_for(context: ServerContext) -> Sandbox:
    """Build the one Sandbox this process uses, from the settings file only.

    Raises:
        SandboxConfigError: if no sandbox root is configured, or the configured
            one is unusable. M4's own constructor check is what refuses a root
            that contains the library -- reused rather than re-implemented, so
            the MCP surface cannot be laxer than the in-process runtime.
    """
    settings = context.settings
    if settings.sandbox_root is None:
        raise SandboxConfigError(
            "no sandbox_root in ~/.kgf/mcp.json, so filesystem tools cannot run. "
            "Set it to an absolute scratch directory that does not contain the library."
        )
    return Sandbox(
        root=settings.sandbox_root,
        allow_bash=settings.allow_bash,
        allow_network=settings.allow_network,
        library_root=context.source.root,
    )


def _runtime_for(agent: str) -> ToolRuntime:
    """The ToolRuntime for one agent, built once per process per agent."""
    context = _ctx()
    if agent not in _runtimes:
        closure = build_closure(context.graph, agent)
        if closure is None:
            raise KeyError(f"no agent matching {agent!r}")
        grant = grant_for(context.graph, agent, closure=closure)
        if grant is None:
            raise KeyError(f"no grant derivable for {agent!r}")
        _runtimes[agent] = ToolRuntime(grant, _sandbox_for(context))
    return _runtimes[agent]


@mcp.tool(annotations=annotations(**READ_ONLY))
@tool_handler
def kgf_grant(agent: str, correlation_id: str = "") -> dict:
    """Derive one agent's effective tool grant, and say how it was derived.

    The ceiling is the agent's own declared tools; the closure's skills'
    `allowed_tools` are UNIONED and intersected with that ceiling; every
    HAS_TOOL_ACCESS tier is intersected on top. Defects are returned rather
    than swallowed -- 18 of 94 tier edges grant beyond their agent's ceiling
    and are clamped, which is a real cost this reports rather than hides.
    """
    context = _ctx()
    closure = build_closure(context.graph, agent)
    if closure is None:
        raise KeyError(f"no agent matching {agent!r}")
    grant = grant_for(context.graph, agent, closure=closure)
    if grant is None:
        raise KeyError(f"no grant derivable for {agent!r}")

    settings = context.settings
    return envelope(
        "kgf_grant",
        {
            "agent": grant.agent,
            "tools": grant.sorted_tools(),
            "ceiling": sorted(grant.ceiling),
            "tiers": list(grant.tiers),
            "narrowed_by": list(grant.narrowed_by),
            "defects": list(grant.defects),
            "posture": {
                "sandbox_configured": settings.has_sandbox,
                "allow_bash": settings.allow_bash,
                "allow_network": settings.allow_network,
            },
        },
        library_version=context.library_version,
        fingerprint=context.fingerprint(),
        correlation_id=correlation_id,
    )


@mcp.tool(annotations=annotations(**MUTATING))
@tool_handler
def kgf_tool_call(
    agent: str,
    tool: str,
    arguments: dict | None = None,
    correlation_id: str = "",
) -> dict:
    """Run one granted tool as one agent, inside the configured sandbox.

    Args:
        agent: The principal. Its graph-derived grant decides what may run.
        tool: Read | Write | Edit | Glob | Grep | Bash | WebFetch | WebSearch.
        arguments: The tool's own arguments. **`allow_bash`, `allow_network`
            and any sandbox root are rejected here** -- posture comes from
            `~/.kgf/mcp.json` and a call cannot raise its own privileges.
        correlation_id: Ties this call's logs to one compose.

    A DENIAL IS A SUCCESSFUL RESPONSE carrying `decision: denied` and a reason,
    not an error: a persona that asked for something it may not have should read
    that and choose differently, and raising would turn a recoverable
    permission answer into a failed run. A SANDBOX VIOLATION does fail -- that
    is not a permission question but an attempt to leave the workdir, and
    returning it softly would let a retry loop keep probing.
    """
    payload = dict(arguments or {})
    forbidden = sorted({"allow_bash", "allow_network", "sandbox_root", "root", "library_root"} & payload.keys())
    if forbidden:
        raise ValueError(
            f"{', '.join(forbidden)} cannot be set per call: posture is read from "
            "~/.kgf/mcp.json at launch. A call that could raise its own privileges "
            "would make every denial reason a set of escalation instructions."
        )

    runtime = _runtime_for(agent)
    context = _ctx()

    dispatch = {
        "Read": lambda: runtime.read(payload["path"]),
        "Write": lambda: runtime.write(payload["path"], payload.get("content", "")),
        "Edit": lambda: runtime.edit(payload["path"], payload["old"], payload["new"]),
        "Glob": lambda: runtime.glob(payload["pattern"]),
        "Grep": lambda: runtime.grep(payload["pattern"], payload.get("path", "**/*")),
        "Bash": lambda: runtime.bash(payload["argv"], payload.get("timeout_seconds")),
        "WebFetch": lambda: runtime.web_fetch(payload["url"]),
        "WebSearch": lambda: runtime.web_search(payload["query"]),
    }
    if tool not in dispatch:
        raise KeyError(f"unknown tool {tool!r}; known: {', '.join(sorted(dispatch))}")

    try:
        result = dispatch[tool]()
    except SandboxViolation as exc:
        raise SandboxViolation(
            f"{tool} attempted to leave the sandbox: {exc}. This fails rather than "
            "returning a denial, because it is not a permission question."
        ) from exc

    return envelope(
        "kgf_tool_call",
        {
            "tool": result.tool,
            "decision": result.decision.value if hasattr(result.decision, "value") else result.decision,
            "reason": result.reason,
            "output": result.output,
            "error": result.error,
            "exit_code": result.exit_code,
        },
        library_version=context.library_version,
        fingerprint=context.fingerprint(),
        correlation_id=correlation_id,
    )


if __name__ == "__main__":
    start(_build, mcp)
