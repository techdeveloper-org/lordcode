# Product Requirements Document (PRD) — LordCode

<!-- Phase 0 Output | BA/PM + R&D Pipeline | KG v29.96.2 -->
<!-- FR/NFR, Acceptance Criteria, RTM, India Regulatory Layer, Capability Gap Register: business-analyst-agent -->
<!-- Positioning, MVP cut, Success Metrics, README narrative, Licence recommendation: product-manager-agent (pending) -->
<!-- Verified by: hallucination-detector (NLI target 1.0) + context-faithfulness-engineer (Faithfulness target 1.0) -->

**Document ID:** PRD-20260904-01
**Version:** 0.1.0-ba-draft
**Status:** DRAFT — BA sections complete, PM sections pending
**Created:** 2026-09-04
**Last Updated:** 2026-09-04
**Entry Mode:** Greenfield (Mode A) — `lordcode` repository is empty, zero commits at generation time
**India Regulatory Applicable:** YES — DPDP Act 2023 §4/§8, CERT-In Directions 2022, RPwD Act 2016 §40
**Hallucination Gate:** PENDING
**Source of truth for every FR/NFR below:** `docs/orchestration_prompt.md` (2026-09-04 revision). Every requirement in Sections 5, 6, 9, 12, and 15 carries an inline quote from that document. No requirement in this document originates from training-data assumption about what an "agentic coding CLI" typically needs — where the orchestration prompt is silent, this document says so explicitly (see §13).

---

## Section 1 — Executive Summary

*Authored by `product-manager-agent` (Phase 0.1b), merged 2026-09-04.*

**LordCode is not another AI coding CLI competing on model quality. It ships the specialist workforce instead of asking you to build one.**

> **Evidence note (corrected 2026-09-04 per Phase 0.4 synthesis).** An earlier draft of this line read *"it is the only one that ships the specialist workforce"*. The R&D evidence does not support that absolute. What two rounds of investigation actually established is narrower and defensible: **across a budget-limited, non-exhaustive survey, no comparable vendor-bundled corpus was found — the three independent candidates examined all turned out to be community marketplaces the user installs from, not capability that ships with the tool.** Graded **LOW** confidence, capped by `research_protocol.md` §9 precisely because this project has an interest in the answer. Permitted public wording therefore excludes "novel", "first", "unique", "unmatched", and "the only one". Use the survey framing above instead — it carries the same competitive weight without becoming false the moment someone produces a counter-example.

Two differentiators, stated as testable claims rather than adjectives:

### Primary — capability completeness
LordCode compiles the complete `claude-global-library` corpus — **528 agents, 1034 skills, 104 domain knowledge graphs, 77 math masters, 9,146 typed edges** (84.3 MB raw / 24.7 MB gzip, verified on disk 2026-09-04, source: `knowledge-graph/_master/README.md`) — directly into the Go binary via code generation (ADR-3). This is testable: `lordcode agents list` must return all 528 by name; `lordcode --version` must report the compiled library version stamp (`v29.96.2`); and a build with a dangling `skills:` reference must fail to compile, not fail silently at dispatch time. A user of a competing tool who wants a security-review specialist or a WSJF-scoring specialist has to *write that prompt themselves*. A LordCode user does not, because the specialist and its skill are already compiled in.

### Second — full-SDLC-per-requirement, not one model loop
Give Claude Code or Codex CLI a requirement and you get one model loop against your own prompt. Give LordCode a requirement and it runs the pipeline the library itself defines — Phase 0 requirements → architecture with real ADRs → a BINARY consensus gate → domain implementation → anti-hallucination verification (`RS = 1.0`) → QA → Phase F security (all severities zero) → reliability (`RS` computed) → Ops readiness — realistically **40–80+ specialist invocations per requirement** (`docs/orchestration_prompt.md`, NEW-3). This is also testable: a LordCode run produces an artifact trail (PRD → HLD → SRS → UML → sprint plan → code → security report) that a single-model-loop competitor structurally cannot produce, because it has no phase-gated pipeline to produce it *from*.

**What this claim does NOT say (guarding against overclaim):** LordCode does not claim its underlying models are more capable than a competitor's — model quality is a routing decision (ADR-1), not a LordCode-authored capability. The claim is about **process completeness and specialist coverage**, which is independently verifiable by inspecting the compiled corpus and the pipeline trace of any run. This distinction matters for the README narrative in §5 and for `hallucination-detector`'s review of this document: do not let "528 agents compiled in" imply "528 agents are always invoked" — NEW-3 and the orchestration prompt are explicit that a requirement runs only the specialists its domain calls for (40–80+ is realistic per requirement, not 528 per requirement).

---

## Section 2 — Product Context & Scope (BA framing)

This section is BA-authored grounding for the FR/NFR sections that follow. It is not a substitute for product-manager-agent's Section 1 positioning — it exists so Sections 5–15 are not read without the two-path model and component boundaries that make each FR's wording precise.

### 2.1 What is being built

> "Build LordCode: a standalone, multi-provider, agentic AI coding CLI **and team daemon**, written in Go, which embeds the complete `claude-global-library` and executes that library's full phase-gated SDLC pipeline." — `docs/orchestration_prompt.md`, "YOUR TASK"

Five load-bearing components, each a genuine engineering problem per the orchestration prompt: (1) the compiled-in library + full-SDLC-per-requirement execution, (2) multi-provider model routing, (3) a runtime harness/control loop, (4) a full SDLC pipeline engine, (5) an open contribution model. This PRD's Section 5 (Functional Requirements) is organized by these five components plus the CLI surface, the multi-tenant daemon, terminal UX/accessibility, and credential handling — all explicitly named in the Phase 0 task brief.

### 2.2 Two-path model (governs every FR that touches file/library access)

> "LIBRARY_PATH (read-only — capability source, NEVER written to by this project) ... PROJECT_PATH (read-write — the actual deliverable)." — `docs/orchestration_prompt.md`, "TWO-PATH MODEL"

LordCode-the-product never writes to `claude-global-library`. Every FR describing corpus compilation (Section 5.1) reads the library at build time only; nothing in this PRD describes a runtime write path back into the library.

### 2.3 Decided constraints — the five Open Architectural Questions (do not re-open)

Per the PRE-FLIGHT RESOLUTION table, all five OAQs plus five NEW items are **RESOLVED**, not open, as of the 2026-09-04 revision. This PRD records them as decided constraints with rationale; it does not re-litigate them. OAQ-3 (distribution/packaging) is the sole deliberate exception — deferred to Phase 1 ADR-5.

| # | Decision | Rationale (source) |
|---|---|---|
| OAQ-1 | CLI runtime language → **Go** | Scored 885/1000 by a dispatched language-selection expert across 8 weighted criteria (library-as-code fit, daemon fit, supply-chain posture). ADR-2. |
| OAQ-2 | Library-consumption mechanism → **full embed, code-generated into Go, compiled into the binary** | Not a curated subset, not a runtime-parsed blob. ADR-3. |
| OAQ-4 | Daemon/server mode → **in scope v1, network-exposed team server, multi-tenant** | "the single largest scope decision in this document." ADR-6. |
| OAQ-5 | Monetization/telemetry → **BYO API key, free tool, telemetry opt-in default OFF, source code and prompt content never transmitted as telemetry** | No LordCode-brokered billing. |
| NEW-1 | Library corpus lifecycle → **FROZEN** | No corpus-refresh mechanism in MVP scope. |
| NEW-2 | Pipeline scope → **LordCode executes the library's full SDLC pipeline** | Not persona dispatch alone. |
| NEW-3 | What runs per requirement → **full SDLC, every relevant specialist, 40–80+ invocations** | "This is the product, not an optimisation to be tuned away later." |
| OAQ-3 | Distribution/packaging → **DEFERRED to Phase 1 ADR-5** | Go widens rather than narrows the channel set — a deliberate deferral, not an oversight. |

Four ADRs remain genuinely open for **Phase 1** (solution-architect), not Phase 0: ADR-1 (router topology), ADR-4 (credential storage mechanism), ADR-5 (distribution/packaging — OAQ-3), ADR-7 (SDLC engine hardcoded-vs-interpreted). These are architecture decisions, not Phase-0-blocking open questions — see §13.

### 2.4 Explicit non-goals (v1)

> "no model training or fine-tuning in v1 (roadmap only) ... LordCode does not broker or resell inference (OAQ-5: BYO key, free); it does not modify `claude-global-library`; and it does not implement a corpus-update mechanism (NEW-1: the library is frozen)." — `docs/orchestration_prompt.md`

These are recorded formally in Section 10 (Out of Scope).

---

## Section 3 — Goals & OKRs

*Authored by `product-manager-agent` (Phase 0.1b), merged 2026-09-04.*

Per `product-analytics-core`'s AARRR/RARRA framing (retention-first) and the 5-criteria NSM test (expresses delivered value; leading indicator; actionable by the team; singular; genuinely measurable — not a vanity count).

### North Star Metric
**Successful multi-turn coding sessions per active user per week (SMS/AU/W).**

A session counts as **successful** iff, within one `lordcode` invocation lifecycle:
1. At least one full pipeline run reaches a terminal gate state of `PASS` (consensus BINARY approved, or the relevant phase gate cleared — not merely "invocation completed without a crash"), AND
2. The user does not abort the session before that gate (a proxy for "the output was worth waiting for"), AND
3. No Phase F security finding at `CRITICAL`/`HIGH` severity was surfaced in that session's output (a defect success would not be a *product* success).

