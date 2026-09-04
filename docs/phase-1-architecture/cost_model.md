# Cost Model — LordCode Multi-Model Router

**Status:** DRAFT — pending `hallucination-detector` review and the Phase D.1.5 Independent Verification Gate (a fresh agent must re-derive every number below from public pricing alone; every formula is written to make that possible without seeing this derivation)
**Author:** `llm-cost-optimizer`
**Date:** 2026-09-04
**Consumers:** `multi-model-router-architect` (router objective function `S_cost(m)`), `solution-architect` (HLD cost-reporting integration), `harness-engineering-architect` (post-run cost display, FR-COR-006), `security-lead-auditor` (Phase F cost-of-verification context)
**Depends on / builds on:** `docs/phase-1-architecture/provider_catalogue.md` (verified 2026-09-04 pricing, DNA scorecard, TOPSIS ranking — **not re-fetched or redone here**), `docs/phase-1-architecture/adr1_router_topology.md` (DNA-ranked cascade topology, θ_min=0.60, per-(provider,tier) circuit breakers), `docs/orchestration_prompt.md`, `docs/phase-0-requirements/PRD.md` §5.2 (FR-RTG), §OAQ-5, §12.3

**Objective-function framing (binding, stated once, applies throughout):** per OAQ-5 (RESOLVED), LordCode brokers zero inference and holds zero billing surface. The user pays their own provider bill on their own account. **Every cost figure below optimises the user's spend, not LordCode's revenue** — there is no LordCode-side revenue to optimise. This document exists to give the router's ranking function `S_cost(m)` a correct, uncertainty-bounded cost signal, and to give the harness's post-run cost display (FR-COR-006) a number worth showing the user. **Token cost is deliberately not gated** — no spend ceilings, no pre-run approval, no budget-gated execution (PRD OOS-005). Runaway protection is the harness's `T_max` + budget-guard mandatory stop disjuncts (FR-HRN-003), a separate mechanism from anything in this document. Nothing here reintroduces cost gating.

---

## 0. A Correction to the Upstream Document, Stated Up Front

Two numbers in `provider_catalogue.md` do not reproduce when recomputed from the formulas that document itself states. Per this project's error-transparency discipline (flag rather than silently fix or silently propagate), both are corrected here and used throughout this document instead of the upstream figures. `provider_catalogue.md` should be updated to match; this is not this document's file to edit.

**Correction 1 — Sonnet 5 secondary-pricing sensitivity.** `provider_catalogue.md` §1.1/§8.2 states that at the secondary-source $3.00/$15.00 Sonnet 5 rate, Tier-B CPST rises from $0.0344/inv to $0.0433/inv (+25.8%). Recomputing directly from the stated `C_raw = T_in·p_in + T_out·p_out`, `CPST = C_raw/s` formula with **both** legs moved to the secondary rate (T_in=8,000, T_out=1,500, s=0.90):

```
C_raw = 8,000 × $3.00/1e6 + 1,500 × $15.00/1e6 = $0.024000 + $0.022500 = $0.046500
CPST  = 0.046500 / 0.90 = $0.0516667/invocation
Δ vs primary ($0.0344444) = (0.0516667 − 0.0344444) / 0.0344444 = +50.0%
```

The upstream $0.0433 figure reproduces only if the output leg is left at the **primary** $10.00 rate (`1,500 × $10.00/1e6 = $0.0150`) while the input leg moves to the secondary $3.00 rate — an inconsistent mix of the two rate regimes. **This document uses +50.0% (CPST = $0.051667/inv) as the correct secondary-rate sensitivity** and carries it as the stated uncertainty range throughout, per the mandatory 95%-CI-and-flagged-pricing-discrepancy rule. `genai-procurement-analyst`/`hallucination-detector` should reconcile this in `provider_catalogue.md` directly.

**Correction 2 — self-host fixed monthly cost.** `token-economics-core` §9 M5 Step 3 states "~$2,574/month per H100" but its own line items (cloud H100 $2,190/mo + power $51.10/mo + "1 SRE FTE amortized: $8,333/month... 0.1 FTE realistic at $100K salary") do not sum to that figure, and 0.1 FTE of a $100K/yr salary is $833/month, not $8,333/month (the skill appears to have mislabeled a decimal place). Recomputed cleanly:

```
C_GPU   = $3.00/hr × 730 hr/month              = $2,190.00/month
C_power = 700W × $0.10/kWh × 730 hr/month       =    $51.10/month
C_ops   = 0.1 FTE × $100,000/yr ÷ 12            =   $833.33/month
C_self_fixed_monthly                            = $3,074.43/month
```

This document uses **$3,074/month** (single H100, 80% utilization) throughout §8, not the skill's $2,574 figure.

Both corrections are computed from formulas already published in the skills this agent is bound to — nothing here is a new derivation method, only arithmetic applied consistently.

---

## 1. CPST — The Primary Metric, With Its 95% CI

Per this agent's binding operating rule, **cost-per-successful-task (CPST) is the only cost metric used anywhere in this document — never cost-per-call.** For a task attempted at success rate `s`:

```
CPST = C_raw / s          where C_raw = T_in·p_in + T_out·p_out
```

Uncertainty in `s` (estimated from a validation sample of size `n_val`) propagates to CPST via the delta method (`token-economics-core` §5.3):

```
SE(CPST) ≈ C_raw × √[(1−s) / (s³ × n_val)]
95% CI = CPST ± 1.96 × SE(CPST)
```

This document reuses `provider_catalogue.md`'s task-tier assumptions verbatim (they are router-design estimates, not production telemetry — LordCode has not shipped — and are labeled as such everywhere they are used): **Tier A** (routine): T_in=3,000, T_out=400, s=0.95. **Tier B** (standard): T_in=8,000, T_out=1,500, s=0.90. **Tier C** (capability-critical): T_in=15,000, T_out=3,000, s=0.85. `n_val=150` throughout.

**The Sonnet 5 pricing uncertainty is carried as a stated range, not resolved to a point estimate.** `provider_catalogue.md`'s live-vendor fetch (2026-09-04) shows Sonnet 5 at $2.00/$10.00 (used as PRIMARY throughout this document, matching the upstream catalogue); a secondary aggregator claims $3.00/$15.00 effective 2026-09-01. Per Correction 1 above, the CPST impact if the secondary rate is already live is **+50.0%** on Sonnet 5's Tier-B CPST specifically ($0.034444/inv → $0.051667/inv), not +25.8%. Every Anthropic-inclusive total in this document is reported at the primary rate with the +50.0%-on-Tier-B sensitivity noted alongside it, exactly where it changes a downstream total (§6).

---

## 2. CPST_cascade — Explicit Derivation Matching ADR-1's Topology

ADR-1 §3 does not implement `token-economics-core` §6.5's simple two-model cascade (`CPST_cascade = C_A + (1−s_A)·C_B/s_B`) as its literal runtime mechanism — ADR-1 §3 step 4 specifies confidence-gated escalation **up the full ranked candidate list**, which for LordCode's 3-tier catalogue means a candidate can escalate A→B→C, not just A→B. The two-model formula in the skill and the three-model ladder ADR-1 actually specifies are related but distinct; both are derived here because the router's objective function needs the one that matches what it actually does.

### 2.1 Two-model cascade (reproduces `provider_catalogue.md` §6.1/§8.6 exactly)

```
CPST_cascade(A→B) = C_A + (1−g_A) × (C_B / s_B)
```
where `g_A` is the confidence gate's acceptance probability at tier A (cold-start proxy: `g_A ≈ s_A`, per ADR-1 §4.2's own stated cold-start convention of expert-elicited priors pending calibration data).

**Worked check (OpenAI nano → OpenAI gpt-5.5):** C_A=$0.0011, s_A=0.95, C_B/s_B=$0.165/0.85=$0.194118.
```
CPST_cascade = 0.0011 + (1−0.95) × 0.194118 = 0.0011 + 0.0097059 = $0.0108059/inv
```
Matches `provider_catalogue.md` §8.6 exactly (≈$10.81/1,000 inv) — confirms the upstream two-model arithmetic is correct; only the Sonnet-5-specific sensitivity figure (§0) needed correction.

### 2.2 Three-tier cascade (extends the skill's own formulas to match ADR-1's actual escalation ladder)

Combining `token-economics-core` §5.2's multi-step pipeline CPST (`CPST_pipeline = Σ_k C_step_k / Π_{j≤k} s_j`) with §6.5's cascade concept, for a ladder A→B→C where escalation past tier k occurs with probability `(1−g_k)`:

```
CPST_cascade(A→B→C) = C_A + (1−g_A)·C_B + (1−g_A)(1−g_B)·(C_C/s_C)
```

