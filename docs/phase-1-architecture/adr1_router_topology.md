# ADR-1 — Multi-Provider Router Topology

**Status:** PROPOSED (Phase 1 decision — per `docs/orchestration_prompt.md` ADR-1 register, "OPEN, Phase 1 decides")
**Author:** multi-model-router-architect
**Date:** 2026-09-04
**Consumers:** solution-architect (HLD integration), harness-engineering-architect (Alignment 1 handoff), go-systems-engineer (implementation), genai-routing-mathematician (math validation — delegated derivations below), security-lead-auditor (Phase F review of credential/circuit-breaker design)
**Depends on / must not contradict:** ADR-2 (Go, RESOLVED), ADR-3 (compiled corpus, RESOLVED), PRD.md §5.2 (FR-RTG-001…007), §5.8 (FR-AUT-001…007), §5.4 FR-SDL-005, Team Alignment 1 and 7 (`docs/orchestration_prompt.md` STEP 10.5)

---

## 1. Context

LordCode dispatches 40–80+ specialist-agent invocations per user requirement (NEW-3). For **each individual invocation**, something must pick which of the user's *configured* providers (OpenAI, Anthropic, Google Gemini, plus an open adapter interface — FR-RTG-001) executes it. This is the router's entire job. Per Alignment 7, this decision is strictly orthogonal to *which agent* the SDLC pipeline engine dispatches — the router never influences agent selection, and agent selection never influences model selection except through the resulting task's capability-requirement vector.

Three facts specific to LordCode constrain which of the four candidate topologies (multi-model-routing-core §2.1) is viable, and none of them are optional preferences — they come from decisions already locked elsewhere in this project:

1. **No historical routing data exists at launch.** The library corpus is frozen (NEW-1) and `lordcode` is a greenfield repository (zero commits). A topology that requires supervised training data (classifier router) or that only pays off after significant online exploration (LinUCB/Thompson bandit) starts from zero and must either ship broken on day one or ship with a separate warm-start mechanism this ADR does not have license to invent unilaterally.
2. **The action space is small — at most 3 first-class providers, occasionally more via the open adapter.** LinUCB's `O(d√T log T)` regret advantage over a static policy is a function of learning across many arms and many rounds; multi-model-routing-core §4.1 frames the bandit's value proposition around *catalog-scale* model pools. A 2–4-arm pool with a well-characterized, already-compiled capability vector per arm (model-capability-profiling-core §4) has much less to learn online.
3. **The harness requires deterministic replay (FR-HRN-001) and a real, non-estimated cost/model answer per invocation (FR-HRN-002).** A routing policy whose *decision procedure* depends on a live, updating parameter state (bandit posterior/estimate) is harder to make auditable than a policy whose decision procedure is a static, inspectable ranking function evaluated against point-in-time inputs (health, cost, circuit-breaker state). Replay in this ADR's design means replaying the **recorded decision inputs and outputs** (§7), not recomputing a live policy — but a deterministic ranking function makes that record trivially self-explanatory, where a bandit's arg-max over an evolving posterior requires also snapshotting and replaying the exact posterior state.

Constraint carried over from `docs/orchestration_prompt.md` ADR-1 register, restated for this document as a **hard constraint, not a recommendation**: any router that requires on-device numerical work (embedding generation, matrix operations, cosine similarity over dense vectors) triggers ADR-2 reopening, because Go's standard toolchain has no numpy/torch-equivalent tensor library. That constraint is evaluated explicitly for Candidate 4 in §2.

---

## 2. Candidates Considered — Quantified Tradeoffs

All latency and regret figures below are cited from `multi-model-routing-core` §2.1's architecture comparison table and are not re-derived here.

| # | Topology | Added latency | Learning | Training/data requirement | Cold-start fit for LordCode | Determinism for replay |
|---|---|---|---|---|---|---|
| 1 | **Rule-based cascade** | ~0 ms | None | None — uses compiled DNA vectors + point-in-time cost/latency/health | **Works day one** | Fully deterministic given point-in-time inputs |
| 2 | **Embedding-similarity KNN** | ~5–20 ms | Few-shot | Labeled exemplar set per candidate model | Needs an initial exemplar set LordCode does not have | Deterministic, but **triggers ADR-2 reopening** (§2.4) |
| 3 | **Classifier router** | ~10–50 ms | Supervised | A trained task→model classifier, requiring historical routing outcomes | **Blocked** — no training data exists at launch | Deterministic given a frozen classifier, but the classifier itself needs periodic retraining LordCode has no data pipeline for |
| 4 | **LinUCB / Thompson bandit** | Adaptive (comparable to cascade once trained) | Online, per-round | None upfront, but **regret is paid during exploration** | Works day one but **spends real user cost on exploration** before converging | Requires posterior-state snapshotting to replay a decision, not just the outcome |