**Why this passes the 5-criteria test, checked explicitly (not asserted):**
- *Expresses value:* a session only counts if a real artifact cleared a real gate — it cannot be inflated by opening the CLI and abandoning it.
- *Leading indicator:* session success this week predicts renewal-of-use next week better than raw invocation count would, because it filters out abandoned/failed runs.
- *Actionable:* every team (router, harness, SDLC engine, security) can move this number — router improves gate-pass latency, harness reduces abort-inducing stalls, SDLC engine reduces false gate failures, security reduces true findings that (correctly) block success.
- *Singular:* one number, one definition, computable from harness/pipeline telemetry already required for the replayable-audit requirement (component 3) — no new instrumentation category is needed beyond what CRITICAL security and HIGH hallucination-risk already mandate logging.
- *Measurable/comparable:* computable per user per ISO-8601 week from local session logs; for the opt-in telemetry cohort (default OFF, per OAQ-5) it aggregates without ever transmitting source code or prompt content — only the boolean success/fail/abort state and gate name.

This directly feeds Phase 6 WSJF **Cost of Delay** scoring: any Sprint 1+ feature's User-Business-Value component can be argued against its measured or projected effect on SMS/AU/W, giving `ba-pm-mathematics-expert` a real CoD input rather than an ungrounded 1–10 guess. **I am not computing the WSJF scores themselves — that derivation belongs to `ba-pm-mathematics-expert` per the binding operating rule; this section defines what CoD should be measured against.**

### Supporting metrics (secondary, feed the NSM, not proxies for it)
| Metric | Layer | Why it matters |
|---|---|---|
| Gate pass rate per phase (consensus, `RS=1.0`, Phase F, Phase H) | SDLC engine | Distinguishes "pipeline ran" from "pipeline was trustworthy" — HIGH hallucination-risk requires this be tracked per-gate, not in aggregate |
| Router acceptance rate per provider (`q_provider`) | Router | Feeds ADR-1's own cascade break-even math (`q₁ > 6.7%` threshold, from the orchestration prompt) — not invented here, cited from the router's own decision criterion |
| P50/P90 cost per successful session, per phase | Harness/cost display | Directly the "post-run per-phase cost display" FR already committed in constraints — this is what that display reports, framed as a metric |
| Time-to-first-successful-gate (new user) | Onboarding/activation | RARRA's Activation stage — a user whose `auth login` + first requirement does not reach one PASS gate within a session will churn before Retention is even measurable |
| Zero-CRITICAL-finding session rate | Security | Must stay at 100% by construction (Phase F gate), tracked as a canary that the gate itself is not degrading, not as a target to trade off |

**Explicit non-metric, to prevent a predictable mistake:** raw agent-invocation count (e.g., "80 agents ran this week") is a *cost* indicator, not a *success* indicator, and must never be reported as if higher were better — the CONSTRAINTS block is explicit that thorough token spend is accepted, not celebrated as a KPI. `product-analytics-core`'s vanity-metric caution applies directly here.

### 3.3 Success Metrics (KPIs)

> Success metrics are defined in full under Section 3 above (North Star Metric plus five supporting metrics, and one explicit non-metric).

---

## Section 4 — Stakeholder Map

Stakeholder identification only — AHP pairwise priority weighting is explicitly out of scope for business-analyst-agent per this agent's Operating Rules ("Must NOT perform AHP eigenvector or MAUT computations inline — always delegate to ba-pm-mathematics-expert"). Weights below are marked TBD pending that delegation.

| ID | Stakeholder | Role | Type | AHP Priority Weight | Engagement Level |
|----|---|---|---|---|---|
| STK-001 | Individual developer (BYO account) | Primary user of the CLI, connects 1–3 provider accounts | Primary User | TBD — ba-pm-mathematics-expert | High |
| STK-002 | Team / engineering org admin | Deploys and administers the multi-tenant daemon | Primary User | TBD | High |
| STK-003 | Daemon end-user (team member) | Uses a shared LordCode team server, not a local CLI | Primary User | TBD | High |
| STK-004 | External contributor | Submits PRs against the open LordCode repository | Secondary User | TBD | Medium |
| STK-005 | Security/compliance reviewer (internal or auditor) | Reviews DPDP/CERT-In/RPwD posture, approves external PR security gates | Decision Maker | TBD | High |
| STK-006 | Data Principal whose source code may contain their personal data | Indirect stakeholder under DPDP Act 2023 | Regulator-adjacent | TBD | Medium |
| STK-007 | CERT-In / regulator | Sets breach-reporting and log-retention obligations | Regulator | TBD | Low (Monitor) |
| STK-008 | Third-party model provider (OpenAI, Anthropic, Google) | Counter-party to every routed inference call | External | TBD | Medium |

---

## Section 5 — Functional Requirements

Format per `business-requirements-analysis-core` §2.2: `FR-{module}-{seq}`. All requirements in imperative voice ("The system SHALL"). MoSCoW: M = Must (v1), S = Should. **WSJF Score: intentionally left TBD in every row** — business-analyst-agent does not compute WSJF; delegated to `ba-pm-mathematics-expert` per this PRD's constraints.

Every FR quotes its source verbatim from `docs/orchestration_prompt.md` so the requirement is traceable to text that was actually generated for LordCode, not inferred from category convention.

### 5.1 Component 1 — Compiled-in library & full-SDLC-per-requirement execution

| ID | Requirement | Priority | Source (STK) | WSJF |
|---|---|---|---|---|
| FR-COR-001 | The system SHALL code-generate the complete library corpus (528 agents, 1034 skills, 104 domain knowledge graphs, 77 math masters, 9,146 typed edges, 368 mapped regulations) into typed Go source at build time and compile it into the binary. The system SHALL NOT read agent/skill markdown or parse KG JSON at runtime to resolve a persona. | M | STK-001, STK-002 | TBD |
| FR-COR-002 | The build SHALL fail (compile-time error) if any agent's `skills:` frontmatter names a skill that is not present in the compiled corpus — a "hollow persona" dispatch SHALL be structurally impossible to ship. | M | STK-001 | TBD |
| FR-COR-003 | For every user requirement submitted to LordCode, the system SHALL execute the library's full phase-gated SDLC pipeline (Phase 0–8 pre-processing, Phase A→A.5→A.6→B→C→D→H→F→E→G→Ops.1–5) rather than a single model-loop dispatch, invoking every specialist agent its domain calls for. | M | STK-001, STK-002, STK-003 | TBD |
| FR-COR-004 | The system SHALL provide a routability audit, run at build/CI time, that for every one of the 528 compiled agents verifies (a) the agent is reachable from at least one node/branch/pattern in the compiled 23-node/82-branch decision tree or its own domain KG routing entry, and (b) every skill in its mandatory skill set is present per FR-COR-002. The audit SHALL emit a machine-readable `routability_report.json` stating a routability ratio = (agents reachable) / 528. A ratio below 1.0 SHALL fail the build. | M | STK-001, STK-005 | TBD |
| FR-COR-005 | The system SHALL compile a `library_version` provenance stamp (value and build date of the source library) into the binary and SHALL surface it via a version-reporting command. | M | STK-001 | TBD |
| FR-COR-006 | After a pipeline run completes, the system SHALL display the token/dollar cost of that run broken down per SDLC phase. The system SHALL NOT require pre-run cost approval or enforce a spend ceiling. | M | STK-001, STK-002 | TBD |

**Acceptance Criteria:**

```
AC-FR-COR-001: Given the LordCode Go module source tree and a checkout of the frozen library corpus,
  When the corpus code-generation step is run as part of the build,
  Then the resulting binary contains every one of the 528 agents and 1034 skills as compiled Go values
  And no file I/O against the library's markdown or JSON files occurs when the binary resolves a persona at runtime.

AC-FR-COR-002: Given an agent definition whose `skills:` list names a skill absent from the compiled corpus,
  When the build is run,
  Then the build fails with an error identifying the missing skill and the offending agent
  And no binary is produced.

AC-FR-COR-003: Given a user submits a new requirement to LordCode,
  When the requirement is accepted,
  Then LordCode reports which SDLC phases and which specialist agents it dispatched for that requirement
  And the report shows more than one specialist agent was invoked for any requirement touching more than one domain.

AC-FR-COR-004: Given the compiled 528-agent corpus and the compiled decision tree,
  When the routability audit is run,
  Then it emits routability_report.json containing a routability ratio
  And any agent with a ratio contribution of zero is listed by name in an "unreachable_agents" array.

AC-FR-COR-005: Given a built LordCode binary,
  When the user runs the version-reporting command,
  Then the output includes the compiled library version string and its build date.

AC-FR-COR-006: Given a completed LordCode pipeline run,
  When the run finishes,
  Then LordCode displays a cost summary itemised by SDLC phase
  And no prompt requesting cost pre-approval was shown before or during the run.
```

### 5.2 Component 2 — Multi-provider model routing

| ID | Requirement | Priority | Source (STK) | WSJF |
|---|---|---|---|---|
| FR-RTG-001 | The system SHALL support three first-class named model providers — OpenAI, Anthropic, and Google Gemini — plus an adapter interface open to additional providers. | M | STK-001 | TBD |
| FR-RTG-002 | The system SHALL treat no provider as primary and no provider as a degraded second tier: a user with only one of the three providers configured SHALL receive a fully working tool, with no provider connection required as a precondition to use LordCode. | M | STK-001 | TBD |
| FR-RTG-003 | For each individual agent invocation within a pipeline run, the system SHALL select which of the user's *configured* providers executes that invocation via a router (topology decided in Phase 1 ADR-1), independently of which specialist agent the SDLC pipeline engine dispatched. | M | STK-001 | TBD |
| FR-RTG-004 | The system SHALL maintain an independent circuit breaker per configured provider (never one global breaker across all providers), so that one provider's outage does not block routing to the user's other configured providers. | M | STK-001, STK-002 | TBD |
| FR-RTG-005 | When the router's best-ranked provider for a given invocation has no account configured by the user, the system SHALL route to the best-ranked *configured* provider instead of failing the invocation, and SHALL record that a substitution occurred and why. | M | STK-001 | TBD |
| FR-RTG-006 | The system SHALL normalise each provider's request/response shape, tool-calling schema, streaming protocol, error taxonomy, and auth model behind a single internal provider-adapter contract, so that no one provider's shape is privileged as "the" internal representation. | M | STK-001, STK-008 | TBD |
| FR-RTG-007 | Before any new or materially changed router topology reaches full production traffic, the system SHALL run it in shadow mode against at least 10% of real traffic and evaluate it against a formal sequential test before promotion (exact statistical procedure and boundary values delegated to `genai-routing-mathematician` in Phase 1). | S | STK-002, STK-005 | TBD |

