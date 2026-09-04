# Harness Control Policy — Corrections (AI-8, AI-11) and AI-9 Support

**Author:** harness-engineering-architect
**Trigger:** solution-architect's HLD.md (§11.3 Finding 8, §11.5, §13) flagged two numeric errors of mine in `harness_control_policy.json` / `resource_elastic_policy.json`, plus asked for clarification supporting `llm-cost-optimizer`'s resolution of AI-9. This document records what changed and why.

**Math channel note:** no live `harness-mathematics-expert` agent type is spawnable in this environment (a direct `Agent` call with `subagent_type: "harness-mathematics-expert"` returned `agent type not found` — confirmed, not assumed). Every corrected number below is a direct application of the cited skill formula, independently verified by exact computation (binomial term-by-term summation; Erlang-B recursion) rather than an improvised derivation.

---

## AI-8 (HIGH) — Circuit-breaker false-trip probability

**Published:** `P(false trip) ≈ 1.3×10⁻⁹` (z = 5.96), computed via a normal approximation to the binomial tail.

**Corrected:** `P(false trip) = 7.2×10⁻⁶` (7.151×10⁻⁶ precise), via the exact binomial tail:

```
P(X ≥ 10 | X ~ Binomial(20, 0.10)) = Σ_{k=10}^{20} C(20,k) · 0.10^k · 0.90^(20−k)

k=10: 6.442e-6   k=11: 6.507e-7   k=12: 5.423e-8
k=13: 3.708e-9   k=14: 2.060e-10  k≥15: <1e-11 combined
Σ = 7.151e-6
```

**Cause.** The normal approximation was applied at `np = N·r₀ = 20 × 0.10 = 2`, far below the `np ≥ 10` validity rule. At that np the binomial (p=0.10) is severely right-skewed, so a CLT-based tail estimate is not valid — the exact binomial sum must be used instead. This mirrors a limitation in `retry-backoff-circuit-breaker-core` M5's own worked example, which used the same (invalid) approximation at the same parameters.

**Direction.** Unsafe. The published figure understated the true false-trip rate by **~5,700×**, making the breaker look far more resistant to spurious trips than it is — the worst direction for a safety parameter to be wrong in, because it invites under-provisioned monitoring around breaker trips on the belief they are near-impossible.

**Operational verdict.** At the corrected 7.2×10⁻⁶ rate, the breaker is still adequately calibrated in absolute terms: ~20,000 rolling windows/breaker/year × 7.2×10⁻⁶ ≈ 0.14 false trips/breaker/year, ≈1.3/year summed across the deployment's 9 breakers. **θ = 0.5 and N = 20 do not need to move on false-trip grounds alone** at the provisional healthy-baseline `r₀ = 0.10`. What had to change was the *method* (exact binomial, not normal approximation) and the number quoted — not the operating point. Recalibrate θ/N only if Phase H / Ops.2 telemetry shows a materially higher real per-provider `r₀`.

**Where fixed:** `harness_control_policy.json` → `circuit_breaker_policy.trip_rule.false_trip_check` (full exact-binomial breakdown, corrected `P_false_trip`, explicit `normal_approx_*_INVALID/WRONG` fields kept only as a labelled warning, not as the quoted figure) and `math_delegation.consumed_results`. Full record in the new `corrections.AI-8` block.

---

## AI-11 (HIGH) — Worker-pool sizing `c = 134`

**Published:** `minimum_stable_pool_c = 134` in both `harness_control_policy.json` (`routing_dispatch.daemon_worker_pool_sizing`) and `resource_elastic_policy.json` (`daemon_elastic_scaling.worked_example`), derived from a placeholder `λ = 5` arrivals/sec (≈18,000 req/h).

**Corrected:** for an illustrative 50-user team at realistic load (`λ ≈ 0.833` inv/s, from 50 req/h × 60 invocations/req):

```
μ = 1/W = 1/26.7s = 0.0375 inv/s/worker      (unchanged — does not depend on λ)

c_min (stability, ρ<1):        c = 23,  ρ = 0.9658
c at the ρ ≤ 0.75 scale-up trigger:  c = 30,  ρ = 0.7404
  Erlang-B(30) = 0.02226
  P(wait) = C(30,a) = 0.0807   (~8%)
  W_q = 0.276 s
```

independently re-derived via exact Erlang-B recursion + Erlang-C, cross-checked against HLD.md §11.3 Finding 8 (which reports P(wait)=8.0%, W_q=0.274s — agrees to rounding).

