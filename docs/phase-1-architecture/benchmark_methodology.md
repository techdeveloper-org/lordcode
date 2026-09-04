# Benchmark Methodology — LordCode Model Quality Measurement

**Status:** DRAFT — pending `hallucination-detector` review and the Phase D.1.5 Independent Verification Gate
**Author:** `llm-benchmark-analyst`
**Date:** 2026-09-04
**Consumers:** `multi-model-router-architect` (ADR-1 §4.3 θ_min, §6 effective-context filter, §9.1 shadow-mode quality signal), `genai-procurement-analyst` (provider_catalogue.md §1.3/§5's flagged low-confidence Quality inputs), `solution-architect` (HLD integration, Phase 1.5 eval-harness scoping), `ai-model-testing-engineer` (Phase D.3 "routing decision quality" testing — the implementing owner of §3's harness), `security-lead-auditor` (Phase F review of any eval-harness data path)
**Depends on / must not contradict:** `docs/orchestration_prompt.md` (Phase D.1.5 mandate, line ~608; the Python eval-harness-over-OpenAPI design consequence, line ~346), `docs/phase-1-architecture/provider_catalogue.md` (§1.3, §2, §5, §8 — the gap this document exists to close), `docs/phase-1-architecture/adr1_router_topology.md` (§3 composite score, §4 θ_min/confidence gate, §6 effective-context filter, §9 SPRT shadow rollout — all four sections this document supplies real inputs to), `docs/phase-0-requirements/PRD.md` §5.2 (FR-RTG-001…007)

**Mathematical Delegation (Operating Rule 8 — binding, per `agents/llm-benchmark-analyst/agent.md`):** Wilson CI derivation, McNemar continuity-correction proof, Bradley-Terry MLE convergence, bootstrap BCa correctness, and IRT 2PL calibration are all pre-derived in `llm-benchmarking-core` §8 (M1–M6) and are cited, not re-derived, below. Any *numeric* fitting against LordCode's own future eval-harness data (τ* calibration, δ/σ for the SPRT boundaries, IRT θ per model) is delegated to `genai-routing-mathematician` once that data exists — this document specifies the measurement design that produces the data, not the eventual fitted numbers.

---

## 0. The Gap This Document Closes — Stated Plainly

`genai-procurement-analyst`'s provider catalogue (§2, §5, §8.7) hit a wall squarely inside this agent's domain: **McNemar could not be run at all**, because no paired per-item data existed anywhere in the data that pass gathered — only aggregate pass rates (Opus 5 96.0% vs. Gemini 3.1 Pro 80.6% on SWE-bench Verified; Sonnet 5 63.2% vs. GPT-5.6 Sol 64.6% on SWE-bench Pro). It fell back to an unpaired two-proportion z-test for the one pair sharing a benchmark (z=7.58, p<0.0001) and flagged that fallback honestly as "directional evidence only... not a substitute for a true paired McNemar result." It also marked its TOPSIS ranking (§5) **provisional**, because two of the three Tier-B Quality inputs (OpenAI 45, Google 36, on a 0–100 scale) are **multi-hop extrapolations** — no benchmark exists for those exact models; the numbers were derived by subtracting an assumed mini-vs-flagship gap from each provider's only measured sibling.

That gap is structural, not a one-off oversight: **no publicly available benchmark publishes item-level, cross-provider paired results for OpenAI, Anthropic, and Google on the same prompts under the same protocol.** Every published number in `provider_catalogue.md` §1.3/§2 is either a single model's own aggregate score, or a competitor's vendor-run evaluation of another provider (flagged there as lower-credibility per `llm-benchmarking-core` §7.1). This document's job is to (a) define how LordCode measures and publishes quality per task type going forward, (b) design the mechanism that actually produces paired data so McNemar becomes usable, and (c) state, honestly, what can be published *before* that mechanism exists. It does not re-rank the three providers from the unpaired data `provider_catalogue.md` already reported — that would repeat the exact overclaiming this document exists to prevent.

---

## 1. Per-Task-Type Quality Measurement — Benchmark-to-DNA-Axis Mapping