**Acceptance Criteria:**

```
AC-FR-RTG-001: Given a user has connected only a Google Gemini account,
  When they submit a coding requirement to LordCode,
  Then LordCode completes the requirement end-to-end using only Gemini-backed invocations
  And LordCode does not report a degraded mode or reduced capability set solely because OpenAI/Anthropic are unconfigured.

AC-FR-RTG-002: Given a user has connected both an Anthropic account and an OpenAI account,
  When two independent agent invocations occur within the same pipeline run,
  Then each invocation's provider selection is reported
  And the report shows the router considered both configured providers, not a single hardcoded default.

AC-FR-RTG-003: Given the Anthropic provider is returning failures above the circuit-breaker's configured threshold,
  When a new agent invocation is routed,
  Then invocations continue to be routed to the user's other configured, healthy providers
  And no invocation is blocked purely because the Anthropic breaker is open.

AC-FR-RTG-004: Given the router's top-ranked provider for an invocation is OpenAI but the user has not connected an OpenAI account,
  When that invocation is routed,
  Then LordCode routes the invocation to the user's next-best configured provider
  And the run's audit trail records that a substitution occurred and names the unavailable provider.

AC-FR-RTG-005: Given a new router topology has been implemented,
  When it is deployed,
  Then it first runs in shadow mode receiving at least 10% of real traffic without affecting production routing decisions
  And promotion to full production traffic only occurs after the shadow-mode evaluation passes.
```

### 5.3 Component 3 — Runtime harness / control loop

| ID | Requirement | Priority | Source (STK) | WSJF |
|---|---|---|---|---|
| FR-HRN-001 | The system SHALL mediate every tool call and every stop condition within an agent-loop invocation through a harness that supports deterministic replay of a completed run for audit purposes. | M | STK-002, STK-005 | TBD |
| FR-HRN-002 | For any completed pipeline run, the system SHALL be able to answer, per invocation: which model/provider executed it, and what it cost — as a real, replayable answer rather than an estimate. | M | STK-001, STK-002 | TBD |
| FR-HRN-003 | The system SHALL enforce a hard maximum-duration bound and a cumulative token/cost budget guard on every agent-loop invocation as mandatory stop conditions, independent of and in addition to the per-run cost *display* in FR-COR-006. | M | STK-002, STK-005 | TBD |

**Acceptance Criteria:**

```
AC-FR-HRN-001: Given a completed pipeline run,
  When an operator requests a replay of that run,
  Then the harness reproduces the same sequence of tool calls and stop-condition evaluations recorded during the original run.

AC-FR-HRN-002: Given a completed pipeline run with 12 agent invocations,
  When the user asks which model executed invocation #7 and what it cost,
  Then LordCode returns the actual provider/model used for invocation #7 and its actual recorded cost, not an aggregate estimate.

AC-FR-HRN-003: Given an agent-loop invocation that has run past its configured maximum duration,
  When the duration bound is reached,
  Then the harness stops the invocation regardless of remaining budget
  And the stop is logged as a T_max stop disjunct, distinct from a budget-guard stop.
```

### 5.4 Component 4 — SDLC pipeline engine

| ID | Requirement | Priority | Source (STK) | WSJF |
|---|---|---|---|---|
| FR-SDL-001 | The system SHALL implement a phase state machine covering Phase 0–8 and Phase A→A.5→A.6→B→C→D→H→F→E→G→Ops.1–5, with a per-gate evaluator for each gate type used by the library (consensus BINARY, reliability score RS, Phase F all-severities-zero, Phase H regression criteria, PRR GO/NO-GO). | M | STK-001, STK-002 | TBD |
| FR-SDL-002 | The system SHALL implement a bounded self-correction loop (SC.1–SC.3) that retries a failed gate at most 3 times before escalating to a human, never looping indefinitely. | M | STK-002, STK-005 | TBD |
| FR-SDL-003 | The system SHALL treat the compiled 23-node/82-branch orchestration decision tree as a traversable runtime artifact that the pipeline engine consults to route a requirement, not as documentation. | M | STK-001 | TBD |
| FR-SDL-004 | The system SHALL persist pipeline state across process invocations, so that a multi-phase SDLC run started in one CLI invocation (or one daemon session) can be resumed or inspected in a later one. | M | STK-002, STK-003 | TBD |
| FR-SDL-005 | The system SHALL keep "which agents run" (owned by the SDLC pipeline engine) and "which model each agent runs on" (owned by the multi-provider router, FR-RTG-003) as independently overridable decisions: overriding a provider selection for one invocation SHALL NOT change which agents the pipeline engine dispatches, and vice versa. | M | STK-001, STK-002 | TBD |

**Acceptance Criteria:**

```
AC-FR-SDL-001: Given a requirement enters Phase C (implementation),
  When Phase C completes,
  Then the reliability gate is evaluated using the library's defined RS formula
  And the pipeline does not advance to Phase F until that gate records a result.

AC-FR-SDL-002: Given a gate fails on its first evaluation,
  When the self-correction loop retries the failing step,
  Then it retries at most 3 times
  And on a 4th consecutive failure the run is escalated to a human reviewer rather than retried again.

AC-FR-SDL-003: Given a new user requirement,
  When the pipeline engine determines which phase(s) and pattern the requirement routes to,
  Then the routing decision is derived by traversing the compiled decision tree
  And the traversal path taken is recorded in the run's audit trail.

AC-FR-SDL-004: Given a multi-phase SDLC run was started and the CLI process then exited,
  When the user re-invokes LordCode against the same requirement,
  Then LordCode resumes from the last completed phase rather than restarting Phase 0.

AC-FR-SDL-005: Given an operator manually overrides the provider used for a single agent invocation,
  When the override is applied,
  Then the set of agents the pipeline engine dispatches for that requirement is unchanged.
```

### 5.5 Component 5 — Open contribution model

Governance and security-gate requirements for contribution are formulated as **NFR-CTB** (testable, non-functional) per the Phase 0 task brief's explicit instruction — see Section 6.5. FR-CTB-001 below is the one functional (user-facing) requirement of this component.

| ID | Requirement | Priority | Source (STK) | WSJF |
|---|---|---|---|---|
| FR-CTB-001 | The system's repository SHALL provide a documented external-contribution path (issue submission, PR submission, and PR review outcome visible to the contributor) that does not require write access to `main`. | M | STK-004, STK-005 | TBD |

**Acceptance Criteria:**

```
AC-FR-CTB-001: Given an external contributor without commit access opens a pull request,
  When the PR is submitted,
  Then the repository's automated checks and maintainer review path both execute against the PR
  And the contributor can observe the PR's review status without needing repository write access.
```

### 5.6 CLI command surface

| ID | Requirement | Priority | Source (STK) | WSJF |
|---|---|---|---|---|
| FR-CLI-001 | The system SHALL define its command/subcommand/flag/config-file/exit-code/stdin-stdout-stderr surface as a single stable, versioned contract, subject to the same breaking-change discipline as the daemon's OpenAPI surface. | M | STK-001 | TBD |
| FR-CLI-002 | Every FR in this PRD that has a user-facing action SHALL map to at least one CLI command or flag, recorded as an FR→command traceability table in the Phase 1.5 CLI Command & Config Contract. | M | STK-001 | TBD |
| FR-CLI-003 | The system SHALL provide a `--json` machine-readable output mode on commands whose output is consumed by CI scripts. | M | STK-004 | TBD |
| FR-CLI-004 | The system SHALL honour the `NO_COLOR` environment variable and SHALL provide colourblind-safe default styling when colour output is enabled. | M | STK-001 | TBD |

**Acceptance Criteria:**

```
AC-FR-CLI-001: Given a released version of LordCode,
  When a documented command's flags or exit codes change,
  Then the change is recorded as a breaking change in the CLI contract's version history
  And the CLI's own version-reporting command reflects a corresponding version bump.

AC-FR-CLI-002: Given the Phase 1.5 CLI Command & Config Contract,
  When it is reviewed against this PRD's FR list,
  Then every user-facing FR has at least one corresponding command or flag entry
  And no command exists in the contract without a traceable FR.

AC-FR-CLI-003: Given a CI script invokes a LordCode command with --json,
  When the command completes,
  Then stdout contains only machine-parseable JSON
  And no human-readable progress text is interleaved into stdout.

AC-FR-CLI-004: Given the NO_COLOR environment variable is set,
  When any LordCode command produces output,
  Then no ANSI colour codes appear in that output.
```

### 5.7 Multi-tenant daemon