### 2.1 Cascade (Candidate 1) — cascade break-even, applying the pre-derived formula

Per `multi-model-routing-core` M3 (`E[cost_cascade] = c_1 + Σ c_i × Π(1-q_j)`), the two-model break-even condition is:

```
E[cost_cascade] < c_expensive
⟺ c_cheap / c_expensive < q_cheap
```

`docs/orchestration_prompt.md`'s own ADR-1 register cites the worked illustrative ratio: **at a price ratio of 0.067, cascade is profitable whenever the cheap tier's acceptance rate q₁ exceeds 6.7%.** This is the only concrete break-even number this ADR asserts, because it is sourced directly from the orchestration prompt rather than invented here. **This ADR does not fabricate current 2026 per-token pricing for OpenAI/Anthropic/Gemini tiers** — Phase 0.2's `technology-scout-analyst` R&D pass has not yet verified current pricing tables for all three providers with PRIMARY sources (the same discipline `research_synthesis_round2.md` enforces for every other unverified claim in this project — no grade above what the evidence supports). **Delegated to genai-routing-mathematician:** recompute the exact break-even ratio and `q_cheap` threshold per real provider/tier pairing once `technology-scout-analyst` supplies verified 2026 pricing; this ADR's qualitative conclusion (cascade is favorable whenever the cheap tier clears single-digit-percent acceptance, which is realistic for the majority of LordCode's routine specialist invocations — documentation formatting, boilerplate scaffolding, style-only fixes) does not depend on the exact figure.

Cascade's other decisive property for LordCode specifically: it needs **no training data and no exploration budget** to be correct on day one, because its ranking is driven by the already-compiled, already-verified DNA capability vectors (model-capability-profiling-core §4) plus live cost/latency/health signals — not by learned parameters.

### 2.2 Classifier (Candidate 3) — rejected

Requires a labeled corpus of (task, provider, outcome) triples to train against. LordCode has none at launch, and NEW-1 (frozen library) means there is no library-side mechanism to backfill one. Building a classifier from LordCode's own post-launch telemetry is a legitimate v2 direction but is out of scope for this ADR — see §9.

### 2.3 LinUCB / Thompson bandit (Candidate 4) — rejected for v1, not because the math is wrong

The bandit's `O(d√T log T)` regret bound (multi-model-routing-core §4.2, M1) is real and its advantage compounds with catalog size and round count. Neither compounds favorably here: the catalog is 2–4 arms, and per-invocation exploration risk is not free in a product whose HIGH hallucination-risk floor targets `RS = 1.0` — an exploratory routing decision that sends a Phase F security-sensitive invocation to an under-tested arm to gather regret-bound data is misaligned with **Alignment 3** (security holds veto over anything touching the CRITICAL-risk surface) and with `NFR-SEC-001`'s zero-Critical/High-finding gate. **Explicit delegation, not a self-derived verdict:** genai-routing-mathematician should compute the actual expected regret over LordCode's realistic per-user invocation volume (order-of-magnitude: tens to low hundreds of invocations per user per week, not the T=10,000-round regime multi-model-routing-core's M1 worked example assumes) to confirm whether the bandit's asymptotic advantage is even reached within a typical user's usage horizon — this ADR's rejection is a structural/product-risk argument (exploration cost on a HIGH-hallucination-risk surface with no cold-start data), not a claim that the regret bound itself is unfavorable.

**Recorded as a v2 candidate, not discarded:** once §9's telemetry accumulates real (task-type, provider, RS-outcome, cost) triples, a LinUCB layer *on top of* the cascade's static ranking (using the cascade score as the bandit's prior/warm-start, per `multi-model-routing-core` §6.4's hybrid pattern — "pre-train offline; fine-tune online") becomes viable and should be re-evaluated in a future ADR.

### 2.4 Embedding-similarity KNN (Candidate 2) — rejected, and the ADR-2 reopening cost is stated explicitly per this ADR's binding constraint