Per `model-capability-profiling-core` §1.2, LordCode measures and publishes quality **per task type**, not as a single scalar "model quality" number, because routing decisions are made per invocation against a task-specific requirement vector `R_t` (ADR-1 §3 step 2). The four task types this document's task instruction names, plus one this agent adds as a named gap (not scope creep — justified below), map to DNA axes as follows:

| LordCode task type | DNA axis | Primary benchmark(s) | Contamination-resistant alternative (apply when saturated, §4.3) |
|---|---|---|---|
| **Coding** (implementation, debugging, refactor specialists) | C2 | HumanEval pass@1 (T=0, greedy) | **LiveCodeBench** (temporal-partitioned, post-cutoff) or **SWE-bench Verified** (agentic, tool-use) — preferred by default per §4.3, not just as a fallback |
| **Reasoning** (architecture, root-cause, consensus-adjacent specialists) | C1 | MMLU-Pro (science/law/history/math subdomains), BBH (3-shot CoT) | **GPQA-Diamond** — not yet saturated (frontier ~60%), highest 2025–2026 discriminative value |
| **Extraction** (structured output — SRS/UML generation, FR/AC parsing, JSON schema compliance) | C3 | IFEval (prompt-level + instruction-level compliance, averaged) | No saturation-driven alternative identified this pass; IFEval's rule-based verification is deterministic and not benchmark-version-sensitive the way MCQ sets are |
| **Long-context** (multi-file refactors, RE sub-pipeline call-graph work, SRS/HLD synthesis over large corpora) | C7 | NIAH grid + RULER effective-context score (§5 below) | RULER's own 13-task taxonomy already spans single-NIAH through aggregation; no further substitution needed |
| **Function-calling / tool-use** (named here because it is not one of the four in the task instruction, but every LordCode agent invocation is a tool-calling loop through the harness — `provider_catalogue.md` §1.3 makes the same observation) | C6 | BFCL (AST accuracy) | Not benchmarked this pass — flagged as a genuine gap for the next methodology revision, not silently assumed adequate |

**Why C6 is added rather than left out silently:** ADR-1 §4.2's confidence-gate mechanism depends on what each provider actually returns from a tool-calling loop (logprobs vs. self-consistency vs. structured-output completeness), and that ADR explicitly defers "which of the three named providers exposes logprobs, under which API modes" as unverified. A quality methodology that measures C1/C2/C3/C7 but never measures C6 leaves the confidence gate's own input axis unmeasured. This document does not fill that gap now — no BFCL evaluation was run this pass — but names it explicitly so it is a recorded gap, not an invisible one, per this agent's Operating Rule against silent omission.

**Saturation check, applied to this table, per `llm-benchmarking-core` §3.2:** GSM8K and HumanEval are both near/fully saturated for 2026-vintage frontier models (top-5 average >90%) — `provider_catalogue.md`'s own SWE-bench Verified numbers (Opus 5 96.0%) sit at the edge of this same ceiling. Per the binding saturation rule, this table names LiveCodeBench/SWE-bench Verified as coding's *default*, not a fallback held in reserve — GSM8K is not listed at all (superseded by MATH-class difficulty for any future reasoning-adjacent numeric-task axis), and HumanEval is retained only as a floor-check because it remains the most widely cross-reported number, with the explicit caveat that a HumanEval-only score is not sufficient for a 2026 procurement or routing decision.

---

## 2. Solving the Paired-Data Problem — The Central Deliverable

### 2.1 Why published aggregate scores can never support McNemar

`llm-benchmarking-core` M2 derives this from first principles, not as a house rule: McNemar exists specifically because when two models answer *the same items*, their errors are correlated — both are more likely to fail on genuinely hard items — and a two-sample z-test (which `provider_catalogue.md` correctly used as an explicitly-labeled fallback) treats the two accuracy rates as independent, which they are not when the underlying item sets even partially overlap in difficulty structure. The (a,b,c,d) contingency table McNemar needs — both correct, A-only, B-only, both wrong — **cannot be reconstructed from two aggregate percentages**, no matter how precisely each is measured. This is a structural fact about the test, not a data-quality problem that a better-sourced aggregate number would fix. **This document states, as permanent policy, not a one-time observation: no aggregate benchmark score, however well-sourced, is ever an acceptable substitute for paired item-level data when a comparative claim is being made.**