| ID | Requirement | Priority | Source (STK) | WSJF |
|---|---|---|---|---|
| FR-DAE-001 | The system SHALL expose the daemon's team-server functionality through a literal `openapi.yaml` HTTP contract, treated as a first-class stable integration surface from day one. | M | STK-002, STK-003 | TBD |
| FR-DAE-002 | The daemon SHALL authenticate and authorize every request against a specific user identity; no daemon endpoint SHALL execute on behalf of an unauthenticated caller. | M | STK-002, STK-003, STK-005 | TBD |
| FR-DAE-003 | The daemon SHALL isolate each user's connected provider credentials from every other user: no code path SHALL allow user A's stored credential to be used to service user B's request. | M | STK-002, STK-003, STK-005 | TBD |
| FR-DAE-004 | The daemon SHALL isolate each user's source code, prompts, and pipeline context from every other user's context window: no user's submitted content SHALL appear in another user's context, response, or logs. | M | STK-002, STK-003, STK-005, STK-006 | TBD |
| FR-DAE-005 | The daemon SHALL rate-limit requests per user and per provider to protect both the daemon and the user's own provider-side quota. | M | STK-002, STK-003 | TBD |
| FR-DAE-006 | The daemon SHALL maintain a per-user audit log of pipeline runs and provider invocations sufficient to reconstruct what data left the daemon, to which provider, and under which user's consent state. | M | STK-002, STK-005, STK-007 | TBD |
| FR-DAE-007 | The daemon SHALL support graceful shutdown that allows in-flight pipeline runs to reach a safe checkpoint (per FR-SDL-004's persisted pipeline state) rather than being abruptly terminated. | M | STK-002, STK-003 | TBD |

**Acceptance Criteria:**

```
AC-FR-DAE-001: Given the daemon is running,
  When a client requests its OpenAPI document,
  Then the served document matches the versioned openapi.yaml contract produced in Phase 1.5.

AC-FR-DAE-002: Given a request arrives at the daemon without valid authentication,
  When the daemon processes it,
  Then the request is rejected before any pipeline or provider action is taken.

AC-FR-DAE-003: Given user A and user B both have provider credentials configured on the same daemon instance,
  When user B submits a request,
  Then only user B's own stored credentials are used to service it
  And an audit check confirms user A's credentials were never read during user B's request.

AC-FR-DAE-004: Given user A and user B are both running pipeline requests concurrently on the same daemon,
  When user A's request completes,
  Then user A's response and logs contain no fragment of user B's source code or prompts.

AC-FR-DAE-005: Given a user has exceeded their configured per-user rate limit,
  When they submit another request,
  Then the daemon rejects the request with a rate-limit response rather than queuing it indefinitely.

AC-FR-DAE-006: Given a completed daemon-hosted pipeline run for a given user,
  When a compliance reviewer requests that user's audit trail,
  Then the trail shows every provider the run's source code was sent to and the consent state at the time of transmission.

AC-FR-DAE-007: Given the daemon receives a shutdown signal while pipeline runs are in flight,
  When shutdown proceeds,
  Then each in-flight run reaches its next persisted checkpoint before its connection is closed
  And no run is left in a corrupted, unresumable state.
```

### 5.8 Connect-your-account authentication

This is one of the three areas the Phase 0 task brief flags as needing specific care: a consumer subscription (ChatGPT Plus, Claude Pro/Max) is **not** API access, and the error surface must say so precisely.

| ID | Requirement | Priority | Source (STK) | WSJF |
|---|---|---|---|---|
| FR-AUT-001 | The system SHALL provide a command to connect a named provider account (`lordcode auth login <provider>`), for each of OpenAI, Anthropic, and Google Gemini independently. | M | STK-001 | TBD |
| FR-AUT-002 | The system SHALL provide a command to list which providers are currently connected and, at minimum, whether each connection is currently valid (`lordcode auth list`). | M | STK-001 | TBD |
| FR-AUT-003 | The system SHALL allow a user to connect one, two, or all three providers, in any combination, and SHALL allow zero providers connected without blocking LordCode from starting (though a run will fail at first routed invocation if no provider is connected — see FR-RTG-002/FR-AUT-007). | M | STK-001 | TBD |
| FR-AUT-004 | The system SHALL provide a command to revoke/disconnect a previously connected provider's stored credential, removing it from local (or daemon-side, per-user) storage. | M | STK-001, STK-002 | TBD |
| FR-AUT-005 | The system SHALL allow a user to explicitly select/prefer a specific connected provider for a run, overriding the router's default selection for that run (consistent with FR-SDL-005's independence of agent- and model-selection). | S | STK-001 | TBD |
| FR-AUT-006 | Before accepting a credential as a valid connection, the system SHALL validate that the credential is a provider **API** credential (e.g., an API key with usage/billing separate from a consumer subscription), and SHALL NOT accept a consumer-subscription-only token (e.g., a ChatGPT Plus or Claude Pro/Max session token) as satisfying "connected." | M | STK-001, STK-005 | TBD |
| FR-AUT-007 | When a connection attempt fails, or when a routed invocation has no configured account for the provider it needs, the system SHALL produce an error message that names the specific missing credential and states where to obtain it (e.g., "Your ChatGPT Plus subscription does not include API access; LordCode needs an API key with credits from platform.openai.com"). The system SHALL NOT surface a bare "authentication failed" message for this class of error. | M | STK-001 | TBD |

> Note on mechanism: the orchestration prompt explicitly defers the exact per-provider connection mechanism (OAuth device flow vs. API-key paste) to Phase 0.2 R&D verification by `technology-scout-analyst`. FR-AUT-001–007 above state the *requirement*, not the mechanism; this PRD does not claim which flow each provider uses until that verification lands.

**Acceptance Criteria:**

```
AC-FR-AUT-001: Given a user runs `lordcode auth login gemini`,
  When the connection flow completes with a valid credential,
  Then Gemini is reported as connected on a subsequent `lordcode auth list`.

AC-FR-AUT-002: Given a user has connected Anthropic and Gemini but not OpenAI,
  When they run `lordcode auth list`,
  Then the output shows Anthropic and Gemini as connected and OpenAI as not connected
  And no fabricated status is shown for OpenAI.

AC-FR-AUT-003: Given a user has connected zero providers,
  When they launch LordCode,
  Then LordCode starts successfully
  And the failure, if any, occurs only at the point a pipeline run attempts its first provider invocation.

AC-FR-AUT-004: Given a user has a connected OpenAI credential,
  When they run `lordcode auth logout openai`,
  Then the credential is removed from storage
  And a subsequent `lordcode auth list` shows OpenAI as not connected.

AC-FR-AUT-005: Given a user has both Anthropic and Gemini connected,
  When they run a command with an explicit provider preference for Gemini,
  Then all invocations in that run are routed to Gemini
  And the router's own top-ranked choice is overridden without error.

AC-FR-AUT-006: Given a user attempts to connect using only a ChatGPT Plus subscription session token (no API key),
  When LordCode validates the credential,
  Then the connection is rejected
  And the provider is not reported as connected on `lordcode auth list`.

AC-FR-AUT-007: Given a user's only configured provider is OpenAI via a ChatGPT Plus subscription with no API key,
  When a routed invocation needs OpenAI,
  Then the error message names "OpenAI API access" as missing and points to platform.openai.com for an API key with credits
  And the message text is not the bare string "authentication failed".
```

### 5.9 Credential / API-key handling

| ID | Requirement | Priority | Source (STK) | WSJF |
|---|---|---|---|---|
| FR-SEC-001 | The system SHALL store connected provider credentials using the host OS's native secure credential store (macOS Keychain, Windows Credential Manager, Linux Secret Service) where one is available, with a documented fallback (encrypted file) for headless environments (SSH sessions, containers, CI) where no Secret Service is running. | M | STK-001, STK-002, STK-005 | TBD |
| FR-SEC-002 | The system SHALL NOT write provider credentials, API keys, or credential fragments to any log output, including debug/verbose logging modes. | M | STK-001, STK-005, STK-007 | TBD |

**Acceptance Criteria:**

```
AC-FR-SEC-001: Given a headless Linux CI environment with no Secret Service running,
  When a user connects a provider credential,
  Then the credential is stored via the documented encrypted-file fallback
  And LordCode does not silently fail or refuse to store the credential.

AC-FR-SEC-002: Given verbose/debug logging is enabled for a run that uses a connected credential,
  When the log output is inspected,
  Then no full or partial API key value appears anywhere in the log.
```

### 5.10 Terminal UX & accessibility (RPwD Act 2016 §40)

| ID | Requirement | Priority | Source (STK) | WSJF |
|---|---|---|---|---|
| FR-UXA-001 | The system SHALL provide a screen-reader-compatible plain-text fallback output mode for all interactive/streaming CLI output, in addition to the styled default output. | M | STK-001, STK-006 | TBD |

**Acceptance Criteria:**

```
AC-FR-UXA-001: Given a user's terminal environment is configured for a screen reader,
  When LordCode produces streaming progress output,
  Then a plain-text fallback rendering is available that conveys the same information without relying on colour, cursor movement, or spinner glyphs.
```

### 5.11 DPDP Act 2023 data-handling requirements

> "LordCode transmits user source code (potentially containing personal data) to third-party model providers, and a multi-user daemon stores per-user data. Consent, purpose limitation, retention, and §8(7) auto-deletion are real FRs." — `docs/orchestration_prompt.md`, CONSTRAINTS

These are written as real functional requirements, not a placeholder compliance sentence, per this PRD's binding constraint and per `business-analyst-agent`'s Operating Rule 4 ("DPDP Act 2023 §3/§4/§8 compliance section is mandatory ... never optional").

| ID | Requirement | Priority | Source (STK) | WSJF |
|---|---|---|---|---|
| FR-DPD-001 | Before a user's source code or prompt content is first transmitted to a third-party model provider, the system SHALL obtain and record explicit consent from that user identifying which provider(s) will receive their content. | M | STK-001, STK-003, STK-006 | TBD |
| FR-DPD-002 | The system SHALL use a user's transmitted source code and prompt content solely for the purpose of producing that user's requested pipeline output, and SHALL NOT repurpose it for any other declared or undeclared purpose (e.g., LordCode's own product analytics, model improvement, or a different user's request). | M | STK-001, STK-006 | TBD |
| FR-DPD-003 | The system SHALL define and enforce a retention period for daemon-stored per-user data (pipeline artifacts, logs, cached content) and SHALL automatically delete data that has exceeded that period, per DPDP Act 2023 §8(7). | M | STK-002, STK-003, STK-006, STK-007 | TBD |
| FR-DPD-004 | Product telemetry SHALL be opt-in with a default-OFF state, and regardless of the telemetry opt-in state, the system SHALL NOT transmit user source code or prompt content as telemetry. | M | STK-001, STK-003, STK-006 | TBD |
| FR-DPD-005 | The system SHALL provide a mechanism for a user of the multi-tenant daemon to request access to, correction of, or erasure of their own stored personal data, consistent with DPDP Act 2023 Data Principal rights. | M | STK-003, STK-006 | TBD |

