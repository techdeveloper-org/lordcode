# LordCode — Pipeline Status

Live execution tracker for the plan in [`orchestration_prompt.md`](orchestration_prompt.md).
Updated as each phase completes. This is the file to read to know where things stand.

**Last updated:** 2026-09-04
**Current phase:** Phase 1 (Solution Architecture) COMPLETE — HLD + GSD v1.0 produced
**Blocking on:** ** STOP 1 ** (licence decision, still open) and ** STOP 2 ** — user review of the ADR resolutions in `phase-1-architecture/HLD.md`

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

### Phase 0.3 — R&D gap-closure chain

Phase 0.2 self-flagged three findings it could not verify. Per the orchestration
prompt's STEP 0.05 task-routing table, systematic research routes through a
three-agent chain rather than a single scout, run **sequentially** (plan → retrieve
→ synthesize), never in parallel.

| # | Item | Agent | Skills | Status |
|---|---|---|---|---|
| 0.3a | Protocol: FINER framing, exact query strings, 3-search budget allocation, CRAAP thresholds, saturation rules | `research-strategist` | 3 | ✅ |
| 0.3b | Retrieval + CRAAP screening. Used 3/3 searches, ~17 free fetches | `deep-web-researcher` | 3 | ✅ |
| 0.3c | GRADE levels, gap taxonomy, contradiction report, decision brief | `research-synthesis-analyst` | 4 | ✅ |

**Gaps being closed** (all three self-flagged by `technology-scout-analyst`, not invented here):

| Gap | Why it matters | Prior state |
|---|---|---|
| OpenAI "Sign in with ChatGPT" OAuth | If open, materially better onboarding | **STILL OPEN** — GRADE VERY LOW. Docs silent by omission (Empirical gap) + one dead link (Reporting gap) |
| Google Gemini Go SDK | Sizes the Gemini adapter cost | **CLOSED** — all 3 features GRADE HIGH via godoc + dated CHANGELOG. Reverses the scout's "largest gap" |
| Prior art: pre-built specialist-agent corpus | LordCode's PRIMARY differentiator | **PARTIALLY OPEN** — GRADE VERY LOW (capped). 2 candidates resolved as community marketplaces; 2 stronger leads unfetchable (413/403) = Reporting gap |

### Phase 0.4 — R&D round 2 (targeted lead retrieval)

Round 1's meta-finding was that "unverified" meant *wrong URL tried*, not
*unfavourable fact*. Round 2 therefore used fetch-path engineering (GitHub REST
API, raw file hosting, registry JSON, sub-path targeting) rather than searching.

| # | Item | Agent | Status |
|---|---|---|---|
| 0.4a | Targeted retrieval: 3/3 searches, ~40 free fetches incl. shipped-source drill-down | `deep-web-researcher` | ✅ |
| 0.4b | GRADE + gap taxonomy + duplicate-candidate correction | `research-synthesis-analyst` | ✅ |

| Item | Round 2 outcome |
|---|---|
| Q3 prior art | **Upgraded VERY LOW → LOW** (within the protocol cap, not beyond). Both Reporting gaps closed. **Correction: the apparent 4 candidates are really 3** — AgentsRoom's "270 agents" is a fork of an already-counted project |
| Q1 OpenAI OAuth | **Split verdict.** GRADE HIGH that Codex's OAuth client is architecturally gated (allow-listed redirect URI in shipped source); GRADE VERY LOW that third parties are excluded — architecture is not policy |
| Gemini billing separation | **CLOSED** at PRIMARY confidence |

**Binding output — permitted README language:**

| Claim | Status |
|---|---|
| Gemini Go SDK features, billing separation | May be stated as resolved |
| OpenAI OAuth third-party eligibility | Must stay "unconfirmed" |
| Specialist-agent corpus | **No "novel / first / unique / unmatched"** — only "no comparable corpus found across a two-round, budget-limited check" |

| — | **STOP 1** — user reviews `PRD.md` + R&D findings, decides licence | *human* | — | ⏸️ **AWAITING YOU** |

**Phase 0 outputs:** `docs/phase-0-requirements/PRD.md`, `docs/phase-0-requirements/tech_scout_report.md`