### 2.2 The mechanism: LordCode's own eval harness, built once, reused as the paired-data engine

`docs/orchestration_prompt.md` (line ~346) already specifies the vehicle this document needs, for an unrelated reason (Go's weakness at data-science-shaped work): **a separate Python tool driving the daemon over its own OpenAPI/HTTP surface** — the "polyglot split" the daemon's contract-first design (FR-DAE-001) makes nearly free. This document's recommendation is to **reuse that exact mechanism as LordCode's benchmark-paired-data engine**, rather than inventing a second piece of infrastructure:

```
Eval Harness (Python) → daemon OpenAPI surface → router (ADR-1, forced through the SAME
  filter/rank/dispatch path a real user invocation takes) → provider adapter (ADR-1 §7's
  OpenAI-compatible normalized shape, per provider_catalogue.md §7) → provider → scored response
```

**Design requirements, each closing a specific hole in what made McNemar impossible for `provider_catalogue.md`'s data:**

1. **Same items.** A fixed, versioned task bank per DNA axis (§1's table), stratified by difficulty. For coding, this bank draws from LiveCodeBench-style *temporally partitioned* problems (post every candidate provider's most recent public training-cutoff — verified per provider, not assumed) so the same items remain contamination-resistant as new provider versions ship. For reasoning and extraction, where no equivalent temporally-partitioned public source exists at the scale LordCode needs, LordCode authors its own held-out item set, explicitly flagged in every published score as **LordCode-authored, not a third-party-standardized benchmark** — this is a materially different evidentiary tier and must never be presented as if it were GPQA-Diamond or MMLU-Pro.
2. **Same prompts.** Every provider receives the identical prompt template, injected through the router's own normalized internal representation (ADR-1 §7 / `provider_catalogue.md` §7 — the OpenAI-compatible shape all three providers' adapters translate to/from). This is not incidental: it is the same architectural choice ADR-1 already made for production traffic, reused here so the eval harness measures the providers, not accidental prompt-shape drift introduced by three different adapter paths.
3. **Same scoring, per model.** Coding: deterministic unit-test pass/fail (no judge model, no subjectivity). Extraction: deterministic rule-based compliance check (IFEval-style, or exact-match against a structured schema). Reasoning: where the item bank is MCQ-shaped, deterministic answer-key match; where it is open-ended, an LLM-judge rubric with the judge model **explicitly disclosed and never one of the three models being evaluated**, and inter-rater reliability reported via Krippendorff's α — reusing the exact α ≥ 0.80 threshold Phase H's own regression gate already uses (`docs/orchestration_prompt.md` line 627), rather than inventing a second reliability bar.
4. **Per model, not per provider.** Every one of the compiled providers' active tiers (per `provider_catalogue.md` §1.1's 3×3 tier table) is run against the full task bank for its relevant axis — not just the flagship tier — because ADR-1's cascade ranks *models*, not providers, and Tier-B is exactly where `provider_catalogue.md` §8.3 flagged its weakest-confidence Quality inputs.

This produces, for every model pair on every axis, the exact `(a,b,c,d)` contingency table `llm-benchmarking-core` M2 requires — the structural gap that made McNemar impossible for `provider_catalogue.md`'s data is closed by construction, not by a better literature search.

### 2.3 What LordCode must run itself, versus what it may take from published sources