**Cause.** `c = 134` used `λ = 5/s`, ~360× the realistic 50-user-team load. Both policy files did label λ a placeholder, but still surfaced `minimum_stable_pool_c: 134` as a bare top-level field — which reads as a usable number even with a caveat attached elsewhere in the same object.

**Direction.** Over-provisioning (~4.5× too many workers), not a safety-direction error — the cost here is wasted infrastructure spend and a misleading capacity plan, not an unsafe gap.

**Structural fix, not just a number swap.** Both files were restructured so that:
- `λ` is explicitly marked a **measurement input pending Ops.2** (site-reliability-engineer, real RED-dashboard telemetry) — never a shipped value.
- The **sizing formula** (stability condition, ρ≤0.75 elastic trigger, Erlang-C wait, wait-time) is the deliverable that ships.
- The `c ≈ 30` figure appears only inside a block explicitly labelled `ILLUSTRATIVE`/`METHODOLOGY_DEMO`/`NOT_A_SHIPPED_VALUE`, to demonstrate the methodology end-to-end for a plausible team size — not to be carried forward as a provisioned pool size.
- The target `P(wait)` the sizing is implicitly aimed at is stated: ρ≤0.75 is chosen to stay clear of Erlang-C's sharp wait-probability inflection near ρ=1, not against an independently fixed SLA; the resulting P(wait)≈8% at the worked point is reported as the outcome, not a promise.

**Where fixed:** `harness_control_policy.json` → `routing_dispatch.daemon_worker_pool_sizing` (fully restructured); `resource_elastic_policy.json` → `daemon_elastic_scaling.worked_example` (fully restructured). Full record in `harness_control_policy.json`'s new `corrections.AI-11` block.

---

## AI-9 (BLOCKER, not resolved here) — input supplied for `llm-cost-optimizer`

AI-9 is `llm-cost-optimizer`'s to resolve: `cost_model.md` says 9,250 tok/invocation, `harness_control_policy.json` says 51,157 — a 5.53× disagreement. I am **not** pre-empting that resolution. What I've done is make my own 51,157 figure unambiguous, added as `forty_to_eighty_invocation_analysis.context_replay_cost_across_the_whole_run.ai9_input_for_llm_cost_optimizer` in `harness_control_policy.json`:

- **Quantity type:** per-invocation, not per-turn. One "invocation" = one bounded agent-loop run (up to its own `T_max`), the same unit `stop_predicate`/`budget_guard_B_per_invocation` use.
- **Which class:** `class_I_implementation` (`p=0.15`, `T_max=30`). Not a cross-class average.
- **Which T:** `E[T] = 1/p = 6.67` turns — the *expected*-case turn count from the loop's own natural stop, **not** `T_max=30` (the worst-case ceiling, which produces the much larger 589,800-token figure elsewhere in the same block).
- **How the Θ(T²) term enters:** `Cost_replay(T) = c·T(T+1)/2` is the cumulative input-token cost of re-sending the growing history on every one of the T turns *inside one invocation*. At `c = 2,000` tok/turn and `T = 6.67`, this sums to ≈51,100–51,157 tokens for the whole invocation.
- **Likely reconciliation** (per HLD.md §11.3 Finding 10, offered not asserted): if `cost_model.md`'s `T_in = 8,000` is *per turn* rather than per invocation, then `6.67 × 8,000 ≈ 53,360 ≈ 51,157` — the two documents may already agree once `cost_model.md`'s unit is clarified. `llm-cost-optimizer` owns confirming this.

---

## Files changed

- `docs/phase-1-architecture/harness_control_policy.json` — both JSON-valid (verified via `python3 -m json.load`). Changes: `math_delegation.consumed_results` (AI-8 citation), `circuit_breaker_policy.trip_rule.false_trip_check` (AI-8 fix), `routing_dispatch.daemon_worker_pool_sizing` (AI-11 fix), `forty_to_eighty_invocation_analysis....ai9_input_for_llm_cost_optimizer` (AI-9 support, new), top-level `corrections` block (new, records AI-8 and AI-11: published value, corrected value, cause, direction, verification).
- `docs/phase-1-architecture/resource_elastic_policy.json` — JSON-valid. Changes: `daemon_elastic_scaling.worked_example` (AI-11 fix, same restructuring pattern).
- `build_pipeline` vs `product_design` scope tagging preserved unchanged throughout.