## Phase 1 — Solution Architecture → HLD + ADRs

| # | Item | Agent | Status |
|---|---|---|---|
| 1.a | Router topology recommendation (ADR-1 input) | `multi-model-router-architect` | ✅ `adr1_router_topology.md` |
| 1.b | Provider catalogue + capability DNA | `genai-procurement-analyst` | ✅ `provider_catalogue.md` |
| 1.c | Cost model / CPST (router objective) | `llm-cost-optimizer` | ✅ `cost_model.md` |
| 1.d | Benchmark methodology | `llm-benchmark-analyst` | ✅ `benchmark_methodology.md` |
| 1.e | Harness control-loop design | `harness-engineering-architect` | ✅ `harness_control_policy.json` + `resource_elastic_policy.json` |
| 1.f | **HLD + ADR-3/4/5/7 resolution + Alignment 6 verdict** | `solution-architect` | ✅ `HLD.md` + `GSD.md` |
| 1.g | Capacity / complexity / reliability derivations | `mathematics-engineer` (delegated) | ✅ merged into `HLD.md` §11 |
| — | **STOP 2** — user reviews ADR resolutions | *human* | ⏸️ **AWAITING YOU** |
| — | **STOP 3** — user reviews `HLD.md` | *human* | ⏸️ pending STOP 2 |
| — | `consensus-agent` BINARY gate (loops to zero open items) | *gate* | ⬜ pending STOP 3 |

**Phase 1 outputs:** `docs/phase-1-architecture/HLD.md` (15 sections + filled RTM), `docs/phase-1-architecture/GSD.md` (v1.0), plus 1.a–1.e above.

**Phase 1 verdicts, for the STOP 2 review:**

| Question | Verdict |
|---|---|
| **Alignment 6** — one engine or two? | **TWO, cleanly layered.** Harness lower, SDLC engine upper and a client of it. `harness-engineering-architect`'s position CONFIRMED on five arguments; two are new (the "core testable with no live API" constraint, and the eval harness being unbuildable under a merged engine). Interface specified in HLD §7.4. |
| **ADR-3** — corpus storage form | **Amended form (b)** — compressed payload in one `go:embed`ed blob addressed by code-generated offset constants; identity/references/structure stay typed Go. Finding: form (b) read literally (per-item `[]byte` literals) produces ~85 MB of escaped Go source, *worse* than form (a)'s compile problem. |
| **ADR-4** — credential storage | **ONE mechanism:** LordCode-owned envelope-encrypted vault; the OS keychain holds only the 32-byte KEK. Headless interactive → Argon2id. CI/containers → `ephemeral`, **no vault file written at all**. Env-var KEK explicitly rejected. |
| **ADR-5** — distribution | **One signed artifact, four thin channels.** GitHub Releases is the sole source of truth; Homebrew/Scoop/npm all download and verify *that* artifact. `go install` works because generated source + blob are committed. |
| **ADR-7** — SDLC engine | **Hybrid with a decidable boundary:** topology interpreted from the embedded artifacts, gate semantics hardcoded in Go. Boundary rule: "can the library's own `validate.py` check it?" |
| **Benchmark scope change** | **ACCEPTED** with a split — the OpenAPI contract at Phase 1.5 (irreversible if missed), the Python harness as new work item **B.10**. Full 2,060-item bank rejected for v1, per the methodology's own advice. |

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

## Carry-forward obligations (raised at STOP 1 user review, 2026-09-04)

Three items that are **correct as designed today but become defects if a later phase
forgets them**. Recorded here because notes like these are exactly what get lost between
phases; each names the phase that must discharge it.