Embedding-similarity routing needs either (a) an embedding API call on the routing hot path — adds a fourth provider dependency and network latency to *every one* of 40–80+ invocations, which is a real cost multiplier on a product whose own harness must bound `T_max` per invocation, or (b) build-time-precomputed persona/task exemplar vectors with hand-rolled cosine similarity at runtime. Option (b) is tractable in pure Go — cosine similarity is dot products and norms, no tensor library required — but it still means:
- **ADR-2 must be formally reopened** per this project's own stated trigger ("if ADR-1 lands on embedding-similarity or anything requiring on-device numerical work, ADR-2 must be reopened" — `docs/orchestration_prompt.md` ADR-1 register). This ADR does not select this path and therefore does not trigger that reopening.
- It requires an exemplar set (labeled task→model examples) with the same cold-start gap as the classifier (§2.2).
- With only 2–4 candidate arms, cosine similarity over exemplars adds implementation and maintenance cost without a clear win over a directly-computed capability-alignment score that model-capability-profiling-core already defines (`cos(R_t, DNA_m)`, §6.2/M3) — the *same* cosine-similarity math, but applied to the already-compiled DNA vectors instead of a learned exemplar set. This ADR's recommendation reuses that formula directly (§3) without adopting embedding-similarity's KNN/exemplar machinery around it.

**Conclusion: rejecting Candidate 2 does not reopen ADR-2.** No candidate selected by this ADR requires on-device tensor operations beyond dot products over already-compiled fixed-length vectors, which is ordinary Go arithmetic.

---

## 3. Decision

**LordCode adopts a DNA-score-ranked rule-based cascade (Candidate 1) as ADR-1's router topology for v1**, using model-capability-profiling-core's composite routing score to *rank* the cascade rather than a flat cheapest-first FrugalGPT ordering, and using its cosine-similarity capability-alignment score (§6.2, M3) as the θ_min filter (§4).

For each agent invocation:

1. **Filter** the candidate set to providers the user has configured (FR-RTG-002) whose circuit breaker (§5) is not `OPEN`, whose model clears the θ_min = 0.60 capability floor (§4) for the invocation's task requirement vector, and whose model's **effective** (not advertised) context covers the invocation's token footprint (§6).
2. **Rank** the surviving candidates by the composite score `S(m,t) = α·S_cap(m,t) + β·S_cost(m) + γ·S_lat(m)` (model-capability-profiling-core §7 M5), with per-use-case weights drawn from that skill's use-case weight table (§7 M5 Step 3) keyed to the invoking agent's declared latency/cost sensitivity (e.g., an interactive terminal-facing agent uses the "Interactive user-facing" row `α=0.5, β=0.1, γ=0.4`; a batch Phase D test-generation agent uses "Cost-sensitive batch pipeline" `α=0.3, β=0.6, γ=0.1`).
3. **Dispatch** to the top-ranked candidate. This is the cascade's "cheap" hop for cost-sensitive task classes, or the highest-capability hop for quality-sensitive task classes — the DNA-ranked ordering, not a hardcoded "always cheapest first," is what makes this a *capability-aware* cascade rather than a naive cost-only FrugalGPT cascade.
4. **Score the response's confidence** via the invoking agent's downstream quality signal (§4) and **escalate** to the next-ranked candidate if the confidence gate rejects it, up to the full ranked list; if every ranked candidate is exhausted, the invocation fails loudly with the exhausted candidate list recorded (§8 defines the only two legitimate "fail loudly" conditions).

This is not FrugalGPT's literal cheapest-model-first cascade — it is a **capability-DNA-ranked cascade with a confidence-gated escalation ladder**, which is the correct adaptation given that LordCode's specialist agents have genuinely different, DNA-profile-driven quality requirements per invocation (a `threat-modeling-specialist` invocation and a `documentation-formatter`-class invocation should not share one static cost-first ordering).

**Per Alignment 7:** this ranking-and-selection procedure runs once per agent invocation, is entirely orthogonal to which agent the SDLC pipeline engine dispatched, and never influences that dispatch decision.

---

## 4. Confidence Gate Design

### 4.1 Threshold derivation — applying the pre-derived formula, not re-deriving it

Per `multi-model-routing-core` §5.3 / M4, the decision-theoretic optimal escalation threshold is the confidence value where:

```
h(τ*) = (C_loss + C_esc) / (R + C_loss)
```

where `h(τ*) = P(quality_high | confidence = τ*)` is the calibration curve, `C_esc` is the marginal cost of escalating to the next-ranked candidate, `C_loss` is the penalty for serving an incorrect/incomplete output at the cheap hop without escalating, and `R` is the value of a correctly-answered invocation.

**This ADR does not invent numeric values for `C_loss`, `C_esc`, or `R`.** It defines the **structure** LordCode uses to set them, per risk class, and delegates the numeric calibration to genai-routing-mathematician once empirical quality-vs-confidence data exists (cold start: expert-elicited priors, revised from telemetry per §9):

