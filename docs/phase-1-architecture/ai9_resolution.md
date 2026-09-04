# AI-9 Resolution — Standalone Summary

**Date:** 2026-09-04
**Author:** `llm-cost-optimizer`
**Full derivation:** `docs/phase-1-architecture/cost_model.md` §0.1
**Status:** RESOLVED (BLOCKER)

---

## The question

`cost_model.md` and `harness_control_policy.json` disagreed by 5.53× on tokens per invocation (9,250 vs 51,157). HLD §13 reduced the whole disagreement to one question: is `cost_model.md`'s `T_in = 8,000` (Tier B) per **turn** or per **invocation**?

## The answer

**Per turn. `cost_model.md` was wrong**, not `harness_control_policy.json`.

`token-economics-core`'s base CPST formula (`C_raw = T_in·p_in + T_out·p_out`) is defined for one API attempt. `cost_model.md` applied it directly to a LordCode "invocation" without accounting for the fact that a LordCode invocation is a multi-turn agent loop (`harness_control_policy.json`'s `loop_lifecycle`/`stop_predicate`), averaging `E[T] = 1/p` turns per invocation class, with no server-side conversation state — so every turn resends the full accumulated context, and total per-invocation input tokens is the triangular sum `Cost_replay(T) = c·T(T+1)/2`, not a single `T_in`.

