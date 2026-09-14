# ADR-0005 — The 44-phase topology is kgf's own authored data

**Status:** accepted · **Decider:** project owner, against a reviewer's recommendation to descope

## Context

The pipeline runs work as a DAG of phases. The obvious source is `claude-global-library`, which ships
`phases.json` and `patterns.json` and describes a 44-phase SDLC.

Measured, those files cannot supply a DAG. `patterns.json` has five keys per record; `phases.json` has
three. There is **no** `depends_on`, `steps`, `order`, `inputs` or `outputs` anywhere, and no join
between the two. A reviewer's conclusion — descope the DAG — followed directly.

## Decision

**kgf invents this graph, owns it, and maintains it against a library that does not model it.**
All 44 phases are hand-authored in `kgf/topology.py`, each node carrying
`provenance: traversal.md#6.3 | authored: kgf` and a rationale.

## Consequences

**Accepted cost, and it is the whole of the objection:** kgf now owns data the library does not, so a
library change can silently invalidate it. Mitigated by a topology test asserting every phase id still
exists in `phases.json` on each library bump — the pin fails loudly rather than drifting.

**Honest provenance split, because "seeded from the library" would overstate it.** Only **16 of 44**
nodes get their placement from the library — 13 from `traversal.md` §6.3's verified chain, 3 from a
title. **28 of 44 are kgf's judgement.**

**Two corrections the authoring produced:**

- **`phase:F` does not exist.** `phases.json` has `F.1`–`F.6` and no bare `F`, so §6.3's chain maps
  `F → F.1..F.6` explicitly. Without that the topology test fails 12/13 on day one.
- **Pruning by removal is wrong.** Dropping phases for a simpler run left `phase:B` with no
  main-pipeline dependency, floated a security audit to level 0 *before implementation*, and stranded
  a phase at level 11 with its own dependents above it — because the DAG correctly ignores an edge
  whose endpoint is gone. **A prune must splice transitively.**

**A related correction to the library's own model:** `patterns.json` records only `id`, `title`,
`lead_agent`, `lead_domain` and `lead_math`. There is no `phases` field on any of the 105 patterns, so
a pattern does not carry a phase set — the phase set is the union of the chosen branches' emissions.