The terminal tier C is not itself cascaded further (it is the top of the ranked list), so its own cost is amortized by its own success rate `s_C`, exactly as the base CPST formula does.

**Worked example (OpenAI nano → OpenAI mini → OpenAI gpt-5.5), g_A=s_A=0.95, g_B=s_B=0.90:**
```
C_A = $0.0011 (nano),  C_B = $0.01275 (mini),  C_C/s_C = $0.165/0.85 = $0.194118 (gpt-5.5, terminal)

CPST_cascade = 0.0011 + (0.05)(0.01275) + (0.05)(0.10)(0.194118)
             = 0.0011 + 0.0006375 + 0.00097059
             = $0.00270809/invocation  ≈ $2.708 / 1,000 inv
```

This is **~71.7× cheaper than always-Tier-C** ($194.118/1,000 inv), and cheaper than the two-model cascade above, because the three-tier ladder only reaches the expensive terminal tier `(1−g_A)(1−g_B) = 0.5%` of the time.

### 2.3 A genuine finding this derivation surfaces: escalation is not always cheaper than flat retry

Applying the same ladder logic starting one rung higher — a candidate whose top-ranked tier is already B, escalating only to C on failure (`C_A ≡ C_B_mini = $0.01275`, `g_A ≡ s_B = 0.90`, terminal `C_C/s_C = $0.194118`):

```
CPST_cascade(B→C) = 0.01275 + (1−0.90) × 0.194118 = 0.01275 + 0.0194118 = $0.0321618/inv ≈ $32.16/1,000 inv
```