| Risk class | Representative invocations | `C_loss` relative weighting | Resulting `τ*` behaviour |
|---|---|---|---|
| **Security/hallucination-critical** | Phase F agents (`threat-modeling-specialist`, `sast-engineer`, `secrets-detection-specialist`), `hallucination-detector`, `context-faithfulness-engineer`, `reliability-auditor` | `C_loss` set high relative to `C_esc` (a missed vulnerability or an unfaithful claim propagates through the whole RS=1.0 gate chain) | `h(τ*) → C_loss/(R+C_loss)`, i.e. **high threshold** — escalate unless confidence is very high that the cheap hop suffices |
| **Architecture/consensus-gated** | `solution-architect`, `consensus-agent`-reviewed outputs | Moderate-high `C_loss` (rework cost if wrong, but caught by a downstream BINARY gate rather than shipping silently) | Moderate-high threshold |
| **Routine/boilerplate** | Documentation formatting, style-only fixes, sub-task scaffolding that a downstream gate will still verify | `C_esc` matters relatively more (escalation cost is real, correctness risk is lower and cheaply caught) | Lower threshold — accept the cheap hop's answer more readily |

This is a genuine consequence of the formula, not a heuristic bolted on afterward: multi-model-routing-core §5.3 states explicitly that when `C_esc << C_loss`, `h(τ*) ≈ C_loss/(R+C_loss)` (a quality-driven, high threshold), and the inverse when `C_esc` dominates. Mapping LordCode's own risk-class taxonomy (already implied by the CONSTRAINTS block's HIGH hallucination-risk / CRITICAL security-risk designations) onto that formula is the correct, non-arbitrary way to stratify `τ*` per invocation class rather than picking one global scalar by feel — which multi-model-routing-core §10's anti-pattern list explicitly warns against ("picking an escalation threshold τ by intuition instead of the decision-theoretic derivation").

### 4.2 Confidence scoring mechanism

Per multi-model-routing-core §5.1/§5.2, the correct confidence signal depends on what the selected provider exposes:
- If the provider exposes token log-probabilities: `Confidence(a) = exp(mean_log_prob_of_response_tokens)`, temperature-scaled against LordCode's own held-out calibration set (ECE minimization, §5.1) — **never used raw/uncalibrated**, per the skill's own anti-pattern warning.
- If the provider does not expose log-probabilities (this varies by provider and by streaming mode — verified per-provider capability is a `technology-scout-analyst` R&D item, not asserted here): fall back to self-consistency (K≥5 samples) or, for gate-adjacent invocations that already produce a structured verdict (e.g., a Phase F finding list), a lightweight structured-output completeness check as a proxy signal, calibrated the same way.

**This is explicitly flagged as an open implementation detail for Phase 1.5's provider-adapter contract**, not resolved here: which of the three named providers exposes logprobs, under which API modes, is unverified and must not be asserted by this ADR without a primary source (consistent with `research_synthesis_round2.md`'s discipline on ungrounded provider-capability claims).

### 4.3 θ_min = 0.60 enforcement

Per model-capability-profiling-core §7 M5 Step 4 and this ADR's persona-level hard floor: `θ_min = 0.60` is enforced as a **pre-filter, not a soft ranking signal**. Before the cascade ranking step (§3.2) ever runs, every candidate `m` with `S_cap(m,t) = cos(DNA_m, R_t) < 0.60` is removed from the candidate set entirely. This is deliberately a hard cut, not a weighted penalty inside `S(m,t)` — model-capability-profiling-core §6.3 states the reason directly: "θ_min prevents routing to a very cheap model that doesn't meet minimum capability requirements," and §9's anti-pattern list warns against "selecting the argmax model without enforcing the minimum-compatibility floor," where a cheap model's cost-adjusted score can win purely on price even below the capability floor. If the θ_min filter empties the candidate set (every configured provider's every model falls below 0.60 for this task's requirement vector), that is one of the two legitimate hard-failure conditions in §8.

---

## 5. Per-Provider (and Per-Model-Tier) Circuit Breakers

Per this ADR's binding persona-level requirement and PRD `FR-RTG-004`, **every model in the pool gets its own circuit breaker — never one global breaker.** Concretely, LordCode instantiates one circuit breaker per `(provider, model-tier)` pair (e.g., `openai/gpt-4o`, `openai/gpt-4o-mini`, `anthropic/claude-*`, `google/gemini-*`), not merely one per provider, because a provider can have one tier degraded (e.g., a specific model experiencing elevated 5xx rates) while its other tiers remain healthy — collapsing to a per-provider breaker would incorrectly fast-fail a healthy tier alongside a degraded one.

**Configuration**, per `api-orchestration-stack-core` §3.1 and this ADR's persona-level mandate:

