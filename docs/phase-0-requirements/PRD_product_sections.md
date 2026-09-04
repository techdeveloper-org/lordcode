# LordCode — Product Sections (Positioning, MVP, Metrics, Competitive Landscape, README Narrative, Licence)

> Authored by `product-manager-agent`. This file is merged into `PRD.md` (owned by `business-analyst-agent`) — do not treat this as the canonical PRD on its own. Source: `docs/orchestration_prompt.md`, PRE-FLIGHT RESOLUTION table, ADR-1..7, CAPABILITY GAP REGISTER.

---

## 1. Positioning

**LordCode is not another AI coding CLI competing on model quality. It is the only one that ships the specialist workforce instead of asking the user to build one.**

Two differentiators, stated as testable claims rather than adjectives:

### Primary — capability completeness
LordCode compiles the complete `claude-global-library` corpus — **528 agents, 1034 skills, 104 domain knowledge graphs, 77 math masters, 9,146 typed edges** (84.3 MB raw / 24.7 MB gzip, verified on disk 2026-09-04, source: `knowledge-graph/_master/README.md`) — directly into the Go binary via code generation (ADR-3). This is testable: `lordcode agents list` must return all 528 by name; `lordcode --version` must report the compiled library version stamp (`v29.96.2`); and a build with a dangling `skills:` reference must fail to compile, not fail silently at dispatch time. A user of a competing tool who wants a security-review specialist or a WSJF-scoring specialist has to *write that prompt themselves*. A LordCode user does not, because the specialist and its skill are already compiled in.

### Second — full-SDLC-per-requirement, not one model loop
Give Claude Code or Codex CLI a requirement and you get one model loop against your own prompt. Give LordCode a requirement and it runs the pipeline the library itself defines — Phase 0 requirements → architecture with real ADRs → a BINARY consensus gate → domain implementation → anti-hallucination verification (`RS = 1.0`) → QA → Phase F security (all severities zero) → reliability (`RS` computed) → Ops readiness — realistically **40–80+ specialist invocations per requirement** (`docs/orchestration_prompt.md`, NEW-3). This is also testable: a LordCode run produces an artifact trail (PRD → HLD → SRS → UML → sprint plan → code → security report) that a single-model-loop competitor structurally cannot produce, because it has no phase-gated pipeline to produce it *from*.

**What this claim does NOT say (guarding against overclaim):** LordCode does not claim its underlying models are more capable than a competitor's — model quality is a routing decision (ADR-1), not a LordCode-authored capability. The claim is about **process completeness and specialist coverage**, which is independently verifiable by inspecting the compiled corpus and the pipeline trace of any run. This distinction matters for the README narrative in §5 and for `hallucination-detector`'s review of this document: do not let "528 agents compiled in" imply "528 agents are always invoked" — NEW-3 and the orchestration prompt are explicit that a requirement runs only the specialists its domain calls for (40–80+ is realistic per requirement, not 528 per requirement).

---

## 2. MVP Cut — Kano-classified, own reasoning

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

## 3. Success Metrics and North Star Metric

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

---

## 4. Competitive Landscape

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

## 5. README Narrative

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

## 6. Licence Recommendation and Governance

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
