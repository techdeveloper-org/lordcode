# Provider Catalogue — LordCode Multi-Model Router

**Status:** DRAFT — `genai-routing-mathematician` derivations received and integrated (§8); pending `hallucination-detector` review + Phase D.1.5 Independent Verification Gate
**Author:** `genai-procurement-analyst`
**Date:** 2026-09-04
**Consumers:** `multi-model-router-architect` (ADR-1 §3.1/§10 pricing gap this document fills), `solution-architect` (HLD integration), `genai-routing-mathematician` (derivations below), `security-lead-auditor` (Phase F compliance review)
**Depends on / must not contradict:** `docs/orchestration_prompt.md`, `docs/phase-0-requirements/PRD.md` §5.2 (FR-RTG-001…007), §12.3 (no LordCode-brokered billing), `docs/phase-1-architecture/adr1_router_topology.md` (DNA-ranked cascade, θ_min = 0.60, per-(provider,tier) circuit breakers — this document supplies the pricing/DNA/CPST inputs ADR-1 §3.1, §5, §9.2 explicitly left as pending delegations)

**Mathematical Delegation (Operating Rule 8 — binding):** every derivation below (AHP weight reasoning, TOPSIS closeness coefficients, CPST 95% confidence intervals via the delta method, McNemar/two-proportion significance tests, Shapley-based lock-in attribution, cascade break-even) was delegated to and computed by **`genai-routing-mathematician`** against the pricing/benchmark data this document assembled. This agent (`genai-procurement-analyst`) did not self-derive any formula — it assembled inputs, stated task-tier assumptions explicitly, and is reporting the mathematician's output.

---

## 0. Scope Note — What This Document Is and Is Not

Per OAQ-5 (RESOLVED): LordCode never brokers or resells inference. This catalogue does **not** recommend "which vendor LordCode should sign" — there is no LordCode-side purchasing decision to make. It scores **"which provider the router should prefer for task type T, given whichever accounts a given user has actually connected"** — the router's own objective function, per `model-capability-profiling-core` §6.3's composite score `S(m,t) = α·S_cap(m,t) + β·S_cost(m) + γ·S_lat(m)`, which ADR-1 §3 already adopted. This document's job is to supply verified, dated inputs to that formula and to ADR-1's cascade break-even calculation (ADR-1 §3.1, explicitly flagged there as "not fabricated, pending verification").

**Binding constraints applied throughout:** 2+ model stack minimum for any production-critical recommendation; CPST, never cost-per-call; 95% CI on every quantitative estimate; McNemar (or an explicitly-flagged fallback) before any "beats" claim; comparison on effective, not advertised, context; every price cited with source and retrieval date.

---

## 1. Provider Catalogue — Three First-Class Providers (Fixed by Product Decision)