**Acceptance Criteria:**

```
AC-FR-DPD-001: Given a first-time user has not yet granted consent,
  When their first pipeline run would transmit source code to a provider,
  Then LordCode blocks the transmission until consent naming that provider is recorded
  And the consent record is retrievable later by the user.

AC-FR-DPD-002: Given a user's source code was transmitted to fulfil their pipeline request,
  When the request completes,
  Then no separate LordCode-internal analytics or training process re-reads that source code for any other purpose.

AC-FR-DPD-003: Given a daemon-stored pipeline artifact has exceeded the configured retention period,
  When the retention sweep runs,
  Then the artifact is deleted
  And the deletion is recorded in the audit log per FR-DAE-006.

AC-FR-DPD-004: Given a user has not opted into telemetry,
  When they use LordCode,
  Then no telemetry is transmitted
  And even if telemetry were enabled, no event payload contains source code or prompt text.

AC-FR-DPD-005: Given a daemon user requests erasure of their personal data,
  When the request is processed,
  Then their stored pipeline artifacts, logs, and credentials referencing personal data are removed
  And the user receives confirmation the erasure completed.
```

---

## Section 6 — Non-Functional Requirements

| ID | Category | Requirement | Metric | Verification Method |
|---|---|---|---|---|
| NFR-SEC-001 | Security | The system SHALL pass a full-depth security audit (Phase F.0–F.6, all agents) with zero Critical/High findings before v1 GA, reflecting the CRITICAL security risk rating raised from v1's HIGH because of the network-exposed multi-user daemon holding multiple providers' credentials. | Zero Critical/High findings at F.6 gate | Security audit (Phase F) |
| NFR-SEC-002 | Compliance | The system SHALL capture sufficient incident-relevant logging (auth failures, credential access, cross-tenant access attempts) to support CERT-In Directions 2022's 6-hour incident-reporting obligation for a network-exposed service. | Incident detection-to-report readiness ≤ 6h | Log/audit review |
| NFR-SEC-003 | Supply chain | The system's dependency tree SHALL consist only of Go modules resolvable without install-time script execution, and SHALL be scanned by a reachability-based vulnerability scanner (not version-matching alone) in CI on every dependency change. | Zero install-time-script dependencies; CI scan gate | CI pipeline (govulncheck or equivalent) |
| NFR-DAE-001 | Scalability | The daemon SHALL service multiple users' concurrent pipeline runs without one user's run degrading another's — real concurrency, not one-session-at-a-time serialization. | Concurrent-run isolation under load test | Load/stress test |
| NFR-DAE-002 | Least privilege | Each credential-handling code path's least-privilege score, `\|permissions_used\| / \|permissions_granted\|`, SHALL exceed 0.8. | Score > 0.8 | Security review (`cloud-security-core`) |
| NFR-UXA-001 | Accessibility | Contrast on the ANSI colour palette actually used by LordCode SHALL meet a measurable accessibility threshold; exact contrast ratio target is delegated to Phase 3 (`ui-ux-mathematics-engineer`) since RPwD Act 2016 §40 does not itself specify a numeric CLI-palette threshold and GIGW does not bind a non-government product. | Contrast ratio ≥ threshold set in Phase 3 | Accessibility audit (Phase 3) |
| NFR-CTB-001 | Governance | The repository SHALL carry a licence file, `CONTRIBUTING.md`, and a code of conduct, and SHALL document its PR review path, before accepting the first external contribution. | All 3 files present + documented path | Repository audit |
| NFR-CTB-002 | Supply chain | External contributions SHALL require commit signing; unsigned commits SHALL be rejected by CI on PRs from outside the maintainer set. | 100% signed-commit enforcement on external PRs | CI gate |
| NFR-CTB-003 | Governance | Every PR SHALL require at least one maintainer review before merge; auto-merge SHALL NOT be enabled for external PRs. | 100% maintainer-reviewed external merges | Repository branch-protection audit |
| NFR-CTB-004 | Security | CI SHALL run the Phase F.2 static-analysis and secrets-detection gates against every external PR before it is eligible for merge. | 100% external PRs gated | CI pipeline audit |
| NFR-CTB-005 | Supply chain | Any PR that adds or upgrades a dependency SHALL trigger a dependency-addition review distinct from ordinary code review, given this is a CRITICAL-security binary handling multiple users' provider credentials. | 100% dependency-adding PRs flagged for review | Repository workflow audit |
| NFR-ARC-001 | Architecture / roadmap boundary | The provider-adapter interface SHALL be designed so that a satisfying implementation is not required to be a third-party HTTP API — i.e., a future first-party LordCode model must be addable as another adapter, not a rewrite of the interface. | Interface review checklist item at Phase 1.5 | Architecture review (ADR-1/Phase 1.5) |
| NFR-PERF-001 | Portability | The CLI SHALL correctly handle file paths containing spaces, non-ASCII characters, and UNC prefixes across Windows, macOS, and Linux (amd64 + arm64). | Cross-platform invocation matrix passes | Phase D.3 cross-platform test matrix |
| NFR-PERF-002 | Portability | Any local cache, config, or credential-fallback directory the system creates SHALL be resolved via the platform-correct user cache/config directory API (e.g., `os.UserCacheDir()`/`os.UserConfigDir()` in Go), never a hardcoded path literal such as `~/.lordcode` or `%APPDATA%`. | No hardcoded path literals in path-resolution code | Code review / static check |
| NFR-DPD-001 | Compliance | The daemon SHALL implement per-user context isolation controls (namespace separation on session creation, and a similarity-based cross-contamination check) sufficient to make DPDP §4 isolation testable, not merely asserted — exact mechanism (e.g., cosine-similarity leakage alert thresholds) is designed in Phase 1 by `context-engineering-agent`. | Isolation controls present and testable | Phase 1 design review + Phase F audit |

> **Open item for Phase 1 to reconcile, flagged rather than silently resolved:** the orchestration prompt's "Path portability" section states "ADR-3's corpus cache-inflation directory must resolve through a platform-correct API," while ADR-3 itself states the compiled-corpus design has "no cache directory, no inflation step, no first-run latency." NFR-PERF-002 above is written to apply to local cache/config/credential-fallback directories generally (which do exist — e.g., FR-SEC-001's headless-Linux credential fallback file), not to the corpus itself, since the corpus is compiled into the binary per FR-COR-001 and has no runtime cache directory. Phase 1 (`solution-architect`) should confirm this reading is correct rather than this PRD asserting a resolution to an apparent tension in the source document.

---

## Section 7 — User Stories

> **[Deferred — not authored in this Phase 0 BA pass.]** Per the orchestration prompt's pipeline mapping, FR/NFR → INVEST user story decomposition with WSJF prioritisation is `scrum-master-agent`'s Phase 6 responsibility (`user-story-mapping-core`), not a Phase 0 BA deliverable under this task's scope. Section 7 is left as a placeholder for Phase 6, not for product-manager-agent.

---

## Section 8 — Product Roadmap

*Authored by `product-manager-agent` (Phase 0.1b), merged 2026-09-04.*

Task framing offered a candidate cut (router + harness + SDLC engine + Go CLI + compiled corpus) as "defensible." I evaluated it rather than accepting it, using the Kano classification `product-management-core` distinguishes: **Must-be** features (utility asymptote — their absence is a hard failure, U → −∞; their presence is merely expected, not delightful) versus **Attractive** features (concave S-curve — value scales with investment but absence is not a failure).

**Must-be, therefore in MVP — because their absence makes the product not-the-product:**
1. **Compiled corpus + code-generation build (ADR-3)** — Must-be. This is the entire primary differentiator from §1. Without it, LordCode is a CLI shell with no claim to make. There is no partial version of this that is coherent: either the library is compiled in and validated at build time, or the product's positioning statement is false.
2. **SDLC pipeline engine (ADR-7), at least a hardcoded phase sequence with real gates** — Must-be. This is the second differentiator. A cut that ships the corpus but dispatches ad hoc (no phase gates, no consensus BINARY, no `RS` check) reduces to "a big prompt library," which is exactly the capability-without-process gap the positioning claim explicitly rejects.
3. **Multi-provider router, minimally rule-based cascade (ADR-1's cheapest topology)** — Must-be, but the *sophistication* of the router (bandit learning, embedding-similarity) is Attractive, not Must-be. The user-facing promise "connect the account you already have" (§5) fails entirely without *some* router; it does not fail if the router is a cascade rather than a Thompson-sampling bandit in v1.
4. **Go CLI surface (`cobra`/`viper`, per ADR-2)** — Must-be. There is no product without an invocable interface.
5. **Harness core: T_max bound + cumulative budget guard as mandatory stop disjuncts** — Must-be, not Attractive, and I am treating this more strictly than the candidate cut implied by grouping it under "harness." Per the orchestration prompt (component 3, and the "on token cost" note), these two stop conditions are what prevents a runaway 40–80-invocation pipeline from draining a user's provider account indefinitely. Shipping the SDLC engine without them is shipping a defect, not a smaller MVP — this is a FURPS+ Reliability NFR at CRITICAL severity and cannot be silently dropped to a fast-follower.

**Attractive, therefore fast-followers — value scales with investment, absence is not a failure:**
1. **Network-exposed multi-user daemon (ADR-6)** — Attractive with a caveat. ADR-6 is already RESOLVED as in-scope by the user, and multi-tenancy is Enterprise-complexity work (per-user authn/authz, per-user credential isolation, DPDP §4 context isolation). I am flagging — not overriding — a tension for `solution-architect` and Stop 1: the daemon is architecturally load-bearing for ADR-3's storage-form decision (per-daemon-start decompression) and for the Python eval-harness integration path (ADR-6's polyglot-split argument), so *deferring the daemon to a fast-follower is not free* — it removes a rationale ADR-3 currently leans on. My MVP recommendation is: **daemon architecture is designed in Phase 1 (so ADR-3 and the OpenAPI contract are not built twice), but daemon *implementation* (auth, rate limiting, multi-tenant persistence) can trail the single-user CLI into a fast-follower** without breaking the single-user product. This is a scope-sequencing recommendation for `solution-architect`, not a reopening of ADR-6.
2. **Full router sophistication (LinUCB/Thompson bandit, embedding-similarity, SPRT shadow-mode rollout)** — Attractive. A rule-based cascade routes correctly; a learning router routes better over time. Ship cascade first.
3. **Every provider adapter beyond the three named (OpenAI, Anthropic, Gemini)** — Attractive. The adapter *interface* must be provider-neutral from day one (ADR-1/ADR consequence, §100-107 of orchestration prompt) so a fourth provider is "write an adapter," not "redesign the contract" — but a fourth adapter itself is not MVP.
4. **Every router topology beyond the MVP cascade** — Attractive, explicitly named as such in ADR-1's own framing.
5. **Distribution breadth (ADR-5)** — Attractive. GitHub Release binaries are Must-be (there must be *a* way to get the binary); Homebrew/Scoop/apt/npm-wrapper channels are Attractive, added as adoption scales.

