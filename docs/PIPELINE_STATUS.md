# LordCode — Pipeline Status

Live execution tracker for the plan in [`orchestration_prompt.md`](orchestration_prompt.md).
Updated as each phase completes. This is the file to read to know where things stand.

**Last updated:** 2026-09-04
**Current phase:** Phase 0 COMPLETE
**Blocking on:** ** STOP 1 ** — user review of PRD.md + licence decision

---

## Breakpoint protocol — where execution STOPS for human review

Execution halts at every ⏸️ below and does not resume until you say so. No stop is
skipped, auto-approved, or inferred from silence. At each one you get: what was produced,
what decision is being asked of you, and what unblocks if you approve.

| # | Breakpoint | You review | You decide |
|---|---|---|---|
| **STOP 1** | After Phase 0 | `PRD.md`, `tech_scout_report.md` | Licence + governance; whether FR/NFR scope is right |
| **STOP 2** | Phase 1 — ADR resolution | ADR-1/3/4/5/7 proposals | Router topology, corpus storage form, credential mechanism, distribution, SDLC-engine shape |
| **STOP 3** | Phase 1 — HLD draft | `HLD.md` | Architecture accepted before the consensus gate runs |
| **STOP 4** | Phase 3 — design | `terminal_ux_spec.md` | Terminal UX and accessibility |
| **STOP 5** | Phase 5 — SRS | `SRS.md` + UML | Documentation baseline |
| **STOP 6** | Phase 6 — sprint | `sprint_verdict.json` | Sprint 1 contents, Jira vs local backlog |
| **STOP 7** | Phase 7 — routing | `implementation_execution_plan.json` | Per-story agent assignments before any code |
| **STOP 8** | Phase 8 — alignment | `ir5_alignment_verdict.json` | Final go-ahead into implementation |
| **STOP 9** | Phase G — release | Release artifacts | Publish or hold |

**Automated gates (no human input needed, but reported to you):** `consensus-agent` BINARY
APPROVED/REJECTED · Phase C `NLI = FactScore = 1.0` · Phase D `coverage = 100%, DRE = 1.0` ·
Phase H zero regressions · Phase F all severity counts = 0 · Phase E `RS = 1.0` ·
Ops.1 GO/NO-GO. A REJECT at any of these triggers the SC.1–SC.3 self-correction loop
(max 3 iterations) and then escalates to you rather than looping forever.

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
| P.4 | Repo pushed to remote | — | ✅ `master` on origin |

## Phase 0 — Requirements & R&D → PRD

| # | Item | Agent | Skills | Status |
|---|---|---|---|---|
| 0.1a | 48 FRs + 14 NFRs, all quote-traced; Given/When/Then ACs; RTM skeleton; DPDP FRs; capability-gap register | `business-analyst-agent` | 5 | ✅ |
| 0.1b | Positioning, Kano MVP cut, North Star metric, competitive read, README narrative, Apache-2.0 licence recommendation | `product-manager-agent` | 5 | ✅ |
| 0.2 | Provider auth terms verified, Go SDK parity, Node SEA, competitor scan | `technology-scout-analyst` | 4 | ✅ |
| — | merge PM sections into `PRD.md` | — | — | ✅ 806 lines, 0 placeholders |
| — | **STOP 1** — user reviews `PRD.md`, decides licence | *human* | — | ⏸️ **AWAITING YOU** |

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
