# ADR-0002 — `kgf` imports nothing from `vishwakarma`, and a test enforces it

**Status:** accepted · **Cited 11 times in code** — the most-referenced decision here

## Context

`kgf` is a knowledge-graph framework that lives in the same repository as `vishwakarma`, the tool that
consumes it. Same repo, same install, same test run. Nothing mechanical stops a `kgf` module importing
`vishwakarma.config` for a convenience, and once one does, `kgf` stops being a framework and becomes a
part of the application.

The repository already carried the counter-example: `engine/kg_routing.py` did a
`sys.path.insert` of an entirely separate repository to reach its selection code, and that coupling was
what made the routing half untestable and eventually deleted.

## Decision

`kgf` depends on `vishwakarma` in **no direction**. The dependency points one way only:
`vishwakarma` → `kgf`.

Enforced rather than intended: a test imports **every** `kgf` module in a subprocess with
`vishwakarma` absent from `sys.path`. Any import of the consumer fails the suite.

## Consequences

**Accepted cost:** genuinely shared helpers get written twice. The clearest instance is the MCP
error-wrapping decorator — about forty lines reimplemented in `kgf/mcp/responses.py` rather than
imported from a sibling repo's `base` package.

**The enforcement had to be fixed once, and the lesson generalises.** The boundary test was believed to
cover the whole package because it "imports every `kgf` module". Both halves were non-recursive —
`glob("*.py")` and `pkgutil.iter_modules`, neither of which descends into a subpackage — so all eight
`kgf/mcp` modules sat **outside** the check it was trusted for. Measured: 20 modules checked before the
fix, 28 after.

> *"A test already covers this" is a claim about a glob pattern, and globs do not recurse by default.*

**One deliberate exception**, narrow and named: `vishwakarma/mcp_client.py` may import `kgf.mcp` to
resolve server paths. It is on an allowlist rather than a general permission.