**Explicitly NOT reclassified, per binding constraints already settled and not reopened here:** monetization tiers (RESOLVED, out of scope, §OAQ-5), spend-ceiling/cost-approval gating (deliberately out of scope, not a "missing Must-be" — the `T_max`/budget-guard harness invariant already covers the runaway-safety concern that a spend ceiling would otherwise address), and corpus-refresh tooling (NEW-1, frozen library, no MVP or fast-follower need).

**FURPS+ note for `business-analyst-agent`/`solution-architect`:** the CRITICAL security NFRs (credential isolation, no telemetry of source/prompts, supply-chain posture) and the HIGH hallucination-risk NFRs (`RS = 1.0` at every gate) are Must-be by definition — Kano classification does not apply to them as a prioritization lever; they are non-negotiable per the CONSTRAINTS block regardless of MVP/fast-follower sequencing. I am not re-deriving them here — flagging so they are not accidentally swept into an "Attractive, defer" bucket by a later phase.

---

## Section 9 — Acceptance Criteria (index)

All Given/When/Then acceptance criteria are inlined directly under each FR in Section 5, per BDD rule: exactly one "When" per scenario, every "Then" independently observable without reading source code, no implementation detail (no HTTP status codes, table names, or CSS-selector-equivalents) in a "Then." A consolidated FR → AC-ID cross-reference:

| FR | AC ID(s) | Test Priority |
|---|---|---|
| FR-COR-001…006 | AC-FR-COR-001…006 | P1 |
| FR-RTG-001…007 | AC-FR-RTG-001…005 (RTG-006/007 covered by RTG-004/005 ACs above and Phase 1.5 contract tests) | P1 |
| FR-HRN-001…003 | AC-FR-HRN-001…003 | P1 |
| FR-SDL-001…005 | AC-FR-SDL-001…005 | P1 |
| FR-CTB-001 | AC-FR-CTB-001 | P2 |
| FR-CLI-001…004 | AC-FR-CLI-001…004 | P1 |
| FR-DAE-001…007 | AC-FR-DAE-001…007 | P1 |
| FR-AUT-001…007 | AC-FR-AUT-001…007 | P1 |
| FR-SEC-001…002 | AC-FR-SEC-001…002 | P1 |
| FR-UXA-001 | AC-FR-UXA-001 | P2 |
| FR-DPD-001…005 | AC-FR-DPD-001…005 | P1 |

---

## Section 10 — Out of Scope

| ID | Item | Rationale | Future Version? |
|---|---|---|---|
| OOS-001 | Model training or fine-tuning of any kind | "no training, no fine-tuning, Domain 22 (Foundation Model) out of scope for this build." Roadmap note only — see NFR-ARC-001 for the architectural constraint this imposes today. | Stated future direction, not committed |
| OOS-002 | LordCode-brokered inference billing / resale | OAQ-5: "BYO API key, free tool ... No LordCode-brokered billing, no payment surface." | Never (per current decision) |
| OOS-003 | Modifying `claude-global-library` | Two-path model: LIBRARY_PATH is read-only, never written to by this project. | Never |
| OOS-004 | A runtime corpus-update/refresh mechanism | NEW-1: "the library is frozen ... no corpus-refresh mechanism is in MVP scope." An overlay design is noted as a *future* ADR if the frozen assumption ever changes — not built now. | Possible future ADR, not v1 |
| OOS-005 | Pre-run spend ceilings / cost pre-approval prompts | "Do NOT build spend ceilings, pre-run cost approval prompts, or budget-gated execution as MVP features." | Not planned |
| OOS-006 | Distribution/packaging channel selection | OAQ-3 deliberately deferred to Phase 1 ADR-5 — not an OOS in the exclusion sense, but explicitly not decided at Phase 0. | Phase 1 |

---

## Section 11 — R&D Findings

*Authored by `technology-scout-analyst` (Phase 0.2). Full report with per-claim confidence levels and sources: [`tech_scout_report.md`](tech_scout_report.md).*

### 11.1 Competitive landscape (positioning read)

*Authored by `product-manager-agent` (Phase 0.1b), merged 2026-09-04.*

`technology-scout-analyst` is running a parallel, independent verification pass on these same competitors — this section states **positioning implications only** and marks everything not independently confirmed as an **assumption**, per the hallucination-detector review floor for this document.

| Dimension | Claude Code | OpenAI Codex CLI | Raw OpenRouter clients | LordCode |
|---|---|---|---|---|
| Agent/skill authoring | User writes custom slash-commands/subagents; no compiled specialist corpus ships by default *(assumption, based on public tool structure as of training cutoff — not independently re-verified for this document)* | Single-model coding-agent loop against user-authored prompts/config *(assumption — not independently verified for this document)* | Zero — a raw router library has no persona layer at all; this is a verifiable structural fact of what "raw OpenRouter client" means, not a claim about a specific product | 528 agents / 1034 skills compiled in, verifiable by build inspection |
| SDLC process per requirement | Task-scoped agent loop; does not claim a phase-gated SDLC pipeline as a product feature *(assumption)* | Single model loop, no stated multi-phase gate structure *(assumption)* | None — a router has no pipeline concept by definition | Phase 0–8/A–G/Ops.1–5 with real gates (ADR-7), verifiable by pipeline trace |
| Model/provider flexibility | Primarily Anthropic-model-oriented as shipped *(assumption — exact current multi-provider support not verified for this document)* | Primarily OpenAI-model-oriented as shipped *(assumption, same caveat)* | Maximal — this is a raw client's entire purpose, and is the one dimension where LordCode does not lead | Three first-class providers (OpenAI/Anthropic/Gemini) + adapter interface, connect-your-own-account |
| Distribution/runtime | Established CLI with existing user base *(assumption — no adoption numbers verified for this document)* | Established CLI with existing user base *(assumption, same caveat)* | Varies by client, not a single product | Not yet shipped — v1 is pre-launch; this is a real competitive gap, not spin |