This is **more expensive per successful task than flat Tier-B CPST alone** ($14.167/1,000 inv, §1). The reason: flat CPST's `1/s` factor implicitly models retry-at-the-same-tier as eventually succeeding (a reasonable proxy for stochastic, sampling-variance failures), whereas escalating a Tier-B failure straight to Tier C pays Tier C's ~14× price premium on every escalated attempt. **Escalating to a materially pricier tier is only cheap when the escalation probability is small and the starting tier is itself cheap** (§2.2, where Tier A's own $0.0011 baseline dominates); it is not a free win once the router is already starting from a mid-tier candidate whose only escalation target is the priciest tier available.

**Router-design implication, not resolved by this document:** ADR-1's ranked candidate list should include intermediate (provider, tier) combinations — e.g., all three providers' Tier-B models ranked before any Tier-C candidate — rather than a strict global A→B→C ladder, to avoid manufacturing exactly this "big price jump on escalation" case when a cheaper Tier-B alternative (a different provider) was available before jumping tiers. This is an architecture note for `multi-model-router-architect`, not a cost-model conclusion this document can enforce.

---

## 3. Prompt-Cache Break-Even and the Sticky-Routing Recommendation

### 3.1 Break-even hit rate, recomputed for LordCode's actual verified Sonnet 5 pricing

`api-orchestration-stack-core` §5.3 derives the Anthropic cache break-even hit rate as 21.7% using the skill's own reference pricing ($3.00 input / $3.75 write-5m / $0.30 read). LordCode's verified primary Sonnet 5 rate (`provider_catalogue.md` §1.1) is $2.00 input / $2.50 write-5m / $0.20 read — different absolute numbers, but the **same ratios** (write = 1.25× input, read = 0.10× input). Recomputing from the skill's own inequality:

```
h × (p_read − p_write) + p_write < p_standard
h × (0.20 − 2.50) + 2.50 < 2.00
−2.30h < −0.50
h > 0.50/2.30 = 0.21739 = 21.7%
```

**The break-even hit rate is unchanged at 21.7%** because Anthropic's cache pricing is a fixed ratio policy (write=1.25×, read=0.10× of whatever the input rate is), not an absolute-dollar threshold — this makes the 21.7% figure scale-invariant to the Sonnet-5 pricing discrepancy in §0/§1: it holds under both the primary and secondary rate hypotheses.

### 3.2 Where LordCode's caching opportunity actually is

LordCode's 40–80+ invocations per requirement (PRD NEW-3) are dispatched to **different specialist agents**, each with its own distinct system prompt (agent persona + skill files) — there is no shared prefix *across* most of those invocations to cache. The real caching opportunity is **intra-invocation**: any single specialist agent's own multi-turn tool-calling loop (Read/Grep/Write/Bash calls back to the same provider within one invocation) shares one system prompt across every turn of that loop — exactly the kind of repeated-prefix pattern prompt caching exists for.

**ADR-1 §7 already gives this for free.** The router's handoff record is "immutable and final for that invocation's execution once emitted... the router never re-invokes itself mid-loop against this same `invocation_id`" (ADR-1 §7). One invocation's multi-turn tool loop is therefore already pinned to one provider for its entire duration by ADR-1's existing design — no separate sticky-routing mechanism is required to get intra-invocation cache preservation; it is a structural consequence of a decision ADR-1 already made for an unrelated reason (deterministic replay, FR-HRN-001).

### 3.3 The remaining question: cross-invocation stickiness for repeated personas

A minority of specialist agents recur across a single pipeline run — `consensus-agent` and `hallucination-detector` are invoked at multiple phase gates in the same run (per the persona-roster pattern this project's own agent library documents). Routing two calls to the *same* persona to *different* providers loses the cache the second call could otherwise have hit.

**Quantified trade-off, per `api-orchestration-stack-core` §10 M6:**

```
dC/dε = c_write + c_compute − c_read     (cost of a 1-percentage-point routing-error increase)
```
Using LordCode's verified Sonnet 5 rates (c_write=$2.50/M, c_compute=$2.00/M saved by cache, c_read=$0.20/M):
```
dC/dε = 2.50 + 2.00 − 0.20 = $4.30/M tokens per unit increase in ε
```
For an 8K-token system prompt, each 1% degradation in sticky-routing accuracy costs `$4.30/M × 0.008M = $0.0344/request` — small in absolute terms.

**Against that, the cost of picking the wrong (sticky) provider over the top-ranked one:** the gap between adjacent-ranked Tier-B candidates is typically the gap between two of the three providers at the same tier — e.g., OpenAI ($0.014167/inv) vs. Anthropic ($0.034444/inv), a **$0.0203/inv** difference (§1), an order of magnitude larger than the $0.0344-per-1%-degradation cache cost above **only if** the top-ranked provider actually changes between the two calls to the same persona.

**Recommendation — conditional stickiness, not unconditional:** implement sticky routing as a **tie-break rule layered on top of the existing ranking**, not a separate routing path: when re-invoking a persona already used earlier in the same pipeline run, prefer that persona's previous provider *if and only if* it still clears the θ_min filter, its circuit breaker is not OPEN, and its composite score `S(m,t)` has not fallen out of the top-K of the current ranking. Because `S(m,t)`'s capability and price inputs are static within a run (only latency/health signals move), the top-ranked provider for a fixed persona rarely changes between two calls minutes apart absent a circuit-breaker event — so the common case costs nothing (sticky and optimal coincide) and the cache is preserved; the circuit-breaker/θ_min escape hatch ensures stickiness never overrides ADR-1's degrade-to-best-available (FR-RTG-005) or capability-floor (θ_min) guarantees. **This is a small, net-positive addition to ADR-1, not a competing mechanism** — it costs at most the $0.0344/request cache-miss penalty in the rare case a re-ranking genuinely occurred, against the cache savings whenever it did not.

---

## 4. "Cost Saved via Routing" — the Publishable Metric

This is the highest-risk user-facing claim this document produces, so the baseline is stated explicitly rather than left implicit.

### 4.1 Definition

```
Cost_Saved_Pct = (Cost_baseline − Cost_actual_routed) / Cost_baseline × 100%

Cost_baseline       = N × CPST_TierC(user's configured provider)
Cost_actual_routed  = Σ over all N invocations of that invocation's recorded cost,
                       read from ADR-1 §7's handoff record `cost_estimate_usd` field
```

**Baseline choice, justified:** `Cost_baseline` is "what this same run would have cost if every invocation had gone to the user's own highest-capability configured model, with no tiering or cascade at all" — the honest counterfactual of a naive tool that always calls the frontier model, using the **user's own connected provider**, not an artificially expensive third-party model they never configured. This is deliberately **not** "always the single most expensive model across all three providers regardless of what the user connected" — that would inflate the claim with a baseline the user could never have actually run. It is also fully retroactively computable from data ADR-1 already logs per invocation (`selected` provider/model → looked up against the CPST table), so the claim is a **post-run report**, consistent with FR-COR-006 and the no-cost-gating constraint — never a pre-run estimate, never a gate.

### 4.2 Conservative-bias caveat (stated for the Phase D.1.5 gate)

`Cost_baseline` uses `CPST_TierC`, whose `s=0.85` reflects Tier C's success rate on genuinely hard (Tier-C-class) tasks. If Tier C were forced to also execute the routine invocations a real cascade would send to Tier A, its success rate on those *easier* tasks would very likely exceed 0.85 — meaning `Cost_baseline` as defined here is if anything an **underestimate** of what "always Tier C" would truly cost (a lower `s` here inflates `CPST_TierC`, but not by as much as reality would). This makes the resulting savings percentage **conservative, not inflated** — the safe direction for a publishable claim. This caveat should ship with the metric's documentation, not just live in this derivation.

### 4.3 Worked numbers (N=60, the midpoint of the 40–80 range; tier mix per §5.1)

| Configured provider | Cost_baseline (always-C) | Cost_actual_routed | Cost saved |
|---|---|---|---|
| Anthropic only (primary rate) | $10.588 | $2.907 | **72.6%** |
| OpenAI only | $11.647 | $2.274 | **80.5%** |
| Google only (standard rate) | $4.659 | $1.659 | **64.4%** |
| Best-available multi-provider | $4.659 (best-available Tier C = Google) | $1.226 | **73.7%** |

**Headline, stated with its uncertainty:** the router saves roughly **64–81% of naive-always-frontier cost**, depending on which provider(s) the user has configured — computed from the same §5.1 tier-mix assumption that is explicitly not yet measured (§5.2), so this range should be recomputed against real telemetry once it exists, exactly as `provider_catalogue.md` and ADR-1 both flag for their own pending numbers.

---

## 5. The 40–80-Invocation Reality — Per-Requirement Cost, With CI

### 5.1 Tier-mix assumption (stated explicitly — an assumption, not a measurement)

No production telemetry exists (LordCode has not shipped). A tier-mix estimate is derived by reasoning from the SDLC pipeline's own documented agent-roster pattern (per this agent's own operating library: the large majority of any phase's roster is sonnet-class specialist/gate agents, with a smaller, consistent minority of opus-class math masters, `solution-architect`, and Phase-F security-critical agents per phase):

```
Tier A (routine — routing/formatting/boilerplate/sub-task scaffolding): 25%
Tier B (standard — the majority of domain-specialist agent invocations): 60%
Tier C (capability-critical — math masters, solution-architect, consensus
        BINARY gates, Phase F security agents, hallucination/faithfulness audits): 15%
```

**This is a stated, reasoned assumption pending real telemetry — not a measured distribution.** It should be revisited against real per-invocation routing records (ADR-1 §7's handoff record) once LordCode ships, exactly as `provider_catalogue.md` §8.7 flags its own Tier-B quality inputs as "reasoned but not measured."

### 5.2 A statistical subtlety that matters for this section specifically

The 95% CI on each CPST figure (§1) reflects **parameter uncertainty in the success-rate estimate `s`**, estimated once from `n_val=150` validation samples per (provider, tier). That same point estimate of `s` is shared by every invocation of that (provider, tier) within a run — the uncertainty does **not** average out across N invocations the way independent per-invocation noise would (which would shrink like `1/√N`). It is fully correlated across all `N_k` invocations of a given tier, so it scales **linearly** with `N_k`, not with `√N_k`:

```
SE(Total_tier_k) = N_k × SE(CPST_k)
SE(Total_run)     = √( Σ_k [N_k × SE(CPST_k)]² )     (tiers/providers assumed independent estimates)
```

Treating this as if it shrinks with volume (the common, wrong intuition for "more samples, tighter interval") would understate the total run's cost uncertainty. This is flagged explicitly because it is exactly the kind of subtlety an independent re-derivation should catch if it were done wrong.

### 5.3 Worked example 1 — Anthropic-only, N=60, primary Sonnet-5 rate

Weighted per-invocation CPST = `0.25×$0.0052632 + 0.60×$0.034444 + 0.15×$0.176471 = $0.0484529/inv`.

Per-tier SE (from `provider_catalogue.md` §6's stated CIs, half-width ÷ 1.96): Tier A SE=$0.0000984/inv, Tier B SE=$0.00093746/inv (matches the upstream §8.2 worked SE exactly), Tier C SE=$0.0060528/inv. At N=60, N_A=15, N_B=36, N_C=9:

```
SE(Total_A) = 15 × 0.0000984  = 0.001476
SE(Total_B) = 36 × 0.00093746 = 0.033749
SE(Total_C) = 9  × 0.0060528  = 0.054475

SE(Total_run) = √(0.001476² + 0.033749² + 0.054475²) = √0.0041288 = 0.064256

Point estimate = 60 × 0.0484529 = $2.9072
95% CI = 2.9072 ± 1.96×0.064256 = [$2.781, $3.033]
```

At the **secondary Sonnet-5 rate** (§0 Correction 1), the same weighted CPST rises to $0.0587867/inv (only the Tier-B term moves, from $0.034444 to $0.051667); total = **$3.527** (+21.4% vs. the primary-rate total — diluted from Tier B's own +50% because Tier B is only 60% of the invocation mix).

### 5.4 Worked example 2 — best-available multi-provider routing, N=60

Weighted per-invocation CPST (cheapest capable provider per tier: OpenAI Tier A $0.0011579, OpenAI Tier B $0.014167 [durable, non-promotional], Google Tier C $0.077647) = **$0.0204367/inv**.

```
SE(Total_A) = 15 × 0.0000217  = 0.000326
SE(Total_B) = 36 × 0.0003855  = 0.013878
SE(Total_C) = 9  × 0.0026633  = 0.023970

SE(Total_run) = √(0.000326² + 0.013878² + 0.023970²) = √0.00076727 = 0.02770

Point estimate = 60 × 0.0204367 = $1.2262
95% CI = 1.2262 ± 1.96×0.02770 = [$1.172, $1.281]
```

### 5.5 The realistic range across N=40–80 and provider configuration

| Scenario | N=40 | N=60 | N=80 |
|---|---|---|---|
| Multi-provider, best-available (durable pricing) | $0.818 | $1.226 | $1.635 |
| Multi-provider, best-available (Google Tier-B promo, thru 2026-12-31) | $0.788 | $1.181 | $1.575 |
| Google only (standard rate) | $1.106 | $1.659 | $2.212 |
| OpenAI only | $1.516 | $2.274 | $3.033 |
| Anthropic only (primary rate) | $1.938 | $2.907 | $3.876 |
| Anthropic only (secondary rate, if active) | $2.352 | $3.527 | $4.703 |

**Headline range: roughly $0.8–$4.7 per requirement**, order-of-magnitude "sub-dollar to a few dollars," with a typical multi-provider central estimate around **$1.2–$1.6** — and up to **~$4.70** in the worst realistic single-provider-configured case if the secondary Anthropic rate turns out to be active. Every figure here inherits the §5.1 tier-mix assumption's own uncertainty on top of the stated CIs — the CIs above bound the *pricing* uncertainty given the tier mix, not the tier-mix assumption itself, which is a second, currently-unmeasured source of error this document does not attempt to quantify further.

### 5.6 Dominant cost driver

Tier C (15% of invocation count, by §5.1's assumption) accounts for **42–77% of total run cost** depending on provider configuration:

| Scenario | Tier C share of total cost |
|---|---|
| Google only | 42.1% |
| Anthropic only (primary rate) | 54.6% |
| Multi-provider best-available | 57.0% |
| OpenAI only | 76.8% |

**The dominant cost driver is not invocation count — it is the minority of capability-critical invocations.** This follows directly from the same output/input price asymmetry `token-economics-core` §2.2 documents structurally (Tier C's own T_out=3,000 tokens is 7.5× Tier A's T_out=400, and its per-token prices are 4–25× higher depending on provider), compounding a 15%-of-count tier into 42–77% of cost. This is the correct place to focus future cost-reduction engineering (tighter Tier-C task classification, better confidence-gate calibration to avoid unnecessary Tier-C dispatch) rather than optimizing the 85%-of-invocations Tier A/B majority, which is already cheap.

---

## 6. India GST RCM Layer

Per PRD §12.3 and `provider_catalogue.md` §10, LordCode itself carries no billing surface and therefore no GST liability of its own — every figure in §5 is a **pre-GST USD figure the user's own account bears**, on which their own accounting applies India's Reverse Charge Mechanism (18% IGST under CGST Act 2017 §9(3) / IGST Act 2017 §5(3)) if the user is an Indian entity, per `token-economics-core` §10.1. This section is included because the skill's own Response Rule requires GST RCM to appear in every India-context cost estimate — it is not a LordCode-facing cost, but it is a real cost line for an Indian user's own books.

```
C_effective_india = C_api × 1.18   (unregistered / non-ITC-eligible entity)
C_effective_india = C_api × 1.00   (GST-registered entity claiming full Input Tax Credit on the RCM-paid IGST)
```

Applying 18% RCM to §5.5's headline range ($0.8–$4.7/requirement, pre-GST): **₹-denominated, at the skill's own reference rate of ₹83/USD** (this rate should be re-verified at time of use, per this project's own stale-data discipline):

```
$0.8–$4.7 × 1.18 (RCM, non-ITC) = $0.94–$5.55/requirement = ₹78–₹461/requirement
$0.8–$4.7 × 1.00 (RCM + full ITC offset) = $0.8–$4.7/requirement = ₹66–₹390/requirement (net GST cost ≈ zero)
```

**Practical guidance for an Indian user, per the skill's own checklist:** an individual developer procuring API access at this scale should confirm GST registration status; a GST-registered user (including most freelance/consulting entities above the registration threshold) can typically claim full ITC against the RCM-paid IGST, making the net GST cost close to zero — the 18% figure matters mainly for an unregistered individual or hobbyist user, for whom it is a genuine, non-recoverable addition to the ranges in §5.5.

---

## 7. Batch API — Explicitly Not Applicable

Per the binding constraint, Batch API is not included in any of the above as a cost-reduction lever, and this is stated rather than silently omitted. `token-economics-core` §4.2's decision rule:

```
Batch is preferable when: V_task × (1 − exp(−24h/τ_decay)) < C_realtime × 0.50
```

LordCode is an interactive terminal-facing CLI tool in a human developer's edit loop (τ_decay measured in minutes to low hours for most invocation classes, not the ≥12-hour horizon Batch's 24-hour SLA needs to clear before the discount outweighs the utility penalty — `api-orchestration-stack-core` §3.1's own worked example shows a 2-hour `τ_decay` makes Batch "almost never preferable" because the utility penalty consumes 91.7% of task value). The 50% Batch discount is real but structurally inapplicable to LordCode's invocation classes — this is not a gap in this document, it is the correct answer to the question.

---

## 8. Should LordCode's Daemon Ever Offer Self-Hosted Inference?

**No — not as a default or LordCode-provisioned option, for volume reasons alone**, independent of the fact that OAQ-5 already places infrastructure provisioning out of LordCode's product scope.

### 8.1 Self-host break-even, recomputed (single H100, corrected fixed cost per §0 Correction 2)

```
V* = C_self_fixed_monthly / (C_API_per_token − C_self_per_token)
```
`C_self_per_token` at 80% utilization, 12,500 tokens/sec (vLLM/H100, per `token-economics-core` §7.2): `$3,074.43 / (12,500 × 2,628,000 × 0.80 / 1e6) = $3,074.43 / 26,280 = $0.11699/M tokens`.

`C_API_per_token` — using LordCode's **own actual routed** blended rate (§5.4's multi-provider-best scenario), not a generic "$9/M" reference figure, since that is the number a self-host alternative actually has to beat: at 9,250 tokens/invocation average (0.25×3,400 + 0.60×9,500 + 0.15×18,000) and $0.0204367/invocation (§5.4), the blended rate is `$0.0204367 / 0.00925 = $2.209/M tokens`.

```
V* = $3,074.43 / ($2.209 − $0.117) = $3,074.43 / $2.092 = 1,469 million tokens/month ≈ 1.47 billion tokens/month
```

### 8.2 Realistic user volume vs. V*

At 9,250 tokens/invocation and a generous active-power-user estimate of 100 requirements/month at 60 invocations each (6,000 invocations/month):

```
Monthly volume = 6,000 × 9,250 = 55.5 million tokens/month ≈ 3.8% of V*
```

Even an extreme, team-scale usage pattern (500 requirements/month, far outside "individual BYO developer tool") reaches only `500 × 60 × 9,250 = 277.5M tokens/month ≈ 19% of V*`. A user would need to sustain **~2,600 requirements/month** — continuous, full-time, multi-person usage — to cross V*, which is outside the individual-developer, free-tool product this project has already scoped (PRD STK-001: "Primary user of the CLI, connects 1–3 provider accounts," individual developer).

### 8.3 India adjustment (IndiaAI Mission subsidized rate)

Even at the IndiaAI Mission's subsidized GPU rate (`genai-procurement-decision-core` §9.3: <₹100/GPU-hour ≈ $1.20/hour, a ~60% discount off the $3.00/hour commercial on-demand rate used above), `C_self_fixed_monthly` scales down roughly proportionally on the GPU line (≈$876+$51+$833=$1,760/month), moving `V*` to roughly `$1,760/($2.092) ≈ 841` million tokens/month — still **~15× the extreme team-scale usage estimate above**. The subsidy narrows the gap but does not close it at any realistic individual-user volume.

### 8.4 Conclusion

Self-hosting is not economical at any volume a single LordCode user (or a small team well beyond the product's stated scope) plausibly reaches. Combined with OAQ-5's product-level decision that LordCode brokers zero inference and provisions zero infrastructure, **the daemon should not offer or recommend self-hosted inference as a first-class option.** The one place self-hosting legitimately belongs in this architecture is exactly where `provider_catalogue.md` §1.1/§7 already scopes it: as one more adapter behind the already-approved open provider-adapter interface (FR-RTG-001/006) — a user who already operates their own GPU (e.g., pointing LordCode at a local Ollama/vLLM endpoint) can do so as their own infrastructure choice, with no LordCode-side provisioning, recommendation, or cost model change required. This is consistent with, not a contradiction of, §8.1–8.3's conclusion that provisioning self-host infrastructure is never worth recommending by default.

---

## 9. Summary Table for `multi-model-router-architect` / `solution-architect`

| Item | This document's answer | Feeds |
|---|---|---|
| CPST formula + 95% CI (delta method) | §1 | Router's `S_cost(m)` term |
| Sonnet-5 pricing uncertainty, corrected | §0 (+50.0%, not +25.8%) | Every Anthropic-inclusive total in §5–§6 |
| CPST_cascade matching ADR-1's actual ladder | §2 (2-tier and 3-tier derivations; escalation-price-jump finding) | Confidence-gate/ranking design (ADR-1 §3–§4) |
| Prompt-cache break-even | §3.1 (21.7%, scale-invariant) | Cache-monitoring alert threshold |
| Sticky-routing recommendation | §3.3 — conditional tie-break, quantified trade-off | Router persona-affinity design |
| "Cost saved via routing" — publishable metric | §4 (baseline definition + conservative-bias caveat + 64–81% worked range) | FR-COR-006 post-run cost display |
| Per-requirement cost, 40–80 invocations, with CI | §5 ($0.8–$4.7 headline range; Tier-C dominant cost driver) | User-facing cost expectations |
| India GST RCM | §6 (pass-through, ITC-eligible → net ≈0) | User's own accounting, not LordCode's |
| Batch API applicability | §7 (not applicable — stated, not omitted) | Confirms no batch-mode cost lever exists for this product |
| Self-host recommendation | §8 (No — V*≈1.47B tokens/month vs. realistic ≤277M) | Confirms OAQ-5/FR-RTG-001's adapter-only self-host path |

---

## Output Format

```
AGENT OUTPUT
  Type:          LLM Cost Optimization Report (Cost Model)
  Agent:         llm-cost-optimizer
  Stack:         DNA-ranked cascade (ADR-1) — CPST-driven router objective function
  India Context: GST RCM applied to §5.5's headline range (§6); pass-through only, no
                 LordCode-side billing/compliance liability (OAQ-5)
  Deliverables:  CPST + 95% CI methodology (§1), CPST_cascade matching ADR-1's actual
                 escalation ladder incl. a router-design finding (§2), prompt-cache
                 break-even + conditional sticky-routing recommendation with quantified
                 trade-off (§3), "cost saved via routing" publishable metric with stated
                 baseline and conservative-bias caveat (§4), 40-80-invocation per-requirement
                 cost range with full CI propagation methodology (§5), India GST RCM layer
                 (§6), Batch API inapplicability (§7), self-host V* break-even and No
                 recommendation (§8). Two upstream arithmetic errors in provider_catalogue.md
                 and token-economics-core identified and corrected (§0), not silently fixed.
  Status:        DRAFT — pending hallucination-detector review and Phase D.1.5 Independent
                 Verification Gate
  Next:          hallucination-detector review -> multi-model-router-architect (S_cost(m)
                 integration) -> solution-architect (HLD cost-reporting integration)
```