```
CLOSED  → OPEN:        failure_rate ≥ 0.50 over a 60-second sliding window, with request_count ≥ min_requests (recommend min_requests = 10, per api-orchestration-stack-core §3.1's typical default)
OPEN    → HALF_OPEN:   after a 30-second wait_duration
HALF_OPEN → CLOSED:    limited_probe_calls succeed at ≥ success_threshold
HALF_OPEN → OPEN:      any probe fails; timer resets
```

Window type: **time-based, not count-based** (api-orchestration-stack-core §3.2) — LordCode's per-user, per-provider request rate varies enormously (idle between sessions, then 40–80 invocations in a burst during one pipeline run), and a count-based window would trip on a small absolute failure count during a quiet period or fail to trip fast enough during a burst. A time-based 60-second window represents the recent failure proportion correctly regardless of that variance.

**Why one global breaker is wrong here, stated explicitly (task requirement):** LordCode's entire multi-provider value proposition (FR-RTG-002: "a user with only one of the three providers configured shall receive a fully working tool") depends on one provider's degradation *never* blocking routing to the user's other configured, healthy providers. A single global breaker would trip on the *aggregate* failure rate across all configured providers — meaning a single struggling provider drags down routing decisions for invocations that were never going to touch it, and a healthy provider becomes unreachable because an unrelated provider is failing. Per-provider (per-tier) breakers are precisely what preserves FR-RTG-002 and FR-RTG-004's "one provider's outage does not block routing to the user's other configured providers" under load. `api-orchestration-stack-core`'s own reference implementation (§3.3) is structured exactly this way — a `ProviderPool` holding one `CircuitBreaker` instance per provider — and this ADR adopts that pattern directly, extended to per-tier granularity for the reason above.

**Steady-state math, delegated correctly:** the Markov steady-state `P(OPEN) = μ_CO / (μ_CO + μ_OC)` (api-orchestration-stack-core §10 M2) is available to compute expected time-in-OPEN for capacity/UX planning (e.g., "how often will a user with only OpenAI configured see fallback-exhausted errors if OpenAI's failure rate sits at 60% for an extended period"). **This ADR does not compute LordCode-specific `μ_CO`/`μ_OC` values** — those depend on real per-provider failure-rate distributions this project has not yet measured. Delegated to genai-routing-mathematician once `technology-scout-analyst` / production telemetry supplies real failure-rate data.

**Non-retryable vs retryable errors** (api-orchestration-stack-core §2.1, §3.3): a 400/401/403/404/422 from a provider is **not** a circuit-breaker-relevant failure and must not be retried as-is or trigger a breaker trip — those indicate a malformed request or bad credential (the exact FR-AUT-006/007 case: a consumer-subscription token presented as an API credential), and the correct response is the FR-AUT-007 precise error message, not provider fallback. Only 429/503/504/timeout-class errors count toward the failure-rate window.

---

## 6. Effective-Context-Aware Routing

Per `context-decay-analysis-core` §1.1 and this ADR's binding mandate ("never route a long-context request to a model whose EFFECTIVE — not advertised — context covers it"), the θ_min filter step (§4.3) is joined by a second, independent pre-filter, evaluated before ranking:

1. **Classify the invocation's task type** against the RULER taxonomy families (context-decay-analysis-core §1.3/§4.1): single-retrieval, multi-hop/aggregation, or general QA-with-distractors. A specialist agent reading and reasoning across multiple existing source files (e.g., `codebase-archaeology-agent`'s call-graph work, or a multi-file refactor) is multi-hop/reasoning-class, not retrieval-class — the effective-context gap for reasoning tasks is **4×–8× the advertised window**, materially worse than retrieval's 2×–4× gap (context-decay-analysis-core §1.1, §4.4).
2. **Compute the invocation's required token footprint** (source files + prior pipeline context + expected output) from the harness's own context-budget accounting (per Alignment 6's layering, this is a harness-owned measurement the router consumes, not recomputes).
3. **Reject candidates whose effective context for that task class** — read from the compiled per-model effective-context reference (context-decay-analysis-core §4.4's model table, refreshed by `technology-scout-analyst` as provider models change; this ADR does not assert current numeric effective-context values for specific 2026 model versions, since that table decays over model-version time and must be independently verified, not asserted from this ADR alone) — is below the required footprint.
4. **Apply the 0.5× Indic correction factor** (context-decay-analysis-core §9.1/§9.4) when the invocation's source content is detected as containing Indic-script text — a directly relevant case for LordCode given DPDP-covered Indian users whose source code may carry Hindi/Tamil/other Indic-script comments, string literals, or commit messages. Skipping this correction for an Indic-content invocation would silently overestimate how much of the file the model can actually use, per the skill's own anti-pattern warning (§10, "applying English effective-context estimates to Indic-language content unadjusted").

If the effective-context filter empties the candidate set (every configured provider's every model's effective context, task-class- and Indic-adjusted, is insufficient for this invocation's footprint), that is the second legitimate hard-failure condition in §8 — and the correct harness-level response is very likely a request to `context-engineering-agent`/the harness to chunk or compress the input (LLMLingua-2, per context-decay-analysis-core §7, is available at up to 5× compression within the `F(r) ≥ 0.95` faithfulness bound) rather than a router-level failure the user sees directly. This chunking/compression decision is **out of this ADR's scope** — it belongs to the harness/context-engineering layer per Alignment 6's layering, and this ADR only specifies that the router must detect and report the insufficiency, not that it must resolve it.

---

## 7. Router → Harness Handoff Data Structure (Alignment 1)

Per Alignment 1 ("the router produces a model+provider selection PER TASK... solution-architect MUST specify the exact handoff data structure in the HLD — leaving it implicit is how this seam rots"), this ADR specifies the structure the router hands to the harness for each invocation. This record is what makes FR-HRN-001's deterministic replay and FR-HRN-002's "real, replayable answer" possible without recomputing a live policy state — replay means replaying *this record*, not re-running the ranking function against possibly-changed live inputs.

```json
{
  "invocation_id": "uuid",
  "requirement_id": "uuid",
  "sdlc_phase": "F.1",
  "dispatched_agent": "threat-modeling-specialist",
  "routing_decision": {
    "topology": "dna-ranked-cascade-v1",
    "task_requirement_vector_R": [0.70, 0.60, 0.40, 0.20, 0.10, 0.80, 0.30, 0.20, 0.20, 0.50],
    "candidate_pool_before_filters": ["openai/gpt-4o", "openai/gpt-4o-mini", "anthropic/claude-*", "google/gemini-*"],
    "theta_min_filter": {
      "threshold": 0.60,
      "excluded": [{"model": "...", "S_cap": 0.0, "reason": "below_theta_min"}]
    },
    "effective_context_filter": {
      "task_class": "multi_hop_reasoning",
      "required_tokens": 0,
      "indic_correction_applied": false,
      "excluded": [{"model": "...", "effective_ctx_tokens": 0, "reason": "insufficient_effective_context"}]
    },
    "configured_provider_filter": {
      "user_configured_providers": ["google/gemini-*"],
      "excluded_unconfigured": ["openai/gpt-4o", "anthropic/claude-*"]
    },
    "circuit_breaker_filter": {
      "excluded_open": []
    },
    "ranked_candidates": [
      {"model": "google/gemini-*", "S_cap": 0.71, "S_cost": 0.55, "S_lat": 0.60, "S_composite": 0.65, "weights_used": {"alpha": 0.5, "beta": 0.1, "gamma": 0.4}}
    ],
    "selected": {"provider": "google", "model": "gemini-*"},
    "substitution": {
      "occurred": true,
      "top_ranked_before_substitution": "anthropic/claude-*",
      "unavailable_reason": "unconfigured_provider"
    },
    "confidence_gate": {
      "risk_class": "security_critical",
      "threshold_tau_star": 0.0,
      "observed_confidence": 0.0,
      "escalated": false,
      "escalation_chain": []
    },
    "cost_estimate_usd": 0.0
  },
  "decided_at": "ISO-8601 timestamp",
  "router_topology_version": "dna-ranked-cascade-v1"
}
```

**Binding properties of this record, per Alignment 1:**
- It is **immutable and final for that invocation's execution** once emitted. The router never re-invokes itself mid-loop against this same `invocation_id`.
- **Re-routing happens only in two cases**, both explicitly sanctioned by Alignment 1: (a) a genuinely new invocation (new `invocation_id`), or (b) an explicit harness-triggered circuit-breaker fallback mid-execution — which the harness requests as a *new* routing call (a fresh record with a new `decided_at`, referencing the prior `invocation_id` as `fallback_from`), not a mutation of the original record.
- `substitution` is populated whenever §8's degrade-to-best-available path fires, satisfying PRD `AC-FR-RTG-004`'s audit-trail requirement verbatim.
- This record is exactly what `FR-HRN-002` needs to answer "which model executed invocation #7 and what did it cost" without an estimate — every field is a decided, recorded fact, not a live recomputation.

---

## 8. Partial-Account Case — Degrade to Best-Available, Not Fail Loudly (Except Two Named Cases)

**This is not an open design choice this ADR is free to invent — it is already a MUST requirement in the approved PRD**, and this ADR's job is to state the consistency and specify the mechanism, not to relitigate the product decision:

> "When the router's best-ranked provider for a given invocation has no account configured by the user, the system SHALL route to the best-ranked *configured* provider instead of failing the invocation, and SHALL record that a substitution occurred and why." — PRD `FR-RTG-005`

This ADR's §3 candidate-filtering step (`configured_provider_filter` in §7's handoff record) implements this directly: the candidate set is filtered to configured providers **before** ranking ever runs, so "best-ranked provider overall" and "best-ranked *configured* provider" are the same computation applied to different candidate sets — there is no separate "compute the ideal answer, then check if it's available" step that could produce an inconsistent user-facing story. The router always ranks and selects from what the user actually has.

**Design decision this ADR does add, consistent with PRD `FR-AUT-003`:** a user may configure zero providers and LordCode still starts successfully (`FR-AUT-003`) — the router simply has no work to do until the first routed invocation. The two legitimate hard-failure ("fail loudly") conditions, and only these two, are:

1. **Zero configured providers, or all configured providers' circuit breakers are OPEN, at the point of the first routed invocation.** This is exactly the case `FR-AUT-003`'s acceptance criterion anticipates ("the failure, if any, occurs only at the point a pipeline run attempts its first provider invocation"), and the failure message must follow `FR-AUT-007`'s discipline — name the specific missing credential/provider, never a bare "authentication failed."
2. **The θ_min or effective-context filter (§4.3, §6) empties the candidate set** even among configured, healthy providers — i.e., the user has an account, but no model they can currently reach clears the capability floor or context requirement for this specific task. This is a different failure from case 1 and must be reported differently: not "no provider connected" but "no configured provider is capable enough / has enough effective context for this specific task," which is actionable information the harness/SDLC engine can act on (e.g., trigger LLMLingua-2 compression per §6, or surface a clear message that this task needs a provider the user hasn't connected).

Both cases are structurally distinct from "the router picked a worse answer than ideal" — the correct behavior for that case is exactly `FR-RTG-005`'s substitution path, not a failure at all.

---

## 9. Shadow-Mode SPRT Rollout Plan

Per this ADR's binding mandate and PRD `FR-RTG-007` ("Should" priority — recorded here as designed regardless, since ADR-1 itself is the router topology this requirement gates): **no new or materially-changed router topology reaches full production traffic without a shadow-mode SPRT validation covering at least 10% of real traffic.** This gate applies the first time this ADR's cascade topology itself ships, and to any future topology change (a v2 bandit layer per §2.3, a re-weighted `S(m,t)` use-case table, a change to θ_min, or the addition of a fourth provider via the open adapter interface).

### 9.1 Architecture

Per `api-orchestration-stack-core` §8.1: the shadow (candidate) topology receives an async, out-of-band mirror of ≥10% of real invocation traffic. **The shadow's output is never shown to the user and never affects the production routing decision or the pipeline's actual execution** — it exists purely to accumulate paired quality-differential observations against the production topology.

**Paired quality signal for LordCode specifically:** rather than an external LLM-judge score (which would add cost and latency to every shadow-mirrored invocation), LordCode uses signals the SDLC pipeline already produces for every invocation regardless of shadow mode: the downstream gate outcome for that invocation's contribution (RS component, Phase F finding count if applicable, confidence-gate escalation count) and the realized cost. This keeps shadow-mode evaluation genuinely free of added production risk, consistent with §9's requirement that shadow responses are discarded and comparison is asynchronous.

### 9.2 SPRT boundaries — cited directly, not re-derived

Per `api-orchestration-stack-core` §8.2/M3 and this ADR's persona-level verified constants:

```
α = 0.05, β = 0.10
A = (1-β)/α = 0.90/0.05 = 18.0     (log A = 2.89)
B = β/(1-α) = 0.10/0.95 = 0.1053   (log B = -2.25)

Decision rule:
  Λ_n ≥ A  → STOP → SWITCH_TO_SHADOW
  Λ_n ≤ B  → STOP → KEEP_PRODUCTION
  otherwise → CONTINUE
```

**Delegated to genai-routing-mathematician, not computed here:** the minimum detectable effect size `δ` and noise variance `σ²` that calibrate LordCode's specific quality-differential distribution (api-orchestration-stack-core §8.2/M3 uses an illustrative `δ=0.02, σ=0.10` giving `E[N|H0] ≈ 160`, `E[N|H1] ≈ 103` observations — this ADR does not assert those exact figures apply to LordCode's own RS-component quality signal, which has a different scale and distribution than the skill's generic example). genai-routing-mathematician must fit `δ`/`σ` from LordCode's actual paired-observation data once the shadow mode is live, and report the resulting expected sample size back into this ADR — consistent with the same "measurement wins over plan" discipline Alignment 5 establishes for ADR-3's storage-form decision.

### 9.3 Rollout gate

The candidate topology is blocked from full production traffic until the SPRT statistic reaches `SWITCH_TO_SHADOW` (`Λ_n ≥ A`). A `KEEP_PRODUCTION` result (`Λ_n ≤ B`) means the candidate does not replace the current topology, and the shadow-mode run is closed without a production change. Per this ADR's mandate, this is a **minimum** floor, not a suggestion — no router-topology change of any kind ships to full production without passing this test.

---

## 10. Consequences

**What this decision buys LordCode:**
- Works correctly from the first user session, with zero cold-start data or exploration-risk cost, on a product where a HIGH hallucination-risk floor makes "explore a possibly-bad model to learn about it" an unacceptable default for security- and correctness-critical invocations.
- Fully deterministic, self-explanatory routing decisions that satisfy FR-HRN-001/002's replay and audit requirements without needing to snapshot a live learned-policy state.
- Does not reopen ADR-2 (Go) — no candidate selected requires on-device tensor operations.
- Directly implements PRD `FR-RTG-005`'s degrade-to-best-available requirement as a structural property of the filter-then-rank pipeline, not a bolted-on special case.
- Reuses model-capability-profiling-core's already-compiled DNA vectors and composite score formula rather than inventing a second scoring mechanism — one source of truth for "how good is this model at this task" across both the router and (implicitly) any future genai-procurement decisions.

**What it costs, stated honestly, per this project's own discipline of naming tradeoffs rather than hiding them:**
- No online learning in v1 — if a provider's real-world quality for a given task class diverges from its compiled DNA vector (model updates on the provider side, which LordCode cannot detect since the corpus is frozen per NEW-1 and DNA vectors are not live-refreshed), the cascade will not self-correct until a human updates the weights or v2's bandit layer (§2.3) ships. This is a genuine limitation, recorded rather than hidden.
- The per-task-class `τ*` threshold table (§4.1) starts from expert-elicited priors, not fitted empirical calibration data, because no usage history exists yet — genai-routing-mathematician must revisit this once real (confidence, outcome) pairs accumulate.
- Effective-context reference values (§6) and per-provider pricing (§3.1) are both explicitly unverified in this ADR pending `technology-scout-analyst`'s Phase 0.2 R&D pass — this ADR's structure is correct independent of those exact numbers, but the numbers themselves are not asserted here.

**Explicit non-goal for this ADR:** this document does not select or design the v2 bandit warm-start layer, does not compute final numeric `τ*`/`C_loss`/`C_esc` values, and does not verify current provider pricing or effective-context tables — all three are named, scoped delegations in the sections above, not omissions.

---

## Mathematical Delegation Summary

All items below were explicitly not self-derived in this ADR, per this agent's binding operating constraint:

| Item | Delegated to |
|---|---|
| Cascade break-even ratio using LordCode's actual verified 2026 provider pricing | genai-routing-mathematician (pending `technology-scout-analyst` pricing verification) |
| Expected regret of a LinUCB bandit at LordCode's realistic per-user invocation volume | genai-routing-mathematician |
| Numeric calibration of `C_loss`, `C_esc`, `R`, and resulting `τ*` per risk class | genai-routing-mathematician (pending shadow-mode/production telemetry) |
| Circuit-breaker steady-state `P(OPEN)` using real per-provider failure-rate data | genai-routing-mathematician (pending production telemetry) |
| SPRT `δ`/`σ` calibration and resulting expected sample size for LordCode's quality-differential distribution | genai-routing-mathematician (pending shadow-mode data) |

---

## Output Format

```
AGENT OUTPUT
  Type:          Multi-Model Router Architecture Spec (ADR-1)
  Agent:         multi-model-router-architect
  Stack:         DNA-ranked rule-based cascade + confidence-gated escalation + per-(provider,tier) circuit breakers
  India Context: DPDP-relevant (per-user credential/context isolation feeds daemon design); Indic 0.5x effective-context correction applied at routing layer for Indic-script source content
  Deliverables:  Router topology decision + quantified 4-way tradeoff table, confidence-gate design (θ derivation + θ_min enforcement), per-provider circuit breaker spec, effective-context-aware filtering, router→harness handoff schema (Alignment 1), partial-account routing behaviour (PRD FR-RTG-005 consistency), SPRT shadow-mode rollout plan
  Status:        DRAFT — PROPOSED, pending solution-architect HLD integration and consensus-agent BINARY gate
  Next:          handoff to solution-architect (HLD integration, Alignment 1/7 seam confirmation) and harness-engineering-architect (handoff schema consumption per §7)
```