**Honest read of where LordCode is behind, not just ahead (required by the CRITICAL-review floor — a positioning section that only lists advantages is not credible):**
- **Zero installed base and zero track record** against two established incumbents — the capability-completeness and full-SDLC claims are *architecturally* differentiating but currently *unproven at scale*; Phase 6 sprint planning and the README (§5) should not imply market traction that does not exist yet.
- **Raw OpenRouter clients beat LordCode on provider breadth in v1** (three named providers vs. an open router's "every provider on OpenRouter") — the counter-positioning is that LordCode trades that breadth for the compiled specialist layer and the SDLC engine neither raw client has, which is the actual bet, not a claim of superiority on every axis.
- **Second-tier Go provider SDKs (ADR-2's stated consequence)** mean LordCode may reach new provider capabilities (new tool-use features, prompt-caching helpers) weeks-to-months after a Python/TS-based competitor — this is a real, acknowledged cost of the Go decision and should not be hidden from the competitive assessment.

---

## Section 12 — India Regulatory Layer

India Regulatory Applicable: **YES**.

### 12.1 Applicable Regulations

| Regulation | Section | Obligation | Deadline | FR/NFR Reference |
|---|---|---|---|---|
| DPDP Act 2023 | §4 Purpose Limitation | Source code/prompt data used only for the requesting user's declared purpose | On launch | FR-DPD-002 |
| DPDP Act 2023 | §4 Consent | Explicit consent before third-party transmission | On launch | FR-DPD-001 |
| DPDP Act 2023 | §8(7) Auto-deletion | Automatic deletion of data past its retention period | On launch | FR-DPD-003 |
| DPDP Act 2023 | §11–§13 Data Principal rights | Access, correction, erasure mechanism | On launch | FR-DPD-005 |
| DPDP Act 2023 | §4 Purpose/context isolation (multi-tenant) | No cross-user data exposure on the daemon | On launch | FR-DAE-004, NFR-DPD-001 |
| CERT-In Directions 2022 | Incident reporting | 6-hour incident-reporting readiness for a network-exposed service | On launch | NFR-SEC-002 |
| CERT-In Directions 2022 | Log retention / credential handling | Auditable credential access, no secrets in logs | On launch | FR-SEC-002, FR-DAE-006 |
| RPwD Act 2016 | §40 | Terminal UX accessibility — contrast, NO_COLOR, screen-reader fallback | On launch | FR-CLI-004, FR-UXA-001, NFR-UXA-001 |
| GIGW | — | **Does not apply** — LordCode is not government-facing. Noted so no GIGW-derived requirement is mistakenly imposed. | N/A | N/A |

### 12.2 Compliance Requirements as FRs

Every regulation row above already has a corresponding FR or NFR in Section 5/6 — this PRD does not carry a DPDP/CERT-In/RPwD obligation without a matching testable requirement. No gap to flag in this pass.

### 12.3 India Pricing Considerations

> **Not applicable — confirmed by `product-manager-agent`.** OAQ-5 is RESOLVED: LordCode is a free, connect-your-own-account tool with no brokered billing and no payment surface, so there is no India pricing, GST, or invoicing consideration for the product itself. Provider-side costs (including 18% GST RCM on cross-border API invoices) are borne directly by the user under their own provider contract and are modelled only inside the router's cost objective, never billed by LordCode. Recorded explicitly rather than left silently absent.

---

## Section 13 — Open Questions

Per the orchestration prompt, the five Open Architectural Questions are **RESOLVED** (§2.3 above) and are deliberately not re-opened here. Phase 0 → Phase 1 handoff is **not blocked** by any unresolved question in this PRD.

| ID | Question | Owner | Blocking Phase 1? | Resolution |
|---|---|---|---|---|
| OQ-001 | Router topology (ADR-1) | solution-architect, Phase 1 | NO — this is a Phase 1 architecture decision, not a Phase 0 gap | Deferred to Phase 1 by design |
| OQ-002 | Credential storage mechanism detail (ADR-4) | solution-architect + security veto, Phase 1 | NO | Deferred to Phase 1 by design |
| OQ-003 | Distribution/packaging (ADR-5 / OAQ-3) | release-engineering-specialist, Phase 1 | NO — explicitly deliberate deferral | Deferred to Phase 1 by design |
| OQ-004 | SDLC engine: hardcoded vs. interpreted from decision-tree artifacts (ADR-7) | solution-architect, Phase 1 | NO | Deferred to Phase 1 by design |
| OQ-005 | Exact per-provider auth mechanism (OAuth device flow vs. API-key paste) for FR-AUT-001–007 | technology-scout-analyst, Phase 0.2 | **YES, informationally** — does not block Phase 1 HLD work, but FR-AUT wording should not be over-specified until this lands | Pending Phase 0.2 R&D |
| OQ-006 | Reconciliation of NFR-PERF-002's "cache-inflation directory" language against ADR-3's "no cache directory" corpus design (flagged in Section 6 footnote) | solution-architect, Phase 1 | NO — informational flag only | Flagged, not resolved by BA |

**Status:** ALL RESOLVED for Phase-0-blocking purposes (0 blocking questions); 2 informational items carried forward.

---

## Section 14 — RTM Skeleton

Modelled as a bipartite graph `G = (R ∪ T, E)` per `requirements-traceability-core` §2.1, where `R` is this PRD's FR/NFR set and `T` is the (not-yet-existing) Phase D test-case set. Per that skill's explicit instruction, the HLD Component and Test Case columns are left empty rather than fabricated — they are populated in Phase 1 and Phase D respectively.

### 14.1 Coverage reporting

Two distinct coverage measures are reported, because the classic RTM coverage ratio `CR = |{r ∈ R : deg(r) ≥ 1}| / |R|` (deg = downstream test-case links) is **not yet meaningful** at Phase 0 — no test cases exist yet, so every row's deg = 0 by construction, and reporting `CR = 0.0` would misrepresent an intentional skeleton state as a defect.

1. **Backward traceability coverage** (FR/NFR → source quote in `docs/orchestration_prompt.md`): **62/62 = 1.0** (48 FRs + 14 NFRs). Every FR and NFR in Sections 5–6 carries an inline quoted source. **Zero orphan requirements** by this measure — no FR/NFR in this PRD lacks a traceable origin in the orchestration prompt.
2. **Requirement-area coverage** (set-cover per `business-requirements-analysis-core` M4, against the explicit checklist of areas the Phase 0 task brief names): the 19 named areas — (a) capability completeness, (b) multi-provider routing + adapter interface, (c) harness/agent-loop runtime, (d) SDLC pipeline engine, (e) open contribution model, CLI command surface, multi-tenant daemon authn/authz, per-user credential isolation, per-user context isolation, rate limiting, terminal UX, RPwD §40 accessibility, credential/API-key handling, connect-your-account auth (connecting/listing/selecting/revoking + no-account fallback + subscription-vs-API distinction + precise error message), contribution governance, roadmap boundary/adapter-interface constraint, DPDP §4/§8 consent/purpose/retention/auto-deletion — are each covered by at least one FR or NFR above. **Coverage = 19/19 = 1.0.**

The **three CAPABILITY GAP REGISTER items** (Section 15) are not counted as coverage gaps in either measure above — they are a named finding about the *agent roster available to build LordCode*, not a gap in this PRD's requirement coverage of the *product*. Conflating the two would misstate what was actually found; Section 15 keeps them distinct on purpose.

### 14.2 RTM table (excerpt structure — full table mirrors Section 5/6 row-for-row)

| FR/NFR ID | Requirement (short) | Source | Priority | HLD Component (Phase 1) | Test Case (Phase D) | Status |
|---|---|---|---|---|---|---|
| FR-COR-001 | Compile corpus into Go source | orchestration_prompt.md, Component 1 / ADR-3 | M | TBD | TBD | Open |
| FR-COR-002 | Build-time hollow-persona check | orchestration_prompt.md, Component 1 / ADR-3 | M | TBD | TBD | Open |
| FR-COR-003 | Full SDLC per requirement | orchestration_prompt.md, Component 1 / NEW-3 | M | TBD | TBD | Open |
| FR-COR-004 | Routability audit report | orchestration_prompt.md, Phase 0 elicitation item | M | TBD | TBD | Open |
| FR-COR-005 | Version provenance stamp | orchestration_prompt.md, ADR-3 | M | TBD | TBD | Open |
| FR-COR-006 | Post-run per-phase cost display | orchestration_prompt.md, Component 1 | M | TBD | TBD | Open |
| FR-RTG-001…007 | Multi-provider routing set | orchestration_prompt.md, Component 2 / ADR-1 | M/S | TBD | TBD | Open |
| FR-HRN-001…003 | Harness/control-loop set | orchestration_prompt.md, Component 3 | M | TBD | TBD | Open |
| FR-SDL-001…005 | SDLC engine set | orchestration_prompt.md, Component 4 / ADR-7 | M | TBD | TBD | Open |
| FR-CTB-001 | External contribution path | orchestration_prompt.md, Component 5 | M | TBD | TBD | Open |
| FR-CLI-001…004 | CLI contract set | orchestration_prompt.md, Phase 1.5 / Phase 3 | M | TBD | TBD | Open |
| FR-DAE-001…007 | Daemon multi-tenant set | orchestration_prompt.md, ADR-6 | M | TBD | TBD | Open |
| FR-AUT-001…007 | Connect-your-account set | orchestration_prompt.md, Component 2 UX / careful area | M/S | TBD | TBD | Open |
| FR-SEC-001…002 | Credential storage/logging set | orchestration_prompt.md, ADR-4 | M | TBD | TBD | Open |
| FR-UXA-001 | Screen-reader fallback | orchestration_prompt.md, Phase 3 / RPwD §40 | M | TBD | TBD | Open |
| FR-DPD-001…005 | DPDP data-handling set | orchestration_prompt.md, CONSTRAINTS / Phase 0 elicitation item | M | TBD | TBD | Open |
| NFR-SEC-001…003, NFR-DAE-001…002, NFR-UXA-001, NFR-CTB-001…005, NFR-ARC-001, NFR-PERF-001…002, NFR-DPD-001 | Non-functional set | orchestration_prompt.md, CONSTRAINTS / ADR-6 / Component 5 | M/S | TBD | TBD | Open |

**RTM Completion Status:** Phase 0 (columns 1–5) — COMPLETE for this pass. Phase 1 (column 6) — pending `solution-architect`. Phase D (column 7) — pending `test-management-agent`.

**Traceability Health Index:** not computed at this phase — `TH = α·CR + β·TE + γ·(1−DL) + δ·TQS` requires test-effectiveness (TE) and dangling-link (DL) data that do not exist until Phase D. Recording `TH` now would produce a meaningless "Critical" reading purely from the skeleton's intentional emptiness, which is a known anti-pattern this skill warns against (`requirements-traceability-core` §9, "TQS-as-compliance shortcut" / decay-model misuse). Compute TH starting at the first post-Phase-D review.

---

## Section 15 — Capability Gap Register (honest finding)

Per the Phase 0 task brief's explicit instruction, the following three items from the orchestration prompt's CAPABILITY GAP REGISTER are recorded here as **named findings**, not smoothed over. They matter to this PRD specifically because they contradict — for the narrow case of *building LordCode itself* — the product's own headline claim that "nobody ever authors an agent or a skill again."

| Gap | Needed for | Nearest existing agent | Recommendation (from orchestration prompt) |
|---|---|---|---|
| CLI / TUI construction | Bubble Tea, cross-platform terminal quirks, Windows console behaviour, streaming render | `go-systems-engineer` covers the runtime and server, not the terminal surface | Author a `cli-tui-engineer`, or accept `go-systems-engineer` + `ui-ux-designer` covering it jointly with a documented seam |
| Cross-platform packaging & code signing | macOS notarization, Windows Authenticode, per-platform artifacts | `release-engineering-specialist` (exists — closest fit) | Probably sufficient; confirm at ADR-5 |
| Keychain / secure credential storage | OS keychain integration, headless fallback design | `secrets-detection-specialist` detects leaks but does not design storage; `crypto-security-specialist` covers primitives | Joint ownership: `solution-architect` proposes at ADR-4, `crypto-security-specialist` + `threat-modeling-specialist` review with veto |

**Why this belongs in the PRD, stated plainly:** LordCode's premise ("the complete capability set is already compiled in ... nobody ever authors an agent or a skill again") is true for LordCode's *users*, building *their* products. It is not currently true for the team building LordCode *itself* — three real capability gaps exist in the 528-agent roster for CLI/TUI construction, packaging/signing, and keychain design. This is not a blocker (the orchestration prompt names workable interim coverage for all three, above), but the PRD records it honestly rather than implying the roster is complete for every purpose, including its own construction. Traceability: these three rows are excluded from the coverage measures in §14.1 by design, per that section's explanation.

---

## Section 16 — Licence Recommendation

*Authored by `product-manager-agent` (Phase 0.1b), merged 2026-09-04.*

### Licence: **Apache License 2.0** — recommended over MIT and over a copyleft option

**The decision that actually matters here is not "permissive vs. copyleft" in the abstract — it's what kind of software LordCode is.** A permissive licence on a *library* mainly affects downstream redistribution terms. A permissive licence on a *tool that routes user source code to commercial third-party providers and runs a network-exposed multi-tenant daemon holding provider credentials* has different stakes: patent exposure across many external contributors, and the possibility of an unmodified or lightly-modified fork being redistributed — including as a hosted service — without any obligation to contribute improvements back or to disclose changes to users of that fork.

| Option | Patent grant | Fork-must-share-changes | Fit for a credential-handling, network-exposed dev tool |
|---|---|---|---|
| **MIT** | None | No | Simplest, most adoption-friendly, but a multi-contributor CRITICAL-security codebase with zero explicit patent grant leaves both the project and its users exposed to a later patent claim from a contributor or third party — a real risk once contribution is genuinely open, not merely hypothetical for an 84 MB, many-specialist corpus with many external contributors over time. |
| **Apache-2.0** (recommended) | **Explicit, express patent grant + patent-retaliation clause** (contributor who sues over patents loses their licence grant) | No | The patent grant is the deciding factor for a project explicitly courting external contribution (§5(b)) on security-sensitive code — it protects contributors *and* users without asking anyone to give up permissive redistribution rights. Still fully compatible with the BYO-account, no-brokered-billing monetization model already RESOLVED (OAQ-5) — nothing about Apache-2.0 constrains how LordCode is distributed or used commercially. |
| **AGPL-3.0** (copyleft, network-use triggers disclosure) | Yes (via GPLv3 lineage) | **Yes — including over-the-network use**, which is the relevant clause given ADR-6's network-exposed daemon | Would force any hosted fork of the daemon to publish its source, which is a genuine deterrent to a "someone stands up a competing hosted LordCode without contributing back" scenario. **Rejected for v1** because it also measurably deters the exact contribution openness §5(b) commits to — AGPL obligations are a known adoption friction point for external contributors and for any commercial user embedding LordCode in an internal tool, and the CRITICAL security review path (signed commits, mandatory maintainer review, Phase F.2 gates) already addresses the supply-chain risk that copyleft partially addresses by a different, less contributor-hostile mechanism. |

**Recommendation: Apache-2.0.** It is the licence that takes the CRITICAL security rating seriously (patent grant, patent retaliation) without contradicting the "open to contributions" commitment the way AGPL's network clause would. This is a decision for the user at Stop 1, not a default to silently apply — flagging explicitly that if a future strategic concern emerges (e.g., a well-resourced competitor forking the daemon into a competing hosted product without contributing back), AGPL is the documented fallback, not a closed question.

### Governance: BDFL-with-maintainer-council, not a foundation, for v1
A full foundation model (e.g., a formal steering committee, neutral legal entity) is premature — LordCode has zero installed base and zero contributor history at this stage (per §4's honest competitive read), and standing up foundation governance ahead of any actual community is overhead without a community to govern. A pure BDFL model, by contrast, under-resources the CRITICAL security review path: a single point of decision on security-relevant PRs is itself a security and continuity risk (bus factor of one, reviewing a credential-handling codebase).

**Recommendation:** BDFL (the project owner) retains final architectural authority and licence/governance changes, but **security-relevant review is delegated to a named maintainer council of ≥2** (minimum, so Phase F.2 gate overrides and credential-storage-adjacent PRs are never single-reviewed) drawn from whoever owns `security-lead-auditor`/`dependency-vulnerability-analyst` review responsibilities per the orchestration prompt's own assignment. Revisit toward a maintainer-team or foundation model once external contribution volume and installed base justify the overhead — this is an explicit, named future decision point, not an indefinite deferral.

**Reconciling openness with CRITICAL security (direct answer to the task's explicit ask):** openness applies to *what can be proposed* (any external contributor may open a PR); it does not apply to *what can be merged without review* (every PR, external or internal, passes signed-commit verification, mandatory maintainer review, and automated Phase F.2 static-analysis/secrets-detection before merge — per component 5 of the orchestration prompt, already binding). The licence and governance choices above are what make that review requirement *enforceable* rather than aspirational: Apache-2.0's patent grant protects the project from weaponized IP after review passes, and the ≥2-reviewer maintainer council prevents the review step itself from having a single point of failure.

---

## Cross-references for merge into PRD.md (business-analyst-agent)

- §2's Must-be/Attractive split should inform the PRD's FR/NFR priority tags — Must-be items map to `Priority: High` FRs, Attractive items are candidates for explicit `Phase: Fast-follower` tagging rather than omission.
- §3's NSM definition (SMS/AU/W) should be cited verbatim wherever the PRD references success criteria for Phase 6 WSJF scoring, so `ba-pm-mathematics-expert` has one canonical definition rather than re-deriving it.
- §6's Apache-2.0 recommendation and governance model are Stop-1 decisions for the user — the PRD should present them as an open decision point with this section's reasoning attached, not as settled fact, until the user confirms.

---

## Section 17 — README Narrative

*Authored by `product-manager-agent` (Phase 0.1b), merged 2026-09-04.*

Three explicitly required elements, written for `README.md` (subject to `rules/11-documentation-files.md` governance — this text is a draft for the required `## Overview`/`## Architecture` sections, to be merged, not a standalone file):

### (a) Any model, any account
> LordCode works with the model you already pay for. Connect an OpenAI account, an Anthropic account, a Google Gemini account — one, two, or all three — and LordCode routes each task to the right one. No LordCode subscription, no LordCode-brokered billing: `lordcode auth login <provider>` connects your own API credentials, and the router works with whatever you've connected. A user with only a Gemini account gets a fully working tool.
>
> **One thing worth knowing up front:** a consumer subscription (ChatGPT Plus, Claude Pro) is not the same as API access — those are billed and provisioned separately by each provider. LordCode needs an API key with credits, not a chat-app login, and will tell you exactly which one is missing if authentication fails.

*(This directly operationalizes the orchestration prompt's explicit warning in component 2 — "authentication failed" is called out there as a product-destroying error message, "your ChatGPT Plus subscription does not include API access" as the correct one. Restated here as committed README language, not left as an internal engineering note.)*

### (b) Open to contributions
> LordCode is open to contributions under [licence — see §6 recommendation]. See `CONTRIBUTING.md` for the PR review path. Because LordCode is a credential-handling tool, external contributions go through a hardened review: signed commits, mandatory maintainer review, and automated Phase F.2 static-analysis and secrets-detection gates on every PR before merge. This is not friction for its own sake — it's what "open source" has to mean for a tool that holds your provider credentials.

### (c) Own models — roadmap, not v1
> LordCode's own first-party models are a stated future direction, not a current feature. **Today, v1 routes exclusively to third-party providers you connect yourself** — there is no training or fine-tuning in this release, and Domain 22 (Foundation Model) work is explicitly out of scope for v1. The provider-adapter interface is designed so that a future first-party model is "add another adapter," not a rewrite — but that is a design constraint we're building toward, not a promise of what ships now.

**Product-honesty check (why the wording above is deliberate):** each of the three sub-sections above states the *current* scope in its first sentence and any future scope in a clearly separated, explicitly-labeled sentence. This is not a copywriting preference — it directly satisfies the task's product-honesty requirement that no reader mistake the roadmap item in (c) for a shipped v1 capability.

---

## Document Control

| Field | Value |
|---|---|
| Generated by | business-analyst-agent (Sections 2–7 partial, 9–10, 12–15 complete) |
| Pending from | product-manager-agent (Sections 1, 3, 8, 11, 16, 17; Section 12.3 confirmation) |
| Verified by | hallucination-detector + context-faithfulness-engineer — **PENDING**, not yet run |
| NLI Score | pending |
| FactScore | pending |
| Faithfulness Score | pending |
| Hallucination Gate | PENDING |
| Pipeline Phase | Phase 0 |
| Source document | `docs/orchestration_prompt.md`, 2026-09-04 revision |
| Library Version | v29.96.2, built 2026-08-29 |
| Save Path | `docs/phase-0-requirements/PRD.md` |
| FR count | 48 (COR 6, RTG 7, HRN 3, SDL 5, CTB 1, CLI 4, DAE 7, AUT 7, SEC 2, UXA 1, DPD 5) |
| NFR count | 14 (SEC 3, DAE 2, UXA 1, CTB 5, ARC 1, PERF 2, DPD 1) |
| Total FR + NFR | 62 |
| Backward traceability CR | 1.0 (0 orphan FR/NFR) |
| Requirement-area coverage | 19/19 = 1.0 |
| Capability gaps recorded | 3 (excluded from coverage measures by design — see §15) |
