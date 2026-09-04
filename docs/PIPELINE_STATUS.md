# LordCode — Pipeline Status

Live execution tracker for the plan in [`orchestration_prompt.md`](orchestration_prompt.md).
Updated as each phase completes. This is the file to read to know where things stand.

**Last updated:** 2026-09-04
**Current phase:** Phase 0 — BA/PM + R&D pre-processing
**Blocking on:** nothing — Phase 0 agents dispatched

---

## Legend

| Mark | Meaning |
|---|---|
| ✅ | Complete |
| 🔄 | In progress |
| ⏸️ | Waiting on a human stop |
| ⬜ | Not started |
| ⛔ | Blocked |

---

## Pre-work

| # | Item | Agent | Status |
|---|---|---|---|
| P.1 | Orchestration plan | `prompt-generation-expert` | ✅ `docs/orchestration_prompt.md` |
| P.2 | README / CHANGELOG / VERSION | — | ✅ committed `2e684a2` |
| P.3 | `.gitignore` | — | ✅ |
| P.4 | Repo pushed to remote | — | 🔄 |

## Phase 0 — Requirements & R&D → PRD

| # | Item | Agent | Skills | Status |
|---|---|---|---|---|
| 0.1a | FR/NFR entries + RTM skeleton + Given/When/Then ACs | `business-analyst-agent` | 5 | 🔄 |
| 0.1b | Positioning, MVP cut, North Star metric, README narrative, licence + governance recommendation | `product-manager-agent` | 5 | 🔄 |
| 0.2 | Provider auth terms (subscription vs API), Go SDK parity, competitor scan | `technology-scout-analyst` | 4 | 🔄 |
| — | **STOP 1** — user reviews `PRD.md`, decides licence | *human* | — | ⏸️ |

**Phase 0 outputs:** `docs/phase-0-requirements/PRD.md`, `docs/phase-0-requirements/tech_scout_report.md`

## Phase 1 — Solution Architecture → HLD + ADRs

| # | Item | Agent | Status |
|---|---|---|---|
| 1.a | Router topology recommendation (ADR-1 input) | `multi-model-router-architect` | ⬜ |
| 1.b | Provider catalogue + capability DNA | `genai-procurement-analyst` | ⬜ |
| 1.c | Cost model / CPST (router objective) | `llm-cost-optimizer` | ⬜ |
| 1.d | Benchmark methodology | `llm-benchmark-analyst` | ⬜ |
| 1.e | Harness control-loop design | `harness-engineering-architect` | ⬜ |
| 1.f | **HLD + ADR-1/3/4/5/7 resolution** | `solution-architect` | ⬜ |
| — | **3 stops:** ADR resolution, HLD review, consensus APPROVED | *human + gate* | ⬜ |

## Phase 1.5 → 8

| Phase | Deliverable | Status |
|---|---|---|
| 1.5 | `cli_contract.json` + `provider_adapter_contract.json` + `openapi.yaml` | ⬜ |
| 2 | Joint validation → `consensus_verdict.json` (BINARY) | ⬜ |
| 3 | `terminal_ux_spec.md` + `accessibility_report.json` | ⬜ |
| 4 | `grand_blueprint_verdict.json` | ⬜ |
| 5 | `SRS.md` + 13 UML + 13 draw.io | ⬜ |
| 6 | `sprint_verdict.json` (or `local_backlog.md`) | ⬜ |
| 7 | `implementation_execution_plan.json` — **STOP 7** | ⬜ |
| 8 | `ir5_alignment_verdict.json` — **STOP 8** | ⬜ |

## Execution — A.5 through Ops.5

| Phase | Deliverable | Status |
|---|---|---|
| A.5 | Context Delivery Plan (BLOCKING) | ⬜ |
| A.6 | `harness_control_policy.json` (BLOCKING) | ⬜ |
| B | Implementation B.1–B.9 — **first actual code** | ⬜ |
| C | Hallucination gate (NLI = FactScore = 1.0) | ⬜ |
| D | QA pipeline D.0–D.4 | ⬜ |
| H | Harness eval / regression (BINARY) | ⬜ |
| F | Security audit F.0–F.6 (FULL depth, CRITICAL) | ⬜ |
| E | Reliability gate (RS = 1.0) | ⬜ |
| G | Release | ⬜ |
| Ops.1–5 | Readiness, SLO, DR, bake, feedback | ⬜ |

---

## Open decisions

| ID | Decision | Owner | Status |
|---|---|---|---|
| ADR-1 | Router topology | Phase 1 | ⬜ |
| ADR-3 | Corpus storage form (constants vs compressed) | Phase 1 | ⬜ |
| ADR-4 | Credential storage + headless fallback | Phase 1, security veto | ⬜ |
| ADR-5 | Distribution channel | Phase 1 | ⬜ |
| ADR-7 | SDLC engine: hardcoded vs interpreted | Phase 1 | ⬜ |
| — | **Licence** | user, at Stop 1 (PM recommends) | ⬜ |

## Known risks

| Risk | Impact | Mitigation |
|---|---|---|
| Subscription ≠ API access | Breaks the headline "connect your account" promise | Phase 0.2 verifies; error-message FR written |
| Library lacks CLI/TUI, packaging, keychain agents | Three capability gaps for building LordCode itself | Ownership assigned in Phase 1 |
| Go SDK parity below assumption | Raises provider-adapter maintenance cost | Phase 0.2 verifies; does not flip ADR-2 |
| Open contributions + CRITICAL security | Supply-chain surface | Hardened PR path; F.2 gates on every external PR |
