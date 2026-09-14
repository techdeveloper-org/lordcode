# ADR-0009 — The MCP surface is kgf's own, not a Claude Code registration

**Status:** accepted · **Decider:** project owner

## Context

Everything kgf knows is reachable from two places: the `kgf` CLI and `vishwakarma`'s `run_task`.
Anything else must shell out and parse human-readable output. MCP already carries this workspace's
other capabilities, so exposing kgf over it makes the knowledge usable by anything.

The workspace convention is clear: 25 existing servers, each a top-level sibling repo with a vendored
`base/` package, a `sys.path.insert` of its own repo, and an entry in `~/.claude/settings.json`.

## Decision

**Depart from that convention deliberately.** Four servers ship **inside the package** at
`kgf/mcp/*_server.py`, with a kgf-owned registry, posture read from `~/.kgf/mcp.json`, and **nothing
registered with Claude Code**.

Split by concern: `kgf-graph`, `kgf-selection`, `kgf-context`, `kgf-tools` — **15 tools** total
(6 + 5 + 2 + 2), of which `kgf_tool_call` is the only non-read-only one.

## Consequences

**Why not the convention:** following it would import another repo's `base/` package — the horizontal
coupling [ADR-0002](0002-kgf-imports-nothing-from-vishwakarma.md) forbids — version-lock four repos to
kgf's internal types, and put kgf's capabilities behind another tool's configuration.

**Accepted cost:** these four will not appear in `~/.claude/settings.json` or any Claude-side listing,
and the workspace gains a second server convention. The registration *shape* is copied so the two look
alike.

**The split's price, measured both ways.** Four processes pay the cold graph build four times (~0.6s
per compose, see [ADR-0004](0004-no-disk-cache.md)) and share no session state, so `KnowledgeGraph`,
`Closure` and `AssembledContext` cannot cross as handles — every server re-derives from ids, and **the
compose is only as trustworthy as the ids handed back**. It buys context headroom in return: a caller
loads one server's 2–6 tool schemas rather than all 15.

**Security posture, graded rather than described.** A read-only compose uses `Read`, `Glob`, `Grep`
while the graph grants all eight tools, so the least-privilege score is **3/8 = 0.375** against a >0.8
target. The tools server therefore **fails that target by design**, and the mitigation is not the
grant — it is the sandbox root plus two opt-ins defaulting to `False`.

**The security claim had to be corrected, and it was mine.** "Launch-time flags mean an MCP client
cannot escalate itself" is **false**: in stdio MCP the client *spawns* the server and supplies its
environment outright. Reading posture from `KGF_MCP_*` env vars would have meant reading values the
launcher chose. Hence `~/.kgf/mcp.json`, and the honest scope: these flags bind **the model driving an
open session**, never the launcher. `kgf mcp config` therefore emits no flag names at all — printing
them would hand every reader the exact string that flips the posture.

**Determinism does not survive the process split** and had to be scoped: four stdio servers share no
run, so a compose produces no single manifest. Each tool returns its **fragment**, and `kgf replay`
merges them — refusing a set whose registry digests or correlation ids disagree.