Two independent checks confirm this:
- **Magnitude**: `T_in=8,000` sits at the scale of one specialist dispatch (20,000–32,000 token Context Budget fields, undivided), not a 6–7-turn accumulation of them.
- **Arithmetic**: treating `T_in=8,000` as the *average* per-turn size implies a per-turn increment `c ≈ 2,087` — within 4% of the harness's own independently-stated placeholder `c=2,000`. `T_in × E[T] = 8,000 × 6.67 ≈ 53,360 ≈ harness's own 51,157`.

A caveat carried forward, not resolved: `cost_model.md`'s Tier A/B/C (which model) and the harness's `class_R`/`class_I`/`class_S` (how many turns) are two different axes — `solution-architect` is Tier C by model but `class_R` by turn-count in the harness's own roster. The diagonal mapping used below (A↔R, B↔I, C↔S) is a first-order approximation, adopted for the same reason HLD §11.3 Finding 10 adopted it, and is a second, unquantified source of uncertainty on top of the ranges below.

## Every figure that moved

All figures below use `harness_control_policy.json`'s own `E[T]=1/p` per invocation class (`class_R`: E[T]=3.33; `class_I`: E[T]=6.67; `class_S`: E[T]=10.0) and ADR-1's sticky per-invocation provider pinning (which makes the repeated portion of the growing context prompt-cache-eligible). Two bounds are given throughout: **cache-adjusted** (central estimate, assumes ADR-1's intra-invocation caching is hit) and **no-cache** (upper bound).

| Quantity | Original (wrong) | Cache-adjusted (central) | No-cache (upper bound) |
|---|---|---|---|
| Tier A CPST | $0.005263/inv | $0.013657/inv (×2.59) | $0.017544/inv (×3.33) |
| Tier B CPST | $0.034444/inv | $0.158519/inv (×4.60) | $0.229630/inv (×6.67) |
| Tier C CPST | $0.176471/inv | $1.155080/inv (×6.55) | $1.764706/inv (×10.00) |
| Weighted CPST (25/60/15 tier mix) | $0.048453/inv | $0.271787/inv (×5.61) | $0.406870/inv (×8.40) |
| Weighted tokens/inv — **bandwidth, unaffected by caching** | 9,250 | 67,833 (×7.33) | 67,833 (×7.33) |
| Per-requirement, N=60 (Anthropic-only) | $2.907 | $16.31 (×5.61) | $24.41 (×8.40) |
| **Per-requirement headline range** (§5.5, folds in AI-7's self-correction retries) | $0.8–$4.7 typical | **$4.5–$26 typical** | $6.7–$39 typical |
| — p95 | $5.5 | **≈$31** | ≈$46 |
| — full SC.1–SC.3 budget | $6.6 | **≈$37** | ≈$55 |
| — full re-route (`R_max`/`N_max`-bounded) | $15.5 | **≈$87** | ≈$130 |
| CPST_cascade (3-tier, OpenAI nano→mini→gpt-5.5) | $0.002708/inv | $0.01214/inv (×4.48) | — |
| Cascade advantage vs. always-Tier-C | ~71.7× | **~104.7× (strengthens)** | — |
| HLD §11.3 egress (input, tier-weighted, both legs corrected) | 245.6 KB/inv (class_I-only, input-only) | **273.6 KB/inv, 16.4 MB/req** | same (bandwidth unaffected by caching) |
| HLD §11.3 ingress (output, tier-weighted, both legs corrected) | 418 KB/req (uncorrected T_out) | **52.0 KB/inv, 3.1 MB/req** | same |
| Self-host `V*` (break-even volume) | ≈1.47B tokens/month | ≈1.47B (cache-adj., rate rises modestly) | ≈540M (no-cache, rate rises more) |
| Self-host recommendation | No | **No — unchanged**, safety margin (realistic usage 3.8–19% of V*) absorbs the correction either direction | No |

**Not affected by AI-9**: the Sonnet-5 secondary-pricing sensitivity (+50.0%, `cost_model.md` §0 Correction 1) is a ratio between two rates that both scale by the identical per-invocation factor, so it cancels exactly — AI-3's fix (below) is independent of AI-9 and unaffected by it. The India GST RCM multiplier (§6, 1.18×/1.00×) and the Batch-API-inapplicable conclusion (§7) are likewise structural, not token-count-dependent, and are unaffected.

**Not resolved by this correction** (carried forward, unchanged in status): the 25/60/15% tier-mix assumption (reasoned, not measured); the harness's own `c=2,000` per-turn placeholder (explicitly provisional pending `go-systems-engineer` telemetry); and the Tier↔class diagonal mapping noted above (a first-order approximation). All three should be revisited together from Phase H replay telemetry once LordCode ships.

## AI-3 — replacement text for `provider_catalogue.md` (not edited here — hand-off to `genai-procurement-analyst`)

`provider_catalogue.md` §1.1/§8.2 still states the superseded **+25.8%** Sonnet-5 secondary-rate sensitivity; `cost_model.md` §0 Correction 1 established the correct figure is **+50.0%** (the upstream figure mixed the secondary input rate with the primary output rate). This figure is unaffected by AI-9 (see above), so no further change is needed once §1.1/§8.2 are brought in line with `cost_model.md`. Exact replacement text, keyed to the current file's line content:

**Replace `provider_catalogue.md` line 42** (currently: *"Sensitivity, computed by `genai-routing-mathematician` (§8.2): if the SECONDARY $3.00/$15.00 rate is in fact already active, Anthropic Sonnet 5's Tier-B CPST rises from $0.0344/inv to $0.0433/inv — a +25.8% increase, which would widen (not narrow) Anthropic's already-highest-CPST position in §6's Tier-B ranking. The pricing discrepancy therefore does not put Anthropic's Tier-B rank in question either way — it only changes the margin."*) with:

> **Sensitivity, corrected (`cost_model.md` §0 Correction 1, 2026-09-04):** if the SECONDARY $3.00/$15.00 rate is in fact already active, Anthropic Sonnet 5's Tier-B CPST rises from $0.0344/inv to **$0.0517/inv — a +50.0% increase**, not the +25.8% previously stated here. The original +25.8% figure reproduces only by leaving the output leg at the primary $10.00 rate while moving only the input leg to the secondary $3.00 rate — an inconsistent mix of the two pricing regimes; recomputing both legs consistently at the secondary rate (`C_raw = 8,000×$3.00/1e6 + 1,500×$15.00/1e6 = $0.0465`, `CPST = 0.0465/0.90 = $0.051667`) gives +50.0%. This widens (not narrows) Anthropic's already-highest-CPST position in §6's Tier-B ranking by nearly double the previously stated margin. The pricing discrepancy still does not put Anthropic's Tier-B rank in question either way — it only changes the margin, now more than originally stated.

**Replace `provider_catalogue.md` line 145** (currently: *"Anthropic Sonnet 5's CPST rises to ≈$43.33/1,000 inv (+25.8%) if the SECONDARY $3.00/$15.00 rate is already active (§1.1 discrepancy)."*) with:

> Anthropic Sonnet 5's CPST rises to ≈**$51.67/1,000 inv (+50.0%)** if the SECONDARY $3.00/$15.00 rate is already active (§1.1 discrepancy, corrected 2026-09-04 — see `cost_model.md` §0 Correction 1).

**Replace `provider_catalogue.md` line 216** (currently: *"Sensitivity: at the SECONDARY $3.00/$15.00 rate, C_raw = 0.024+0.015 = $0.039, CPST = 0.039/0.90 = $0.043333 (+25.8% vs. the primary-rate figure). ..."*) with:

> Sensitivity, corrected: at the SECONDARY $3.00/$15.00 rate, **both legs must move together** — `C_raw = 8,000×$3.00/1e6 + 1,500×$15.00/1e6 = $0.024000 + $0.022500 = $0.046500`, `CPST = 0.046500/0.90 = $0.0516667` **(+50.0% vs. the primary-rate figure)**, not $0.043333/+25.8% as previously stated (that figure left the output leg at the primary $10.00 rate while moving only the input leg — an inconsistent mix of the two rate regimes). The remaining 8 cells (§6's table) follow the identical corrected formula.

Note for the reader merging this: none of §8's other CPST cells (the primary-rate $34.444/1,000 inv Anthropic Tier B figure, or any OpenAI/Google cell) need to change — only the *secondary-rate sensitivity* figure was wrong, and only for Anthropic Tier B, where the two-regime mixing error occurred.

## What Phase 2 and the user need to know in one sentence

Every cost and capacity figure published in Phase 1 before this dispatch was understated by roughly **5.6× to 8.4×** because `cost_model.md` priced one turn of a multi-turn agent-loop invocation as if it were the whole invocation; the corrected typical per-requirement cost is **$4.5–$39** (was $0.8–$4.7), with a re-route ceiling near **$87–$130** (was $15.5) — and this correction, while large, does not change any of the HLD's qualitative architectural conclusions (the cascade design gets *more* attractive, not less; self-hosting stays uneconomical).
