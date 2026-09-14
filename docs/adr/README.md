# Architecture Decision Records

Source comments across `kgf/` and `vishwakarma/` justify their design by citing these records —
*"per ADR-2"*, *"ADR-4's no-cache decision"*, *"ADR-7's replay promise"*. Measured: **35 citations**
across seven ADRs. Until this directory existed they pointed at nothing a reader could open (#51).

Each record states the **accepted cost**, not only the choice. That is the part worth reading: several
of these were decided against a reviewer's recommendation, and a decision without its price is an
assertion rather than a record.

| ADR | Decision | Cited in code |
|---|---|---|
| [0001](0001-build-fresh-rather-than-vendor.md) | Build the ranker fresh from JSON rather than vendoring `selection/` | 1 |
| [0002](0002-kgf-imports-nothing-from-vishwakarma.md) | `kgf` imports nothing from `vishwakarma`, enforced by a subprocess test | 11 |
| [0003](0003-lexical-ranking-not-embeddings.md) | Lexical (BM25) ranking, no embeddings — scoped to *ranking* | — |
| [0004](0004-no-disk-cache.md) | No disk cache; a warm load is cheap enough | 2 |
| [0005](0005-kgf-authors-its-own-phase-topology.md) | The 44-phase DAG is kgf's own authored data | 6 |
| [0006](0006-role-is-not-derived-from-model.md) | Role is classified by kgf, never derived from the `model` field | 2 |
| [0007](0007-run-manifests-for-replay.md) | Run manifests give determinism and replay | 7 |
| [0008](0008-outbound-http-for-granted-tools-only.md) | Outbound HTTP for granted tools only, both sandbox flags default False | — |
| [0009](0009-mcp-surface-is-kgfs-own.md) | The MCP surface is kgf's own, not a Claude Code registration | 5 |

Decisions made while hardening the tool, which the code now depends on just as heavily:

| ADR | Decision |
|---|---|
| [0010](0010-rate-limits-are-not-candidate-failures.md) | A rate limit must not spend a role's candidate chain |
| [0011](0011-self-heal-keeps-the-best-attempt.md) | Self-heal keeps the best attempt, not the last |
| [0012](0012-absent-evidence-is-not-success.md) | Absent evidence is not success |

`rules/11-documentation-files.md` §6 exempts `docs/` from root-file governance, which is why these
live here rather than at the root.