| Data class | Source | Usable for |
|---|---|---|
| Single-model aggregate accuracy on a standardized third-party benchmark (e.g., a provider's own reported HumanEval score) | Published, PRIMARY-sourced where possible | Wilson CI single-model claims only (§6.1) — never a comparative claim |
| Item-level, cross-provider paired results on the same prompts | **Must be run by LordCode's own eval harness (§2.2)** — does not exist anywhere else | McNemar (§6.2), the DNA vector's confidence-weighted composite score, θ_min pre-filter numerator, TOPSIS Quality inputs at production-grade confidence |
| Arena-style pairwise battle logs (Chatbot-Arena-shaped) | Third-party if ≥50 battles/pair exist for LordCode's specific candidate models; otherwise LordCode does not fabricate a substitute | Bradley-Terry/Elo fitting (§6.4) — not attempted below θ_min-battle-count |
| Contamination audit signals (already-published leakage findings, e.g. OpenAI's own July 2026 audit finding ~30% of SWE-bench Pro tasks flawed, cited in `provider_catalogue.md` §2) | Published | Contamination flags (§4) — genuinely reusable, since contamination findings about a *benchmark* (not a provider comparison) don't carry the paired-item requirement |

**The bound stated as permanent policy, restated for emphasis because it is the single most consequential sentence in this document:** published aggregate scores can supply single-model Wilson-CI claims and can inform which benchmarks to trust or discard (§4), but **can never supply a paired comparative claim**. Any future agent instance tempted to reach for a two-sample z-test the way `provider_catalogue.md` did must first check whether LordCode's own eval-harness data now exists for that pair/axis — if it does, McNemar is mandatory and the z-test approximation is no longer an acceptable substitute.

### 2.4 Sizing the task bank

Per `llm-benchmarking-core` M2 Step 4's power analysis, detecting a genuinely small effect size (`p_b − p_c = 0.05`) at α=0.05, power=0.80 requires `n_discordant ≥ 309`; at a typical ~15% discordance rate that implies **~2,060 items per axis per model pair** for a fully-powered result — larger than any single standardized benchmark LordCode's task types currently draw from. This document does not recommend LordCode wait for a 2,060-item bank before shipping v1's router: it recommends a **cold-start bank of n≈150–200 items per axis** (matching HumanEval's own scale, §1's floor-check precedent), published with correspondingly wide Wilson/McNemar confidence intervals disclosed honestly, grown toward the fully-powered size as real usage accumulates — the same "measurement wins over plan" discipline ADR-1 §9.2 already applies to its own SPRT δ/σ calibration. A bank below ~50 discordant pairs must report the χ² asymptotic caveat explicitly (§6.2) rather than presenting a McNemar p-value as if the normal approximation were reliable at that size.

### 2.5 Governance and refresh cadence

The task bank is versioned and timestamped (matching ADR-1 §9's `router_topology_version` discipline). It is re-audited for contamination (§4) whenever a candidate model's provider announces a new training cutoff, and it is re-scored whenever a router-topology change triggers ADR-1 §9's SPRT shadow-mode gate — the harness's per-item outcomes are precisely the "downstream gate outcome" quality signal ADR-1 §9.1 already specifies for SPRT's paired quality-differential observations, so this eval harness and ADR-1's shadow-mode rollout share one data-generating mechanism rather than requiring two.

---

## 3. Contamination Audit — Dual-Method, DCR > 0.10, Applied Honestly to LordCode's Actual Constraints

Per `agents/llm-benchmark-analyst/agent.md` Operating Rule 4 and this task's binding constraint, **no scorecard is published without a contamination audit attached**, and per `llm-benchmarking-core` §6.1/§6.2, the audit is dual-method:

### 3.1 Method 1 — n-gram overlap: honestly scoped to what LordCode can actually access

`llm-benchmarking-core` §6.1's canonical n-gram method requires searching the model's *training corpus* for 8–13-gram overlap with test items. **LordCode structurally cannot run this against OpenAI, Anthropic, or Google's training data — none of the three is a locally-hosted or open-weight model, and none of their training corpora is accessible to a third-party evaluator.** This is a real constraint, not an oversight this document papers over: for LordCode's three first-class providers, Method 1 is applied only in its indirect form — ingesting **already-published third-party contamination findings** (e.g., the OpenAI-audited ~30% SWE-bench Pro task-quality finding `provider_catalogue.md` §2 already cites) — never as a self-run corpus search LordCode has no corpus to search.

### 3.2 Method 2 — canonical-order permutation test: the method LordCode CAN run directly

Per `llm-benchmarking-core` §6.2 (Oren et al. 2023), the permutation test needs no training-data access — it only requires querying the model itself across all `k!` answer-choice orderings and testing whether the model prefers the canonical (memorized) ordering beyond chance (`T_perm = (f_canonical − 1/K)/√(1/K(1−1/K)/n_perm_trials)`, reject at `T_perm > 1.96`). **This is directly runnable through the same eval harness §2.2 already builds**, for every MCQ-shaped item in the reasoning axis's task bank (GPQA-Diamond-style, and any LordCode-authored MCQ items). For non-MCQ items (coding, extraction, open-ended reasoning), canonical-order permutation does not apply by construction; contamination resistance for those axes instead comes from the temporal-partitioning discipline §2.2 already specifies (items dated after every candidate model's public training cutoff) plus, where a provider exposes token log-probabilities (unverified per provider — ADR-1 §4.2), a membership-inference likelihood-ratio check (`llm-benchmarking-core` M6) as a secondary signal.

### 3.3 DCR threshold and the saturation rule, reconciled

Per this agent's Operating Rule 5 and the task's binding constraint: **DCR > 0.05 is flagged as medium risk; DCR > 0.10 requires excluding the benchmark from scorecard publication or flagging every score drawn from it as contamination-risked**, never silently included. No LordCode-published scorecard is complete without a DCR line per benchmark/task-bank slice, computed via whichever of §3.1/§3.2 is applicable to that item's shape.

The saturation rule (§1's table decisions, `llm-benchmarking-core` §3.2) is re-applied on a recurring cadence, not just once at methodology-authoring time: every quarter, or on any router-topology-version bump (whichever is sooner), LordCode recomputes the top-5-candidate average per axis's active benchmark. Once that average exceeds 90%, the benchmark is rotated to its harder variant (already pre-selected in §1's table) rather than continuing to report a benchmark that has stopped discriminating — this is the same discipline that already justified naming LiveCodeBench/SWE-bench Verified as coding's *default*, not GSM8K/HumanEval, in §1.

---

## 4. Effective-Context Measurement Protocol — Replacing ADR-1 §6's Placeholder Ratios

ADR-1 §6 states plainly that it "does not assert current numeric effective-context values for specific 2026 model versions" and instructs the router, until measured, to apply the conservative 4×–8× reasoning-class degradation ratio as a placeholder. This section is the measurement design that retires that placeholder.

### 4.1 NIAH grid, run through the same harness

Per `context-decay-analysis-core` §2.1 and `llm-benchmarking-core`'s own KNOWLEDGE DISTILLATION for this task: standard grid `L ∈ {8K, 32K, 64K, 128K, 200K}` tokens, depth `d ∈ {5%, 25%, 50%, 75%, 95%}`. Because the same §2.2 eval harness already drives every candidate model through the router's real dispatch path, the NIAH grid is not a separate piece of infrastructure — it is the same harness pointed at a different item type (needle-insertion documents instead of coding/reasoning prompts), which keeps the measurement apples-to-apples with every other axis in this methodology (same routing path, same provider adapters, same scoring discipline).

### 4.2 RULER task-family stratification and the 85.6% threshold

Per `context-decay-analysis-core` §4.2, `Effective_Context_Length(M) = max L such that RULER_score(M,L) ≥ 85.6%`, threshold calibrated against Llama-2-7B at 4K. Per §1.3 of that skill, degradation is **not uniform across task families** — single-NIAH retrieval holds at ~0.5× advertised while multi-hop tracing degrades to ~0.2× — so LordCode measures and publishes effective context **per RULER task family**, not as one scalar per model:

| RULER family | LordCode invocation class this maps to |
|---|---|
| Single/multi-NIAH retrieval | Simple lookup-style specialist reads (e.g., a single-file style check) |
| Multi-hop tracing (VT) | Multi-file refactors, `codebase-archaeology-agent`-class call-graph work |
| Aggregation (CWE/FWE) | Corpus-wide summarization, SRS/HLD synthesis over many source files |
| QA-with-distractors | RAG-shaped specialist reads against a retrieved-context window |

This directly answers ADR-1 §6 step 1's classification requirement: a multi-file refactor is multi-hop-class, not retrieval-class, and must be routed against the multi-hop-class effective-context number, never the (much larger) retrieval-class number — conflating the two is exactly the anti-pattern `context-decay-analysis-core` §10 warns against.

### 4.3 Indic 0.5× correction — verified, not assumed

ADR-1 §6.4 already commits to applying a 0.5× Indic correction for Indic-script source content, per `context-decay-analysis-core` §9.1/§9.4. That correction is currently an unverified placeholder ratio in the source skill (derived from Multilingual RULER, arXiv 2503.01996 — not a LordCode-specific measurement). This methodology's NIAH grid runs a parallel pass with Indic-script (Devanagari/Tamil/other scheduled-language) fillers and needles for every candidate model, so LordCode's own published effective-context table reports a **measured** Indic correction factor per model, replacing the generic 0.5× placeholder wherever LordCode's own measurement diverges from it — consistent with DPDP-covered Indian users' source code, comments, and commit messages being a real, not hypothetical, LordCode workload (`context-decay-analysis-core` §9.4's own recommendation, echoed in ADR-1 §6.4).

### 4.4 What this feeds

The resulting per-model, per-task-family, Indic-adjusted `Effective_Context_Length(M)` table is the direct, measured replacement for ADR-1 §6's placeholder ratios, and is the input `multi-model-router-architect` consumes for its effective-context pre-filter (ADR-1 §6 step 3) — this document does not redesign that filter, it supplies the real numbers the filter was always specified to consume.

---

## 5. Statistical Reporting Contract — Binding on Every Published Score

Every score LordCode publishes, in a scorecard, in the router's compiled DNA vectors, or in any user-facing README/marketing surface, must satisfy the following before publication. This is the enforceable version of `llm-benchmarking-core` §7.1's reporting standard, made specific to LordCode's three failure modes observed in `provider_catalogue.md` (unpaired-test-as-comparative-claim, low-confidence extrapolation presented without a confidence flag, and a provisional ranking risk of being read as final).

### 5.1 Single-model claims

Every single-model accuracy figure carries: benchmark name **and version** (e.g., "MMLU-Pro," not bare "MMLU" — `llm-benchmarking-core` §2.3), sample size `n`, evaluation protocol (shots, CoT flag, temperature), evaluation date, and the **Wilson 95% CI**, computed per M1 (`center = (k + z²/2)/(n + z²)`, `half-width = z·√(p̂(1−p̂)/n + z²/4n²)/(1+z²/n)`, z=1.96). A bare point estimate is not publishable. Source tier (PRIMARY vendor-fetched / SECONDARY aggregator / vendor-run-of-competitor) is stated per `provider_catalogue.md`'s own precedent, since that distinction materially changes how much weight a reader should place on the number.

### 5.2 Comparative ("A vs. B", "A beats B") claims

1. **If paired item-level data exists** (from §2's harness): compute McNemar with continuity correction, `χ² = (|b−c|−1)²/(b+c)`, reject H₀ only at `χ² > 3.84` (df=1, α=0.05). Report `χ²`, p-value, and the full `(a,b,c,d)` table. If `b+c < 10`, the χ² asymptotic approximation is unreliable — state this explicitly rather than reporting a p-value as if it were trustworthy at that count (`llm-benchmarking-core` M2 Step 3's own stated condition).
2. **If only aggregate data exists:** McNemar is **not computed**. State plainly: *"No paired per-item data exists for this comparison; McNemar cannot be computed."* An unpaired two-proportion z-test may be reported **only** as an explicitly labeled, weaker, non-paired approximation — exactly the caveat `provider_catalogue.md` §2/§8.4 already modeled correctly — and never phrased as "X beats Y" without that qualifier attached in the same sentence, not a footnote.
3. **Where the difference is not statistically significant** (whether by McNemar or the z-test fallback), the published verdict states so explicitly: *"The N-point gap between X and Y on [benchmark] is not statistically distinguishable at n=[n] (p=[p])."* Per this agent's binding Operating Rule and the Alignment 2 contract ("under-claiming is safe; over-claiming is a defect"), a non-significant result is never smoothed into a ranking by silently reporting point estimates and letting the reader infer a winner.

### 5.3 Composite / bootstrap scores (TOPSIS Quality inputs, DNA vector components)

Bootstrap CI at `B ≥ 1,000` resamples (per `llm-benchmarking-core` §4.5's Bradley-Terry precedent, generalized). Any input into a composite score that was derived by cross-model extrapolation (as `provider_catalogue.md` §8.3's OpenAI-45/Google-36 Tier-B Quality figures were) is flagged **LOW CONFIDENCE — extrapolated, not measured** at the point of use, not just in a methodology footnote, and is treated as provisional for any ranking that feeds a shipped default ordering (§7 below).

### 5.4 Elo / Bradley-Terry

Not fit below 50 pairwise battles per model pair (this agent's hard rule, restated). LordCode's own eval-harness output (§2) is head-to-head-comparable data suitable for Bradley-Terry fitting once ≥50 battles per pair accumulate per axis — this is a plausible v2 use of the same harness output, not attempted in v1 given the harness does not exist yet.

### 5.5 Freshness

Any score older than 90 days is flagged stale (this agent's Operating Rule 10) at the point of display, not silently carried forward. Re-measurement triggers on: (a) a candidate provider announcing a new model version, (b) a router-topology-version bump (ADR-1 §9), (c) the 90-day staleness clock, whichever fires first.

---

## 6. What LordCode May Publish Today — The Interim Honest Position

The eval harness (§2.2) does not exist yet — LordCode is pre-launch, and `docs/orchestration_prompt.md`'s own Phase B roster lists the harness as Phase D.3 (`ai-model-testing-engineer`, "routing decision quality"), not a Phase 0/1 deliverable. This section states, deliberately, what is and is not defensible to publish **before** that harness ships, so the product does not either (a) wait for a full eval harness before shipping any quality claim, or (b) publish unsupported rankings in the meantime — both of which this document's task explicitly asks it to avoid.

### 6.1 Publishable today

- **Single-model Wilson-CI'd aggregate scores**, individually cited per §5.1, exactly as `provider_catalogue.md` §1.3 already reports them (SWE-bench Verified 96.0% for Opus 5, etc.) — publishable as "Model X scores Y% on Benchmark Z (independently reported, [date])," never as a ranking implying "X > Y."
- **The θ_min = 0.60 capability floor check (ADR-1 §4.3)** can run today using these single-model scores mapped through §1's DNA-axis table, because θ_min is an **absolute per-model threshold**, not a comparative claim — it does not require paired data to be defensible. A model whose measured `cos(DNA_m, R_t) < 0.60` is excluded from the candidate pool regardless of how any other model scores; that is a single-model judgment, not a "beats" claim.
- **Contamination flags** (§3) — these describe a *benchmark's* trustworthiness, not a cross-provider comparison, and are safely publishable from third-party-sourced findings.

### 6.2 Publishable today only with the PROVISIONAL label attached, never as final

`provider_catalogue.md` §5's TOPSIS ranking (OpenAI > Google > Anthropic, Tier B, cost-driven) may ship as the router's **cold-start / default ordering** (per that document's own §9 recommendation, which this document endorses) — but only continuing to carry the PROVISIONAL label that document already applied, in every surface it appears (internal routing config, any user-facing explanation of "why this model was picked"), until the two LOW-CONFIDENCE Quality inputs (§5.3 above) are replaced by harness-measured paired data. This is not a new constraint — it is this document making permanent, and binding on every future scorecard revision, the flag `genai-procurement-analyst` already raised once.

### 6.3 Not publishable under any circumstances, until §2's harness exists and produces the relevant paired data

- Any "Provider X beats Provider Y" or "Model X is better than Model Y" claim on coding, reasoning, extraction, or long-context, for any pair not covered by `provider_catalogue.md` §2's single already-significant unpaired result (Opus 5 vs. Gemini 3.1 Pro on SWE-bench Verified) — and even that one result is published, per §5.2 rule 2, with its non-paired caveat attached every time it is cited, not just at first mention.
- Any Elo/Bradley-Terry leaderboard — no arena-style battle data exists for LordCode's three candidate providers at any battle count, let alone ≥50/pair.
- Any cross-benchmark comparison (e.g., treating SWE-bench Verified and SWE-bench Pro scores as comparable) — `provider_catalogue.md` §2 already identified these as non-shared test sets; this document reaffirms that finding as permanent, not benchmark-specific.

### 6.4 The build-order recommendation this creates

Because Phase D.1.5's Independent Verification Gate (`docs/orchestration_prompt.md` line 608) requires a fresh agent to re-derive every published routing/quality metric from an authoritative external source, and because §2.1 established that **no external source can ever independently re-derive a paired comparative claim that was never itself paired**, this document recommends: **any comparative router-quality claim LordCode intends to ship (not just the θ_min/single-model claims already defensible per §6.1) must wait on §2's eval harness existing and producing real paired data before Phase D.1.5 can meaningfully verify it.** Scoping the eval harness as an explicit Phase 1.5/Phase B deliverable (owner: `ai-model-testing-engineer`, consuming this methodology directly) rather than an implicit Phase D.3 afterthought is this document's concrete recommendation to `solution-architect` — not a redesign of the SDLC engine's phase ordering, which is outside this agent's authority, but a scoping flag consistent with `provider_catalogue.md` §5's own instruction that `llm-benchmark-analyst`'s output "should supersede this ranking's Quality inputs before the router bakes in a static preference order."

---

## 7. Summary Table for `multi-model-router-architect` / `solution-architect`

| Item | This document's answer | Feeds |
|---|---|---|
| Per-task-type quality measurement + DNA axis mapping | §1 | Router's `S_cap(m,t)` term (ADR-1 §3 step 2) |
| The paired-data mechanism (McNemar now possible) | §2 — LordCode's own eval harness, reusing the daemon's OpenAPI surface | Every future comparative claim; ADR-1 §9.1's SPRT quality-differential signal |
| Contamination audit (dual-method, DCR>0.10) | §3 | Gate on every scorecard publication |
| Effective-context measurement (NIAH+RULER, per task family, Indic-verified) | §4 | ADR-1 §6's effective-context filter — replaces the placeholder 2–4×/4–8× ratios |
| Statistical reporting contract | §5 | What any future scorecard, README, or marketing copy is allowed to say |
| What ships today | §6 | Router's cold-start ordering (provisional TOPSIS + defensible θ_min) without waiting for or fabricating comparative claims |

---

## Output Format

```
AGENT OUTPUT
  Type:          LLM Benchmark Methodology Specification
  Agent:         llm-benchmark-analyst
  Stack:         Per-task-type DNA-axis mapping (C1/C2/C3/C6/C7) + LordCode-run eval harness over the
                 daemon's OpenAPI surface as the paired-data mechanism + dual-method contamination audit
                 + per-task-family NIAH/RULER effective-context protocol + binding statistical reporting
                 contract
  India Context: Indic 0.5x effective-context correction (context-decay-analysis-core §9.1) verified via
                 a dedicated Indic-script NIAH pass rather than assumed from the skill's generic ratio
  Deliverables:  Benchmark-to-DNA-axis mapping table, eval-harness design closing the McNemar paired-data
                 gap, contamination audit protocol (DCR>0.05 flag / DCR>0.10 exclude), effective-context
                 measurement protocol replacing ADR-1 §6's placeholders, statistical reporting contract
                 (Wilson CI / McNemar / "not significant" verdicts), interim publishable-today position
  Status:        DRAFT — pending hallucination-detector review and the Phase D.1.5 Independent
                 Verification Gate
  Next:          hallucination-detector review -> multi-model-router-architect (ADR-1 finalization,
                 θ_min/effective-context filter numeric replacement) and solution-architect (Phase 1.5
                 eval-harness scoping as an explicit deliverable, per §6.4)
```