Per `docs/orchestration_prompt.md` component 2 and PRD FR-RTG-001, OpenAI, Anthropic, and Google Gemini are first-class regardless of how they score below — "the product promise is that a user's existing account works, not that LordCode picked the winners." None is treated as the reference shape the others are compared against (this matters directly for §7's adapter-design conclusion).

### 1.1 Verified Pricing (fetched 2026-09-04, primary vendor sources)

| Provider | Model (LordCode tier) | Input $/M | Cached Input $/M | Output $/M | Context window | Source |
|---|---|---|---|---|---|---|
| OpenAI | gpt-5.5 (Tier C — frontier) | $5.00 | $0.50 | $30.00 | not itemized in this fetch | developers.openai.com/api/docs/pricing, 2026-09-04 |
| OpenAI | gpt-5.4-mini (Tier B — standard) | $0.75 | $0.075 | $4.50 | not itemized in this fetch | same |
| OpenAI | gpt-5.4-nano (Tier A — routine) | $0.20 | $0.02 | $1.25 | not itemized in this fetch | same |
| OpenAI | gpt-5.5-pro (reasoning-premium, out of default rotation) | $30.00 | — | $180.00 | not itemized | same |
| Anthropic | Opus 5 (Tier C) | $5.00 | read $0.50 / write-5m $6.25 | $25.00 | 200K | claude.com/pricing, 2026-09-04 |
| Anthropic | Sonnet 5 (Tier B) | **$2.00** (see discrepancy note below) | read $0.20 / write-5m $2.50 | $10.00 | 200K | claude.com/pricing, 2026-09-04 |
| Anthropic | Haiku 4.5 (Tier A) | $1.00 | read $0.10 / write-5m $1.25 | $5.00 | 200K | claude.com/pricing, 2026-09-04 |
| Google | Gemini 3.1 Pro (Tier C) | $2.00 (≤200K) / $4.00 (>200K) | ~10% of input (not itemized per-model) | $12.00 (≤200K) / $18.00 (>200K) | >200K, tiered | ai.google.dev/gemini-api/docs/pricing, 2026-09-04 |
| Google | Gemini 3.8 Flash (Tier B) | $0.75 (promo thru 2026-12-31) / $1.50 standard | n/a in fetch | $3.75 (promo) / $7.50 standard | long context | same |
| Google | Gemini 3.5 Flash-Lite (Tier A) | $0.30 | n/a | $2.50 (batch: $0.15/$1.25) | — | same |

**⚠ Pricing discrepancy, flagged rather than silently resolved (Operating Rule "no stale pricing"):** a secondary aggregator (finout.io, retrieved 2026-09-04) states Claude Sonnet 5 carried an introductory $2.00/$10.00 rate "through August 31, 2026," reverting to standard $3.00/$15.00 from September 1, 2026. The **live vendor pricing page** (claude.com/pricing), fetched today (2026-09-04, i.e. 4 days after the claimed reversion date), still showed **$2.00/$10.00**. This document uses the vendor-fetched $2.00/$10.00 as authoritative because it is PRIMARY and more recent than the SECONDARY claim, but flags that Sonnet 5 pricing may change again without notice — `technology-scout-analyst` should re-verify at Phase 1.5 contract finalization, and the router's pricing table must be refreshable independent of a code release (a config/remote-pricing-table concern for `solution-architect`, not resolved here).

**Sensitivity, computed by `genai-routing-mathematician` (§8.2):** if the SECONDARY $3.00/$15.00 rate is in fact already active, Anthropic Sonnet 5's Tier-B CPST rises from $0.0344/inv to **$0.0433/inv — a +25.8% increase**, which would widen (not narrow) Anthropic's already-highest-CPST position in §6's Tier-B ranking. The pricing discrepancy therefore does not put Anthropic's Tier-B rank in question either way — it only changes the margin.

**Batch API:** all three providers offer a 50% discount at 24-hour SLA (per `token-economics-core` §2.3/§4, relevant only for LordCode's non-interactive invocation classes, e.g. Phase D test-generation batches — never for interactive terminal-facing agents per that skill's decision rule `V_task × (1-exp(-24h/τ_decay)) < C_realtime × 0.50`).

### 1.2 Fourth Candidate on Pareto Grounds — DeepSeek (SECONDARY confidence)

Per task instruction to justify further providers on Pareto grounds: DeepSeek V4 Flash ($0.14/$0.28 per M) and V4 Pro ($1.74/$3.48 standard, promotional $0.435/$0.87) are dramatically cheaper than any of the three first-class providers' equivalent tiers (source: benchlm.ai/deepseek + cloudzero.com/blog/deepseek-pricing, both SECONDARY aggregators, retrieved 2026-09-04 — no PRIMARY DeepSeek pricing page was independently fetched in this pass, flagged accordingly). §5's Pareto frontier evaluates whether DeepSeek's price advantage survives quality-adjustment (CPST, not raw price) before any inclusion recommendation. **DeepSeek is not one of the three fixed providers and carries no product-decision weight** — it is evaluated purely as a possible fourth adapter candidate for the open interface FR-RTG-001 already names.

### 1.3 Capability DNA Scorecard — Coding-Relevant Axes

Per `model-capability-profiling-core` §1.1, the full 10-axis DNA (C1–C10) requires independent per-axis benchmark data this pass did not fully gather (a search-budget-limited pass, consistent with this project's own documented discipline in `research_synthesis_round2.md` of not overstating breadth of confirmation). The axes most load-bearing for LordCode's SDLC pipeline invocations — C1 (Reasoning), C2 (Coding), C6 (Function-calling/tool-use — every agent invocation is a tool-calling loop per the harness), C7 (Long-context), C10 (Safety, given Phase F's CRITICAL-security invocations) — are reported below with explicit confidence tiers. **No score below is presented as more precise than its source tier supports.**

| Model | C2 Coding signal | Confidence | C1 Reasoning | Confidence | C7 Effective context | C10 Safety |
|---|---|---|---|---|---|---|
| Claude Opus 5 | SWE-bench Verified 96.0% (independently reported, PRIMARY-adjacent aggregation) | MEDIUM-HIGH | — no independent C1 measurement found this pass | LOW (est. only) | 200K advertised; no 2026-specific RULER re-measurement found — apply skill's documented 2×–4× retrieval / 4×–8× reasoning gap as a placeholder ratio, i.e. **~100K effective retrieval / ~25–50K effective reasoning (extrapolated, not measured)** | est. only, no STRONG-REJECT-class data found |
| Claude Sonnet 5 | SWE-bench Pro 63.2% (third-party eval, essentially tied with GPT-5.6 Sol's 64.6%) | MEDIUM | — | LOW (est.) | same extrapolation basis, 200K advertised | est. only |
| GPT-5.5 | SWE-bench Verified: **not found** in this pass (no independently-reported score on this exact benchmark); SWE-bench Pro 58.6% is Anthropic's own **vendor-run** evaluation of a competitor — flagged LOW credibility per `llm-benchmarking-core`'s own standard (a competitor-run eval of you is not neutral) | LOW | — | LOW (est.) | context window not itemized in this pass's pricing fetch; extrapolation not attempted without a base figure | est. only |
| Gemini 3.1 Pro | SWE-bench Verified 80.6% (independently reported); SWE-bench Pro 54.2% (Anthropic vendor-run, same credibility flag as above) | MEDIUM (Verified score) / LOW (Pro score) | — | LOW (est.) | >200K advertised, tiered pricing above 200K suggests a real long-context product surface; no 2026 RULER re-measurement found — extrapolation only | est. only |

**Why this table is intentionally sparse rather than filled with invented numbers:** `model-capability-profiling-core`'s own anti-pattern list (§9) explicitly warns against "treating 'est.' and cited DNA axis values as equally reliable" and against reusing stale normalization denominators. A full independent 10-axis re-benchmark of 2026-vintage frontier models was out of this pass's search budget (three benchmark-comparison searches were run; results are reported in §1.3 above and nowhere else). **This is a named gap, not a silent one**: `llm-benchmark-analyst` (parallel-dispatched per the orchestration prompt, `docs/orchestration_prompt.md` line ~1124) is the correct owner of a full independent benchmark sweep; this document's C2/C1/C7/C10 columns should be treated as a floor, refreshed by that agent's output before the router ships numeric DNA vectors into ADR-3's compiled corpus.

---

## 2. McNemar / Significance Testing on "Beats" Claims

Per the binding constraint, no provider is asserted to "beat" another without a significance test, and every non-significant or non-testable comparison is stated as such rather than smoothed over.

**Headline, stated plainly ahead of the detail:** the only pair of providers with a genuinely shared, independently-reported benchmark result in this pass is Claude Opus 5 (96.0%) vs. Gemini 3.1 Pro (80.6%) on SWE-bench Verified. Every other cross-provider comparison gathered in this pass either lacks a shared test set (GPT-5.5 has no independently-reported SWE-bench Verified score) or is sourced from a vendor's **own** evaluation of a competitor (SWE-bench Pro numbers attributed to "Anthropic's own vendor-run evaluation"), which `llm-benchmarking-core`'s reporting standards (§7.1) treat as a materially weaker evidentiary tier than an independent third-party run. **No "GPT-5.5 beats/loses to X" claim is assertable from this pass's data**, and this document does not make one.

**McNemar CANNOT be run** on any of this document's data: `llm-benchmarking-core` M2's paired test requires the item-level (a,b,c,d) contingency table from both models answering the *same* items, and no per-item paired results exist for any provider pair here — only aggregate pass rates. Presenting a McNemar χ² statistic from aggregate percentages alone would be fabricated. Per `genai-routing-mathematician`'s delegated computation:

**Fallback: unpaired two-proportion z-test (Opus 5 96.0% vs. Gemini 3.1 Pro 80.6%, SWE-bench Verified, n=500 each arm, assumed since the true per-arm n was not independently confirmed in this pass):**
```
Pooled p̂ = (0.960×500 + 0.806×500)/1000 = 0.883
SE = √[p̂(1-p̂)(1/500+1/500)] = √0.00041324 = 0.020328
z = (0.960 - 0.806)/0.020328 = 7.575   →   two-tailed p < 0.0001
```
The 15.4-point gap is very likely a real capability difference **by this non-paired approximation**. This is explicitly *not* proof of a paired, per-item-significant difference (a true McNemar test could in principle read differently if failures correlate with shared item difficulty) — it is directional evidence only, and is reported as such, not as "Opus 5 significantly beats Gemini 3.1 Pro" without qualification.

**Every other comparison in this dataset — the Sonnet 5 (63.2%) vs. GPT-5.6 Sol (64.6%) pair on SWE-bench Pro (numerically close, 1.4 points, no paired data — treat as statistically indistinguishable) and all three Anthropic-vendor-run SWE-bench Pro numbers (Opus 4.8 69.2%, GPT-5.5 58.6%, Gemini 3.1 Pro 54.2%) — cannot support any significance claim.** The vendor-run set carries a further qualitative caveat: OpenAI's own July 2026 audit found ~30% of SWE-bench Pro tasks flawed (contamination/task-quality risk), independent of whether any given pairwise gap would otherwise clear a significance threshold.

---

## 3. Effective vs. Advertised Context

Per `context-decay-analysis-core` §1.1: "advertised context length is a hardware limit, not a quality guarantee," and providers must never be compared on advertised context. No 2026-vintage independent RULER/NIAH re-measurement of gpt-5.5, Opus 5/Sonnet 5, or Gemini 3.1 Pro was found in this pass's search budget. Per that skill's own documented 2×–4× (retrieval) / 4×–8× (multi-hop reasoning) degradation ratios (§1.1, §4.4), the extrapolated — **not measured** — effective-context estimates in §1.3's table are a placeholder for `technology-scout-analyst`/`llm-benchmark-analyst` to replace with a real 2026 RULER pass before ADR-3's compiled corpus bakes in a numeric effective-context table (this is exactly ADR-1 §6.3's own flagged dependency — "this ADR does not assert current numeric effective-context values for specific 2026 model versions"). **Router implication for ADR-1 §6:** until real measurements land, LordCode's effective-context filter should apply the conservative (larger) gap — treat reasoning-class invocations (the majority of specialist-agent work, per `context-decay-analysis-core` §1.3's own table showing multi-hop tracing at ~0.2× advertised) as clearing only ~20–25% of any provider's advertised window, not 50%, until measured otherwise. Indic 0.5× correction (§9.1 of that skill) stacks multiplicatively on top of this for Indic-script source content, consistent with ADR-1 §6.4.

---

## 4. AHP Weight Adjustment for LordCode's Profile

The India-enterprise empirical baseline (Quality 0.38, Compliance 0.27, Cost 0.18, Vendor risk 0.10, Latency 0.07) does not describe LordCode's actual profile: LordCode is a free, BYO-account developer tool with **no LordCode-side procurement or compliance liability** for provider selection (the user's own account and the user's own DPDP §4 consent, per PRD FR-DPD-001, already carry that weight) — so the enterprise table's Compliance weight, which encodes a procuring organization's own regulatory exposure, does not transfer directly. Conversely, cost-sensitivity is materially **higher** than an enterprise buyer's: a single LordCode requirement burns 40–80+ invocations on the user's own bill (PRD component 1, "the user pays their own provider bill... a thorough run costing real tokens is the point of the product"), so cost compounds across a run in a way a per-seat enterprise contract does not. Latency also matters more than the enterprise baseline because LordCode is an **interactive** CLI tool, not a batch enterprise workflow.

**Method note (`genai-routing-mathematician`, §8.1):** no fresh pairwise comparison matrix was elicited for this reweighting — per `genai-procurement-decision-core` §2, a reasoned direct-weight adjustment from a documented baseline is an accepted alternative to eigenvalue derivation when no new pairwise elicitation actually occurred, and fabricating a pairwise matrix that wasn't elicited would misstate the method used.

| Criterion | Enterprise baseline | **LordCode reweight** | Reasoning |
|---|---|---|---|
| Quality | 0.38 | **0.40** | Still dominant — a coding CLI's value proposition is code correctness; rises slightly with no compliance function competing for weight. |
| Compliance | 0.27 | **0.05** | Sharply cut — LordCode brokers zero spend and holds zero compliance liability for provider selection; residual 0.05 is a binary "does the option exist" check, not a procurement-grade obligation. |
| Cost | 0.18 | **0.30** | Materially increased — the individual user pays per-invocation, 40–80 times per requirement, out of pocket; price sensitivity is a first-order adoption driver here, not a back-office line item. |
| Vendor risk (lock-in) | 0.10 | **0.15** | Modestly increased — multi-provider portability is core to LordCode's architecture, but this is a technical concern for the tool, not an enterprise vendor-risk register. |
| Latency | 0.07 | **0.10** | Increased — interactive CLI in a human's edit loop, though still trailing Quality/Cost since most of the 40–80 invocations run unattended within a pipeline. |

**Sum check:** 0.40 + 0.05 + 0.30 + 0.15 + 0.10 = **1.00** ✓

---

## 5. Pareto Frontier and TOPSIS Ranking

**Result (Tier B representative — gpt-5.4-mini, Sonnet 5, Gemini 3.8 Flash promo rate; full arithmetic in §8):**

| Rank | Provider (Tier B model) | Closeness coefficient CC_i |
|---|---|---|
| 1 | OpenAI (gpt-5.4-mini) | 0.6353 |
| 2 | Google (Gemini 3.8 Flash) | 0.5677 |
| 3 | Anthropic (Sonnet 5) | 0.4251 |

**This ranking is cost-driven, not quality-driven, and is explicitly flagged as provisional.** Anthropic's Tier-B quality signal (SWE-bench Pro 63.2%, the only Tier-B-adjacent figure in this dataset with genuine third-party sourcing) is the *highest-confidence* of the three Quality inputs, yet Anthropic ranks last — because its Tier-B CPST ($34.44/1000 inv, §6) is 2.4–2.7× the other two providers', and Cost now carries 0.30 of the weight vector (§4) versus 0.18 in the enterprise baseline. The OpenAI and Google Quality inputs used in this ranking (45 and 36 respectively, on a 0–100 scale) are **low-confidence extrapolations** — no direct benchmark exists for gpt-5.4-mini or Gemini 3.8 Flash in the data gathered this pass; both were derived by applying an assumed mini-vs-flagship benchmark gap (~18–20 points, an industry-pattern assumption, not vendor-confirmed) to each provider's only measured sibling model. **If a real Tier-B benchmark later shows OpenAI/Google materially below these assumed values, this ranking could flip** — `llm-benchmark-analyst`'s independent benchmark sweep (parallel-dispatched per the orchestration prompt) should supersede this ranking's Quality inputs before the router bakes in a static preference order.

**Pareto-frontier note on DeepSeek (§1.2):** DeepSeek's raw per-token price is far below any of the three first-class providers, but §1.3 records **no independently-verified coding-capability score for DeepSeek V4** in this pass — its 2025-era DNA profile (from `token-economics-core`'s own April-2026 skill-embedded pricing table, referencing the now-retired V3/R1 generation) is stale by this document's own "benchmark older than model version" standard. **Recommendation: do not add DeepSeek to the router's default candidate pool in v1** pending a real V4-generation capability measurement — its price advantage is real and worth revisiting once `llm-benchmark-analyst` supplies a genuine 2026 DNA vector for it, consistent with the Pareto-frontier discipline of never ranking on price alone (`genai-procurement-decision-core` §11 anti-pattern: "ranking self-hosting vs API pricing by GPU-hour rate alone" generalizes directly to ranking any provider on price without a verified quality axis).

---

## 6. CPST Table — Per Provider, Per Task Tier, 95% CI

**Assumptions (router-design estimates, not production telemetry — LordCode has not shipped yet):** Tier A: T_in=3,000, T_out=400, s=0.95. Tier B: T_in=8,000, T_out=1,500, s=0.90. Tier C: T_in=15,000, T_out=3,000, s=0.85. CI via delta method, `SE(CPST) ≈ C_raw × √[(1−s)/(s³×n_val)]`, n_val=150. Standard (non-cached, non-batch) pricing only.

| Provider | Tier | Model | CPST ($/1,000 invocations) | 95% CI ($/1,000 inv) |
|---|---|---|---|---|
| OpenAI | A | gpt-5.4-nano | **1.158** | [1.115, 1.200] |
| OpenAI | B | gpt-5.4-mini | **14.167** | [13.411, 14.922] |
| OpenAI | C | gpt-5.5 | **194.118** | [181.068, 207.167] |
| Anthropic | A | Haiku 4.5 | **5.263** | [5.070, 5.456] |
| Anthropic | B | Sonnet 5 (@$2.00/M primary rate) | **34.444** | [32.607, 36.282] |
| Anthropic | C | Opus 5 | **176.471** | [164.607, 188.334] |
| Google | A | Gemini 3.5 Flash-Lite | **2.000** | [1.927, 2.073] |
| Google | B | Gemini 3.8 Flash (promo rate, thru 2026-12-31) | **12.917** | [12.228, 13.606] |
| Google | C | Gemini 3.1 Pro (≤200K tier) | **77.647** | [72.427, 82.867] |

**Read as $/invocation, divide by 1,000** (e.g. OpenAI Tier A ≈ $0.00116/invocation). Worked example (Anthropic Sonnet 5, Tier B) is reproduced in full in §8.2.

**Flags that affect this table directly:**
- Google's Tier B rate is a promotional rate expiring 2026-12-31; at the standard $1.50/$7.50 rate, Gemini 3.8 Flash's CPST rises to ≈**$25.83/1,000 inv** — still cheaper than OpenAI and Anthropic's Tier B, but the promo/standard gap is large enough that the router's cost model must not hardcode the promo rate past its expiry.
- Anthropic Sonnet 5's CPST rises to ≈$43.33/1,000 inv (+25.8%) if the SECONDARY $3.00/$15.00 rate is already active (§1.1 discrepancy).

**Framing note, repeated because it is easy to lose in a numbers table:** every number above is **CPST = cost-per-*successful*-task**, never cost-per-call, per this agent's binding operating rule. A provider that looks cheaper on raw per-token price can still lose on CPST if its assumed success rate for that task tier is lower — this is the entire reason `token-economics-core` §6 exists (the cheap-retries-vs-expensive-single-shot break-even). No ranking in this document is made on raw price.

### 6.1 Cascade Break-Even (feeds ADR-1 §3.1's pending pricing verification directly)

Per `multi-model-routing-core` M3 (`CPST_cascade = C_A + (1−s_A)×C_B/s_B`), computed for two representative cascades:

| Cascade | CPST_cascade ($/1,000 inv) | vs. always-Tier-C | Break-even q₁ = c_cheap/c_expensive | Actual s_A |
|---|---|---|---|---|
| OpenAI nano → OpenAI gpt-5.5 (same-provider) | **10.81** | ~17.96× cheaper than always-C ($194.12) | **0.67%** | 95% |
| Gemini Flash-Lite → Anthropic Opus 5 (cross-provider) | **10.72** | ~16.46× cheaper than always-C ($176.47) | **1.27%** | 95% |

Both break-even thresholds sit at well under 2% — because Tier-A per-attempt cost is 2–3 orders of magnitude below Tier-C, the cascade is economical even if Tier-A's success rate collapsed far below the assumed 95%. This directly answers ADR-1 §3.1's stated open item ("recompute the exact break-even ratio and q_cheap threshold per real provider/tier pairing once pricing is verified") — **the conclusion is robust to the exact pricing figures**, since the break-even margin is roughly two orders of magnitude wide; it is far less robust to the token-shape assumptions above, which remain pre-launch estimates pending real telemetry (§9).

---

## 7. Lock-In Score and the Case for OpenAI-Compatible Adapter Interfaces

**Portability / lock-in scores (`genai-procurement-decision-core` §5.2 formula: 0.30×API_compat + 0.25×model_format + 0.20×data_ownership + 0.15×finetune_export + 0.10×prompt_format), computed by `genai-routing-mathematician`, §8.5:**

| Provider | Portability_Score | **Lock-in (1 − Portability)** | `model_format`'s share of total lock-in |
|---|---|---|---|
| OpenAI | 0.600 | **0.400** | 50.0% |
| Anthropic | 0.425 | **0.575** | 34.8% |
| Google | 0.470 | **0.530** | 37.7% |

OpenAI scores highest on portability specifically because its request/response shape (`/v1/chat/completions`) is the one most third-party gateway tooling (LiteLLM, OpenRouter) already normalizes to, and its prompt format is treated as the reference format by construction (§5.2's own scoring). Anthropic's distinct Messages-API shape (system field, content blocks) and Google's native Gemini shape (contents/parts, though Google now also ships an OpenAI-compatibility endpoint) both score lower on API-compatibility and prompt-format, which is exactly the C_format-dominant switching cost this section exists to quantify.

**Shapley-band confirmation:** applying a linear weight×gap decomposition (not a full Shapley computation — `genai-routing-mathematician` flagged this distinction explicitly), `model_format`'s share of each provider's total lock-in is 50.0% (OpenAI), 34.8% (Anthropic), 37.7% (Google) — OpenAI's figure lands squarely inside `genai-procurement-decision-core` §5.3's documented 40–60% Shapley-dominance band; Anthropic and Google fall slightly below it under this simplified decomposition (a true Shapley computation accounts for cross-dimension interaction effects a linear decomposition does not, so this is a directional confirmation, not an independent re-derivation of the 40–60% figure — that figure is inherited from the skill's own prior Shapley computation, per instruction).

**The conclusion this section exists to state, directly connecting to the Phase 1.5 provider-adapter contract:** per `genai-procurement-decision-core` §5.3, Shapley attribution of switching-cost components across a typical enterprise LLM migration shows `C_format` (API-format conversion cost) dominates total switching cost at **40–60%** — far above contract-termination penalties or fine-tune migration cost. This is not a LordCode-specific finding; it is the skill's own empirically-documented result, and it generalizes directly to LordCode's situation: LordCode's own future switching cost (a user reconfiguring which provider handles a given task class, or a fourth provider being added via the open adapter interface, FR-RTG-001) is dominated by how much of the internal request/response/tool-calling/streaming/error shape is tied to one provider's specific API conventions.

**Concretely, all three named providers in 2026 expose a REST/JSON chat-completion-shaped API surface**, and OpenAI's specific shape (`/v1/chat/completions`, its tool-calling schema, its streaming delta format) is the shape most third-party gateway tooling (LiteLLM, OpenRouter — per `api-orchestration-stack-core` §1.3/§1.5) has already converged on as the de facto reference — not because OpenAI's shape is technically superior, but because it is the one most existing tooling already normalizes to. `NFR-ARC-001` (PRD §6) already requires the provider-adapter interface to admit "a future first-party LordCode model... as another adapter, not a rewrite" — the Shapley result above is the direct, quantified justification for *how* to satisfy that NFR cheaply: **design LordCode's internal provider-adapter contract to accept OpenAI-compatible request/response/tool-call/streaming shapes as its normalized internal representation, translating Anthropic's and Gemini's native shapes into it (and out of it) at the adapter boundary**, rather than inventing a fourth, LordCode-proprietary internal shape that all three (plus any future provider) must translate into equally. This directly lowers the dominant `C_format` term of LordCode's own future switching/extension cost, and it is consistent with — not a contradiction of — ADR-1 §10's explicit statement that "no candidate selected requires provider bias in the internal representation."

**Caveat, stated per this agent's operating rule against overclaiming:** choosing OpenAI's request/response *shape* as the internal normalized representation is an engineering-economics argument about `C_format`, not an endorsement of OpenAI as a preferred provider — §5's Pareto/TOPSIS ranking and §1's "none is the reference the others are compared against" instruction are unaffected by this adapter-shape recommendation. A shape choice at the adapter layer is orthogonal to a routing-preference choice at the composite-score layer.

---

## 8. Mathematician's Report — Full Derivations (delegated to `genai-routing-mathematician`)

**Prepared by:** `genai-routing-mathematician` (delegated derivation per `genai-procurement-analyst`'s Operating Rule 8) | **Date:** 2026-09-04 | **Method:** closed-form computation on the data `genai-procurement-analyst` supplied — no independent web lookups performed by the mathematician; all pricing/benchmark inputs trace back to §1–§3 above.

### 8.0 Upfront data-quality flags (read before trusting any ranking in §3–§7)

| Flag | Detail |
|---|---|
| Sonnet 5 pricing discrepancy | Live vendor page = $2.00/M input (used as PRIMARY). SECONDARY source claims $3.00/M from 2026-09-01. Sensitivity computed in §8.2. |
| No Tier B model has a directly measured benchmark | Quality scores used in TOPSIS (§8.3) are for gpt-5.4-mini, Sonnet 5, Gemini 3.8 Flash specifically. Only Sonnet 5 has a same-benchmark, third-party number (SWE-bench Pro 63.2%). OpenAI/Google Tier B Quality figures are multi-hop extrapolations — LOW CONFIDENCE, flagged explicitly. |
| Benchmark sets are not shared across all three providers | SWE-bench Verified (Opus 5 vs Gemini 3.1 Pro) ≠ SWE-bench Pro (Sonnet 5 vs GPT-5.6 Sol) ≠ Anthropic vendor-run SWE-bench Pro. No apples-to-apples 3-way comparison exists in the source data. |
| McNemar cannot be run | No paired per-item results were supplied for any comparison. Only an unpaired two-proportion z-test approximation is possible, and only for the one pair sharing an actual benchmark. |
| GPT-5.5 SWE-bench Pro number is VENDOR-RUN (Anthropic's own eval) | Treated as lower-credibility than an independent third-party eval, per `llm-benchmarking-core` reporting standards. |
| Compliance scores in TOPSIS are qualitative judgment, not verified | India-region availability scores are reasoned estimates, not confirmed facts — no research was in scope for the mathematician's delegated task. |

### 8.1 AHP reweighting — method note

Per `genai-procurement-decision-core` §2, a reasoned direct-weight adjustment from a documented baseline is an accepted alternative to a freshly-elicited pairwise matrix when no new pairwise elicitation was actually performed — that is the case here; the §4 table above is a reasoned adjustment, not a fabricated eigenvalue derivation from an invented pairwise matrix. Sum verified at 1.00.

### 8.2 CPST — full worked example (Anthropic Sonnet 5, Tier B)

```
T_in = 8,000, T_out = 1,500, s = 0.90
Input:  8,000 × $2.00/1,000,000  = $0.016000
Output: 1,500 × $10.00/1,000,000 = $0.015000
C_raw = $0.031000
CPST  = 0.031000 / 0.90 = $0.0344444/invocation

SE factor (s=0.90, n_val=150): √[(1-0.90)/(0.90³×150)] = √[0.10/109.35] = √0.00091449 = 0.030241
SE = 0.031000 × 0.030241 = $0.00093746
95% CI = 0.0344444 ± 1.96×0.00093746 = 0.0344444 ± 0.0018374 = [$0.0326070, $0.0362819]/invocation
```
Sensitivity: at the SECONDARY $3.00/$15.00 rate, C_raw = 0.024+0.015 = $0.039, CPST = 0.039/0.90 = **$0.043333** (+25.8% vs. the primary-rate figure). The remaining 8 cells (§6's table) follow the identical formula; full per-cell arithmetic available on request but is mechanically identical to this worked example.

### 8.3 TOPSIS — full arithmetic (Tier B representative: gpt-5.4-mini, Sonnet 5, Gemini 3.8 Flash promo)

**Raw criteria values used:**

| Criterion | Type | OpenAI | Anthropic | Google |
|---|---|---|---|---|
| Quality (0–100) | benefit | 45 (est., low-conf.) | 63 (SWE-bench Pro 63.2%, 3rd-party — highest-conf. of the three, but still a Tier-B≠exact-model gap) | 36 (est., low-conf.) |
| Cost (CPST, $/1,000 inv) | cost | 14.1667 | 34.4444 | 12.9167 |
| Latency (1=lowest…5=highest; MEDIUM-HIGH=4, LOW=2 mapping) | cost | 4 | 4 | 2 |
| Vendor lock-in (0–1, §7) | cost | 0.400 | 0.575 | 0.530 |
| Compliance (0–1, qualitative "India-region option exists?", unverified est.) | benefit | 0.5 | 0.5 | 1.0 |

Quality-score derivation (flagged — no direct data exists for these three exact Tier-B models): Anthropic uses SWE-bench Pro 63.2% near-directly (→63). OpenAI's only measured sibling is "GPT-5.6 Sol" (64.6%, presumed flagship, not gpt-5.4-mini) minus an assumed ~20-point mini-vs-flagship gap (industry-pattern assumption, not vendor-confirmed) → ≈45. Google's only measured sibling is Gemini 3.1 Pro (54.2% Anthropic-vendor-run, or 80.6% on a different benchmark — the weaker/vendor-run number was used) minus an assumed ~18-point Flash-vs-Pro gap → ≈36. **These three Quality numbers are the single largest source of ranking uncertainty in this entire report.**

**Step 1 — Vector normalization** (r_ij = x_ij / √Σx_ij²):

| Criterion | OpenAI | Anthropic | Google |
|---|---|---|---|
| Quality (÷85.383) | 0.5271 | 0.7379 | 0.4216 |
| Cost (÷39.420) | 0.35937 | 0.87377 | 0.32766 |
| Latency (÷6.000) | 0.6667 | 0.6667 | 0.3333 |
| Vendor lock-in (÷0.878365) | 0.45539 | 0.65464 | 0.60338 |
| Compliance (÷1.224745) | 0.40825 | 0.40825 | 0.81650 |

**Step 2 — Weighted normalized matrix** (v_ij = w_j × r_ij, weights from §4):

| Criterion (w) | OpenAI | Anthropic | Google |
|---|---|---|---|
| Quality (0.40) | 0.21084 | 0.29516 | 0.16864 |
| Cost (0.30) | 0.10781 | 0.26213 | 0.09830 |
| Latency (0.10) | 0.06667 | 0.06667 | 0.03333 |
| Vendor lock-in (0.15) | 0.06831 | 0.09820 | 0.09051 |
| Compliance (0.05) | 0.02041 | 0.02041 | 0.04083 |

**Step 3 — Ideal solutions:** A⁺ = {Quality 0.29516, Cost 0.09830, Latency 0.03333, Lock-in 0.06831, Compliance 0.04083}; A⁻ = {Quality 0.16864, Cost 0.26213, Latency 0.06667, Lock-in 0.09820, Compliance 0.02041}.

**Step 4 — Euclidean distances and closeness coefficient:**

| Provider | D⁺ | D⁻ | CC_i | Rank |
|---|---|---|---|---|
| OpenAI (gpt-5.4-mini) | 0.093429 | 0.162750 | **0.6353** | 1 |
| Google (Gemini 3.8 Flash) | 0.128452 | 0.168612 | **0.5677** | 2 |
| Anthropic (Sonnet 5) | 0.171067 | 0.126521 | **0.4251** | 3 |

### 8.4 Significance testing — full detail

**SWE-bench Verified, Opus 5 (96.0%) vs. Gemini 3.1 Pro (80.6%) — the only shared, independently-reported benchmark in this dataset.** McNemar cannot be run (no paired item-level data). Fallback unpaired two-proportion z-test (n=500 each arm, assumed):
```
Pooled p̂ = (0.960×500 + 0.806×500)/1000 = 0.883
SE = √[0.883×0.117×(1/500+1/500)] = √0.00041324 = 0.020328
z = (0.960-0.806)/0.020328 = 7.575  →  two-tailed p < 0.0001
```
Directional evidence of a real gap under this non-paired approximation — not a substitute for a true paired McNemar result, which cannot be computed from the available data.

**SWE-bench Pro, Sonnet 5 (63.2%) vs. GPT-5.6 Sol (64.6%):** both third-party-sourced, but no paired data — numerically close (1.4 pts), treat as statistically indistinguishable absent real data. **Anthropic's own vendor-run SWE-bench Pro numbers (Opus 4.8 69.2%, GPT-5.5 58.6%, Gemini 3.1 Pro 54.2%):** no cross-provider significance claim possible — single-vendor evaluation of competitors, not an independent third-party benchmark, further weakened by OpenAI's July 2026 audit finding ~30% of SWE-bench Pro tasks flawed.

### 8.5 Shapley / lock-in — full derivation

Formula: `Portability_Score = 0.30×API_compat + 0.25×model_format + 0.20×data_ownership + 0.15×finetune_export + 0.10×prompt_format` (`genai-procurement-decision-core` §5.2).

| Provider | API_compat | model_format | data_ownership | finetune_export | prompt_format | Portability | Lock-in (1−P) |
|---|---|---|---|---|---|---|---|
| OpenAI | 1.0 (de facto reference shape — LiteLLM/OpenRouter default to it) | 0.2 (closed weights, no export) | 0.6 | 0.2 (fine-tune usable only via OpenAI API) | 1.0 (is the reference format) | **0.600** | **0.400** |
| Anthropic | 0.6 (REST/JSON but distinct Messages-API shape — system field, content blocks — needs adapter) | 0.2 (closed weights) | 0.6 | 0.1 (narrower fine-tune/export access than OpenAI) | 0.6 (distinct block format, translatable) | **0.425** | **0.575** |
| Google | 0.7 (native Gemini shape, but ships an OpenAI-compatibility endpoint, raising this vs. a pure-native score) | 0.2 (closed weights) | 0.6 | 0.2 (Vertex tuning, no weight export) | 0.6 (distinct contents/parts format, but the OpenAI-compat layer helps) | **0.470** | **0.530** |

Decomposing each provider's total lock-in into per-dimension "loss" contribution (weight × (1−score)): `model_format` loss = 0.25×0.8 = 0.20 for all three providers (since all three score 0.2 on this dimension). Its share of total lock-in: OpenAI 0.20/0.40 = **50.0%**, Anthropic 0.20/0.575 = **34.8%**, Google 0.20/0.53 = **37.7%**. OpenAI's figure lands inside `genai-procurement-decision-core` §5.3's documented 40–60% Shapley-dominance band; Anthropic and Google fall slightly below it under this linear decomposition, which does not capture cross-dimension interaction effects the way a true Shapley marginal-contribution average would — **directionally confirmed, not an independent re-derivation of the 40–60% figure itself**, which is inherited from the skill's own prior Shapley computation per instruction.

### 8.6 Cascade break-even — full derivation

Formula: `CPST_cascade = C_A + (1−s_A) × (C_B/s_B)` (`multi-model-routing-core` M3).

**Same-provider (OpenAI nano → gpt-5.5):** C_A=$0.001100, s_A=0.95, C_B/s_B=$0.1941176 → CPST_cascade = 0.001100 + 0.05×0.1941176 = **$0.0108059/inv** (≈$10.81/1,000 inv) — ~17.96× cheaper than always-Tier-C ($194.12/1,000 inv).
**Cross-provider (Gemini Flash-Lite → Anthropic Opus 5):** C_A=$0.001900, s_A=0.95, C_B/s_B=$0.1764706 → CPST_cascade = 0.001900 + 0.05×0.1764706 = **$0.0107235/inv** (≈$10.72/1,000 inv) — ~16.46× cheaper than always-Tier-C ($176.47/1,000 inv).

**Break-even q₁ (= c_cheap/c_expensive, raw per-attempt costs):** OpenAI nano→gpt-5.5 = 0.001100/0.165000 = **0.667%**; Gemini Flash-Lite→Opus 5 = 0.001900/0.150000 = **1.267%**. Both thresholds sit well under 2%, roughly two orders of magnitude below the assumed 95% actual Tier-A success rate — the cascade remains economical even under severe Tier-A degradation. This conclusion is **robust to the exact pricing figures** (the margin is ~two orders of magnitude wide) but **not** robust to the token-shape assumptions in §6, which remain pre-launch estimates pending real telemetry.

### 8.7 Summary: what is solid vs. assumption-chained

| Confidence | Item |
|---|---|
| **Solid (arithmetic on given data)** | All CPST/CI numbers (§6), TOPSIS mechanics given the stated inputs (§8.3), Portability/lock-in arithmetic (§7/§8.5), cascade math (§6.1/§8.6) |
| **Reasoned but not measured** | AHP reweight (§4), Compliance qualitative scores (§8.3), Latency 1–5 mapping (§8.3) |
| **Weakest link** | Tier-B Quality scores for OpenAI (45) and Google (36) in §8.3 — multi-hop extrapolations from benchmarks measuring different models entirely. The TOPSIS ranking (§5) is sound math on unsound-confidence inputs for two of three Quality values. |
| **No claim made** | McNemar (impossible without paired data), any SWE-bench Pro cross-provider significance claim |

---

## 9. Stack Architecture Recommendation (2+ Model Minimum)

Per the binding operating rule ("always propose a 2+ model stack — never a single model for production-critical work") and consistent with ADR-1's already-adopted DNA-ranked cascade topology:

**Recommended minimum stack for any production-critical LordCode task class (Phase F security agents, `consensus-agent`-gated architecture work, `reliability-auditor`'s RS computation):**

```
PRIMARY   → highest S(m,t) among the user's CONFIGURED providers, θ_min = 0.60 pre-filter applied
FALLBACK  → second-ranked configured provider (cross-provider, not same-provider-different-tier,
             for genuine failure-mode independence — a same-provider outage must not take out
             both primary and fallback)
ROUTER    → ADR-1's DNA-ranked cascade with confidence-gated escalation (§4 of that ADR)
```

This is not a new topology — it is this document's confirmation that ADR-1's already-adopted cascade, applied to any user who has ≥2 providers configured, structurally satisfies the 2+ model minimum without further design work.

**How §5's TOPSIS ranking (OpenAI &gt; Google &gt; Anthropic, Tier B, cost-driven) relates to ADR-1's per-invocation DNA-ranked cascade:** this document's TOPSIS ranking is a *portfolio-level* signal (which provider tends to win under LordCode's reweighted cost-heavy profile, all else equal) — it is not a static override of ADR-1's per-invocation `S(m,t) = α·S_cap + β·S_cost + γ·S_lat` composite score, which re-evaluates capability alignment per task requirement vector every invocation. Where the two agree (a cost-sensitive, Tier-A/B-class invocation), TOPSIS's ranking and the composite score should converge on the same provider. Where they might diverge — a security-critical or architecture-class invocation where `α` (capability weight) dominates `β` (cost weight) per ADR-1 §3 step 2's use-case weight table — the composite score's capability term should win, since §5's Quality inputs for two of the three providers are explicitly flagged as low-confidence extrapolations (§8.3, §8.7) unsuitable for driving a high-stakes routing decision on their own. **Use TOPSIS as the default/cold-start ordering when per-task DNA data is thin; defer to ADR-1's live composite score once real per-task-class quality telemetry exists.**

**The one case this document flags as a genuine gap, not resolved by ADR-1 or here:** a user with exactly **one** connected provider (FR-RTG-002's explicitly-supported "a user with only a Gemini account gets a fully working tool" case) has no fallback by construction — for that user, the harness's `T_max`/budget-guard stop disjuncts (PRD FR-HRN-003) are the only safety net, not a second model. This is a product-level tradeoff already accepted by FR-RTG-002/FR-AUT-003 (zero or one provider must not block LordCode from working), not a defect in this stack recommendation — but it means the "2+ model production-critical" guarantee is conditional on the user's own configuration, and LordCode's UX (per §17(a) of the PRD's README narrative) should make this legible rather than implying redundancy that doesn't exist for a single-provider user.

---

## 10. India / Compliance Layer (Pass-Through, Not LordCode Liability)

Per PRD §12.3 (confirmed by `product-manager-agent`): OAQ-5 means there is no LordCode-side pricing/GST/invoicing consideration — provider costs, including the 18% GST RCM under CGST Act Section 9(3) on cross-border API invoices (`token-economics-core` §10.1), are borne directly by the user under their own provider contract, modelled only inside the router's cost objective (§6's CPST table), never billed by LordCode. This document's CPST figures are therefore pre-GST USD figures the user's own accounting applies RCM to, not a LordCode-facing cost.

**What is genuinely LordCode's obligation, restated from PRD §12.1 rather than re-derived here:** DPDP Act 2023 §4 purpose/context isolation on the daemon (FR-DAE-004, NFR-DPD-001) and consent before third-party transmission (FR-DPD-001) — both already covered by existing FR/NFR, not gaps this catalogue needs to fill. No provider in §1's catalogue is excluded on India-compliance grounds; MeitY empanelment is not applicable here because LordCode is not itself a government-facing deployment and does not broker billing (PRD §12.1 table: "GIGW — Does not apply").

---

## 11. Summary Table for `multi-model-router-architect` / `solution-architect`

| Item | This document's answer | Feeds |
|---|---|---|
| Verified 2026 pricing, all 3 providers, 3 tiers each | §1.1 (PRIMARY vendor-fetched, 2026-09-04) | ADR-1 §3.1 pricing gap |
| AHP weights for LordCode's actual profile | §4 / §8 | Composite score `S(m,t)` weighting per use-case (ADR-1 §3 step 2) |
| TOPSIS provider ranking (Tier B representative) | §5 / §8 | Router's default preference ordering before per-invocation DNA scoring |
| CPST 95% CI, 3×3 | §6 / §8 | Router's `S_cost(m)` term; ADR-1 §3.1's cascade break-even |
| McNemar / significance | §2 / §8 | What "provider X beats Y" claims are safe to make in README/marketing copy — currently: none, safely |
| Lock-in / Shapley / adapter shape | §7 / §8 | Phase 1.5 provider-adapter contract's internal normalized shape |
| Effective context | §3 | ADR-1 §6's effective-context filter (flagged pending real measurement) |
| Stack minimum | §9 | Confirms ADR-1's cascade already satisfies the 2+ model rule when ≥2 providers configured |

---

## Output Format

```
AGENT OUTPUT
  Type:          Procurement Recommendation + Multi-Model Orchestration Stack (Provider Catalogue)
  Agent:         genai-procurement-analyst
  Stack:         DNA-ranked cascade (per ADR-1) over PRIMARY (highest S(m,t) among configured providers)
                 + cross-provider FALLBACK, θ_min = 0.60
  India Context: Pass-through only — no LordCode-side billing/compliance liability (OAQ-5); DPDP/CERT-In
                 obligations already covered by existing FR-DPD/FR-DAE requirements, not gaps this
                 catalogue fills
  Deliverables:  Verified pricing catalogue (3 providers x 3 tiers), capability DNA scorecard (partial,
                 gaps named), effective-context comparison, AHP-adjusted weights, TOPSIS ranking, CPST
                 table with 95% CIs, McNemar/significance findings, Shapley lock-in + adapter-shape
                 recommendation, 2+ model stack confirmation
  Status:        DRAFT — genai-routing-mathematician's full derivations received and integrated (§8);
                 pending hallucination-detector review and Phase D.1.5 Independent Verification Gate
  Next:          hallucination-detector review -> multi-model-router-architect/solution-architect
                 consumption into ADR-1 finalization and Phase 1.5 provider-adapter contract
```