| # | Obligation | Discharged by | Why it matters |
|---|---|---|---|
| CF-1 | **Go is LOCKED** (OAQ-1 / ADR-2). No Phase 1 agent may reopen the language question. If it were reopened, the entire backend-engineer role shifts — `go-systems-engineer` out, one of rust/nodejs/python in — invalidating the roster, the thinking-budget table, and ADR-3's storage form. The single documented reopen trigger remains ADR-1 selecting an embedding-similarity topology. | Phase 1 — treat as settled input | A silent language change late would invalidate most of Phase 1 |
| CF-2 | **RTM `HLD Component` and `Test Case` columns are TBD by design**, not by omission — they are Phase 1 and Phase D deliverables respectively. `solution-architect` MUST replace the HLD-component TBDs with real component names when the HLD lands, or traceability reads as incomplete rather than as staged. | Phase 1 (HLD column) — ✅ **DISCHARGED**, `HLD.md` §14 carries the full replacement table for PRD §14.2, 62/62 = 1.0 coverage, ready to merge back. Phase D still owns the test-case column. | Staged emptiness is legitimate; permanent emptiness is a traceability failure |
| CF-3 | **No "Sign in with ChatGPT" / OAuth button for OpenAI in v1.** Evidence grades third-party eligibility VERY LOW; the shipped Codex client is architecturally gated via an allow-listed redirect URI. The CLI contract and the terminal UX must offer the **API-key flow only** for OpenAI, and must not render, document, or imply an OAuth path until official support is confirmed. | Phase 1.5 (`cli_contract.json`), Phase 3 (`terminal_ux_spec.md`) | Promising an auth path that does not exist is a first-run product failure |

## Open decisions

| ID | Decision | Owner | Status |
|---|---|---|---|
| ADR-1 | Router topology | Phase 1 | ✅ DNA-ranked cascade; adopted into the HLD with four seam amendments (HLD §7.3) |
| ADR-3 | Corpus storage form (constants vs compressed) | Phase 1 | ✅ amended form (b) — HLD §3. **Subject to `go-systems-engineer`'s measured spike: measurement wins over plan.** |
| ADR-4 | Credential storage + headless fallback | Phase 1, security veto | ✅ proposed — HLD §4. **Security holds veto at Phase F.1/F.4/F.6.** |
| ADR-5 | Distribution channel | Phase 1 | ✅ HLD §5. Forced cost: Apple Developer account + code-signing certificate. |
| ADR-7 | SDLC engine: hardcoded vs interpreted | Phase 1 | ✅ hybrid with a decidable boundary — HLD §6 |
| — | **Licence** | user, at Stop 1 (PM recommends Apache-2.0) | ⬜ |

## Advisory items raised by the HLD (for Phase 2 joint validation)

| ID | Item | Owner |
|---|---|---|
| AI-1 | PRD does not require daemon tool execution to be confined to a per-user workspace root — an elevation-of-privilege path on a CRITICAL-risk daemon | Phase 1.5 contract + F.3 |
| AI-2 | CERT-In log retention and DPDP §8(7) auto-deletion pull in opposite directions; a naive sweeper would delete audit evidence | `security-compliance-mapper` (F.5) |
| AI-3 | `cost_model.md` §0 Correction 1 (+50.0%, not +25.8%) not yet merged back into `provider_catalogue.md` — two Phase 1 docs state different numbers for the same thing | `genai-procurement-analyst` |
| AI-4 | TOPSIS ranking must keep its PROVISIONAL label in every surface, including the router's cold-start config, until B.10's harness replaces the two extrapolated Quality inputs | `multi-model-router-architect`, B.2 |
| AI-5 | Hand-rolled provider adapters (HLD §9.5) create a real recurring maintenance burden that needs a named Ops owner | Ops.1 |
| AI-6 | Per-`(provider, model-tier)` breaker granularity may leave too little call volume for the min-calls floor ever to be reached — an architectural question, not a parameter | `solution-architect`, on §11.5 |

## Known risks

| Risk | Impact | Mitigation |
|---|---|---|
| Subscription ≠ API access | Breaks the headline "connect your account" promise | Phase 0.2 verifies; error-message FR written |
| Library lacks CLI/TUI, packaging, keychain agents | Three capability gaps for building LordCode itself | Ownership assigned in Phase 1 |
| Go SDK parity below assumption | Raises provider-adapter maintenance cost | Phase 0.2 verifies; does not flip ADR-2 |
| Open contributions + CRITICAL security | Supply-chain surface | Hardened PR path; F.2 gates on every external PR |
