# ADR-0004 — No disk cache for the knowledge graph

**Status:** accepted · **Cited in `kgf/loader.py`**, and defended by a test

## Context

Every run loads five master registries and builds a graph of 528 agents, 1,034 skills, 104 domains,
368 regulations and 9,146 edges. That sounds expensive, and the reflex is to cache it to disk.

An early draft measured the load at ~35 seconds and specified a full cache subsystem around that
figure.

## Decision

**No disk cache.** A process-level `lru_cache` on `load_graph()` is the whole of it.

## Consequences

**The 35s figure was wrong** — a cold-OS-cache artefact. Re-measured, and these are the numbers the
loader's module docstring now carries as the single canonical source:

| | warm |
|---|---|
| full load | **~76ms** (~31ms json parsing + ~45ms building) |
| cold process | ~152ms (~64ms import + ~88ms first build) |

Against a 300ms budget that is roughly 4x headroom, so a cache would add an invalidation failure class
to solve a problem that does not exist.

**The proposed cache key would not have worked either.** It was `kg_version`, which is `"1.0.0"` in
every registry and never moves — it is the *schema* version, correctly frozen. The field that actually
moves is `library_version`, and even that is a release label rather than a content key: an unreleased
local edit would silently reuse stale data. The library's own discovery index uses sha256-per-source,
which is the precedent kgf follows for its manifests.

**Accepted cost:** the MCP surface pays the cold build **per server per spawn**, because four stdio
servers share no process. That is roughly 0.6s for a four-server compose — recorded rather than fixed,
and the reason [ADR-0009](0009-mcp-surface-is-kgfs-own.md) prices its split honestly.

**This decision is the one thing a test defends directly.** `test_warm_load_is_within_budget` asserts
the warm floor stays under 300ms. It went red three times under load before being rewritten to assert
on the minimum of five samples — contention can only make a sample slower, so the minimum estimates
the uncontended cost. The budget is a **portability floor for unknown client hardware**, not a
regression guard: the worst observed min-of-5 was 128ms, so real headroom is ~2.3x.
