# ADR-0001 — Build the ranker fresh from JSON rather than vendoring `selection/`

**Status:** accepted · **Decider:** project owner, re-affirmed on corrected facts

## Context

`claude-workflow-engine` contains a `selection/` package — about 2,459 lines — that already implements
BM25 ranking, edge-gated candidacy, four selection outcomes and a better id normaliser than anything
kgf had. Its measured top-1 domain accuracy on an 8-task sample was **4/8**, against the then-wired
`kg_router`'s **0/8**.

A reviewer recommended vendoring it. Reusing 2,459 tested lines instead of rewriting them is the
obvious call on effort alone.

## Decision

Build fresh. `kgf` derives its own BM25-class ranker and harness from the library JSON.

## Consequences

**Accepted cost, stated plainly:** we re-derive a ranker and its evaluation harness that already
existed and worked. That is real duplicated effort and a real risk of being worse.

**Mitigation — adopt the two load-bearing *ideas* without the code:**

- **edge-gated candidacy**: an agent no edge names is never a candidate;
- **refusing to promise an accuracy figure retrieval cannot honour** — its 4/8 is the bar to beat, and
  no number above it was promised in advance.

**What the reuse would have cost, and why it decided the question:** vendoring means importing another
repository's package, which is exactly the cross-repo coupling [ADR-0002](0002-kgf-imports-nothing-from-vishwakarma.md)
exists to forbid. `selection/` reaches `loguru` through `..core.get_logger` and pulls a 446-line
`..library.resolver`, so "vendor just the ranker" was never available — the parent package initialises
either way.

**A correction worth keeping:** an early claim that `ids.py`'s type-word hazard would bite us was
wrong. It bites only when *stripping* a prefix; kgf *prepends*, so all 12 type-word names resolve.
