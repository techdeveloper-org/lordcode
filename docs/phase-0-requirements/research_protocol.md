# Research Protocol — Phase 0.2 Gap Closure (Q1 OpenAI OAuth / Q2 Gemini Go SDK / Q3 Specialist-Agent Prior Art)

**Prepared by:** research-strategist
**Date:** 2026-09-04
**For execution by:** deep-web-researcher (hard cap: 3 `WebSearch` calls total, search → synthesize → search; `WebFetch` calls are NOT counted against this cap)
**Grading handoff:** research-synthesis-analyst (GRADE-style certainty labeling — see §7)
**Upstream input:** `docs/phase-0-requirements/tech_scout_report.md` (technology-scout-analyst, 2026-09-04) — this protocol closes exactly the three gaps that report self-flagged as UNVERIFIED. Do not re-search anything that report already answered with PRIMARY confidence.

---

## 0. Design Principle: Fetches Are Free, Searches Are Not

Per the tech scout report's own methodology note, `WebFetch` against a specific URL does not count against the Cooldown Research Protocol's 3-search cap — only `WebSearch` does. Two of the three questions already have known or highly-probable target URLs (surfaced by the prior dispatch's own "Recommended Follow-ups"). The design below therefore front-loads **free, targeted fetches** against those known URLs before spending any search, and concentrates the scarcer search budget on the one question (Q3) that is a genuine open-ended discovery problem with no known target URL.

**Budget reallocation rule (read before executing Search 1):** If the pre-search fetches for Q1 or Q2 fully and explicitly resolve that question (definitive answer per §1.2/§2.2 below), the search allocated to it in §5 is **not spent**. Any unspent search from Q1 or Q2 is reallocated to Q3 as a second search, in the priority order Q3 > Q2 > Q1, because Q3 is explicitly the highest-stated-importance question ("LordCode's primary claimed differentiator") and the hardest to saturate with a single query. Never reallocate a search away from Q3 toward Q1/Q2 — if all three need their allocated search, run them as assigned in §5 and report Q3 findings as partial/gap rather than stealing search capacity from Q1 or Q2, since Q1/Q2 feed concrete PRD line items (onboarding copy, effort sizing) that must not be left fully unverified either.

---

## 1. Question 1 — OpenAI "Sign in with ChatGPT" OAuth: Third-Party Availability

### 1.1 FINER Framing

| Criterion | Assessment |
|---|---|
| Feasible | Yes — target URLs are already named by the prior dispatch; this is a targeted verification, not open discovery. |
| Interesting | Yes — determines whether LordCode's onboarding can offer OAuth login or must document API-key-only for OpenAI. |
| Novel | Extends prior work — the tech scout report explicitly reached MEDIUM confidence on Anthropic's equivalent policy and explicitly left OpenAI's as "unverified, open question." This question closes that specific extension. |
| Ethical | None — public developer documentation only. |
| Relevant | High — directly changes onboarding copy and the Phase 0 PRD's authentication section for one of three providers. |

### 1.2 Definitive Answer vs. Honest "Cannot Verify"

**Definitive answer** = an explicit statement, found on an OpenAI-owned domain (`developers.openai.com`, `platform.openai.com`, or the official `github.com/openai/codex` repo/docs), that either (a) names third-party/non-Codex client applications as permitted to use the ChatGPT-login OAuth grant, with any registration/client-ID process described, or (b) explicitly scopes the grant to Codex (or to OpenAI first-party clients) and states or implies third parties must use API-key auth instead.

**Honest "cannot verify"** = after the fetches in §5.1 and (if needed) Search 1, no explicit first-party statement addresses third-party eligibility either way. In that case the retriever MUST report: *"OpenAI's ChatGPT-login OAuth availability to third-party CLIs remains unconfirmed after a targeted primary-source check; only Codex-scoped documentation was found."* Do NOT infer "probably first-party only" from the Anthropic precedent (§1 of the tech scout report) — a policy pattern at one vendor is not evidence about a different vendor's policy. That inference is exactly the anti-pattern flagged in §6 below.

---

## 2. Question 2 — Google Gemini Go SDK Feature Parity (Streaming / Tool Use / Prompt Caching)

### 2.1 FINER Framing

| Criterion | Assessment |
|---|---|
| Feasible | Yes — `pkg.go.dev` godoc and the repo's `examples/` directory are specific, reachable targets not yet tried by the prior dispatch (which only tried repo root + raw README, both inconclusive). |
| Interesting | Yes — sizes the Gemini provider-adapter's maintenance-burden line item in the PRD. |
| Novel | Extends prior work — closes the single largest gap the tech scout report identified ("largest gap in this dispatch"). |
| Ethical | None. |
| Relevant | High — Gemini was added as a first-class provider after the Go language ADR; this is the first real sizing of its adapter cost. |

### 2.2 Definitive Answer vs. Honest "Cannot Verify"

**Definitive answer** = for EACH of the three features independently (streaming, tool/function calling, prompt caching), either a godoc type/method signature on `pkg.go.dev` (e.g., a `GenerateContentStream` method, a `Tool`/`FunctionDeclaration` type, a `CachedContent` type or `CreateCachedContent` method) or a working example in the repo's `examples/` directory that demonstrates it.

**Honest "cannot verify"** = report per-feature, not as one bundled verdict. It is entirely possible streaming is confirmed while caching remains unverified — that must be reported as three separate findings, not collapsed into "Gemini Go SDK status: unclear." A feature not found in godoc or examples is reported as **UNVERIFIED**, never as "absent" or "not supported" (see §6 anti-pattern — Gemini's own pre-1.0 versioning warning already confirms active churn, so a documentation gap could mean "not yet documented" rather than "not implemented").

---

## 3. Question 3 — Prior Art on Shipped Specialist-Agent Corpora

### 3.1 FINER Framing, with Explicit NOVEL Test

| Criterion | Assessment |
|---|---|
| Feasible | **Lowest of the three.** This is open-ended landscape discovery with no known target URL, inside a single-search budget (plus one reallocated search under §0's rule). Flag this explicitly to whoever reads the findings: this question is at the highest risk of an under-covered answer, and that risk is inherent to the budget, not a retriever execution failure. |
| Interesting | Yes — this is LordCode's stated primary differentiator. |
| **Novel** — apply literally, per research-methodology-core §2.3: "confirms, refutes, or extends prior work" | This question is *itself* a novelty test on LordCode's own claim. A finding that a comparable vendor-shipped corpus already exists **REFUTES** LordCode's differentiation claim and must be reported as such, prominently — this is exactly the "expensive false negative" the task brief warns about, so a positive prior-art finding is not a disappointing result to soften, it is the single most decision-relevant possible outcome of this entire protocol. A well-searched absence is a much weaker **do-not-refute** signal (see §1.2 of source-evaluation-credibility-core's anti-patterns: absence of evidence ≠ evidence of absence) and must be reported at correspondingly lower confidence. |
| Ethical | None. |
| Relevant | Highest stated importance of the three questions — this is explicitly LordCode's positioning claim. |

### 3.2 Definitive Answer vs. Honest "Cannot Verify"

**Definitive answer (REFUTING finding)** = a named, currently-shipping coding tool/CLI/agent framework with primary-sourced documentation (its own docs, README, or product page — not a third-party comparison blog) describing an order-of-magnitude-comparable (hundreds, not a handful of ~5-15 roles) pre-built, vendor-curated library of named specialist personas that ships *inside* the product (compiled/bundled/embedded), as opposed to a framework where users author or the runtime spawns generic/unnamed agents on demand.

**Honest "cannot verify" (weak non-refuting finding)** = after the search and fetches in §5.3, no such product is found among the candidates actually checked. This MUST be reported as: *"No comparable prior art found among the candidates searched in this pass (see list of candidates checked). This is a search-budget-limited finding, not an exhaustive-landscape finding, and should not be cited as confirming novelty without the dedicated follow-up dispatch the tech scout report already recommended (Follow-up #5)."* Never upgrade this to "no prior art exists" or "confirmed differentiator."

---

## 4. Source Tier Order (apply to every fetched/found source, all three questions)

1. **PRIMARY** — official vendor documentation, official GitHub org repos (README, CHANGELOG, `examples/`), official godoc (`pkg.go.dev`), fetched directly by the retriever itself in this dispatch.
2. **SECONDARY** — independent journalism, established community references (e.g., a well-known engineering blog, a maintainer's own non-vendor blog), fetched directly.
3. **SEARCH-SYNTHESIS** — anything seen only via a `WebSearch` result summary/snippet and not independently opened with `WebFetch`. Weakest tier. Never promote a search-synthesis-tier claim to a definitive answer under §1.2/§2.2/§3.2 — it can only support a "cannot verify, weak signal" characterization.

This mirrors the tier discipline the tech scout report already used throughout — continue it, do not regress to a lower evidentiary standard for these three follow-up questions.

---

## 5. Search Budget Allocation — Exact Executable Strings

### 5.1 Question 1 — Pre-Search Fetches (spend zero search budget first)

Fetch, in this order, stopping as soon as §1.2's definitive-answer bar is met:
1. `https://developers.openai.com/codex/auth`
2. `https://developers.openai.com/codex/auth#sign-in-with-an-api-key`
3. `https://platform.openai.com/docs/guides/authentication` (or the current OpenAI Platform auth/OAuth guide reachable from the platform docs nav — fetch the platform docs index first if this exact slug 404s, then follow the authentication link)

**Search 1 (spend ONLY if the three fetches above do not produce a definitive answer per §1.2):**

```
"sign in with ChatGPT" OAuth third-party site:developers.openai.com OR site:platform.openai.com
```

Fallback string (use only if Search 1 returns zero relevant results):

```
"Sign in with ChatGPT" OAuth "third-party" apps -codex site:openai.com
```

### 5.2 Question 2 — Pre-Search Fetches (spend zero search budget first)

Fetch, in this order — these are DIFFERENT URLs from the two that already failed in the prior dispatch (repo root, raw README), per the tech scout report's own Recommended Follow-up #4:
1. `https://pkg.go.dev/google.golang.org/genai` (godoc — check the exported type/method list directly for `Stream`, `Tool`/`FunctionDeclaration`, `CachedContent`)
2. `https://github.com/googleapis/go-genai/tree/main/examples` (examples directory listing — open any example filenames matching streaming/tool/cache)
3. `https://github.com/googleapis/go-genai/blob/main/CHANGELOG.md` (raw CHANGELOG — this exact approach is what produced high-confidence, dated findings for the Anthropic Go SDK in the prior dispatch; replicate it here)

**Search 2 (spend ONLY if the three fetches above leave one or more of the three features unresolved per §2.2):**

```
site:pkg.go.dev google.golang.org/genai stream OR "function calling" OR "cached content"
```

Fallback string:

```
"go-genai" OR "google.golang.org/genai" examples GenerateContentStream FunctionCall CachedContent site:github.com
```

### 5.3 Question 3 — Search-First (no known target URL)

**Search 3 (always spend — this question has no free-fetch shortcut):**

```
coding CLI "hundreds of" OR "500+" pre-built specialist agents shipped -jobs -hiring
```

Fallback string (use only if Search 3 returns zero relevant results, or if results are dominated by job postings/recruiting content despite the `-jobs -hiring` exclusion):

```
"specialist agent" library compiled binary coding assistant CLI -jobs site:github.com OR site:producthunt.com
```

**If §0's reallocation rule frees a second search for Q3**, use this as the follow-up query, refined toward whichever candidate category the first Search 3 surfaced (e.g., if it surfaced multi-agent orchestration frameworks like CrewAI/AutoGen/MetaGPT, refine toward those specifically; if it surfaced coding-CLI competitors, refine toward those):

```
"agent library" OR "agent marketplace" OR "agent catalog" hundreds specialists coding tool vendor-shipped -tutorial
```

After Search 3 (and its optional follow-up) return candidates, spend free `WebFetch` calls (not counted against budget) on the **top 3-5 most promising candidate URLs** — prioritize each candidate's own product/docs page over any secondary comparison article, per §4's tier order. Known candidates already touched by the prior dispatch (do not re-search these blindly, but do fetch their own docs directly if a new angle emerges): Claude Code subagents/marketplace, OpenAI Codex CLI manager-worker model, OpenCode. Also worth a direct fetch if surfaced: CrewAI, AutoGen, MetaGPT, ChatDev, Cline, Aider — check specifically whether any of these ships a **pre-built, hundreds-scale, vendor-curated** corpus (per §3.2's definitive-answer bar) rather than a **user-authored or spawned-on-demand** agent model (which all of the prior dispatch's candidates turned out to be).

---

## 6. Anti-Pattern Reminder (binding on the retriever for all three questions)

**Absence of evidence is not evidence of absence.** A search or fetch returning nothing relevant means: *report the gap explicitly, using the exact "honest cannot verify" language specified in §1.2 / §2.2 / §3.2 for that question.* It never means "assume the negative," "assume policy parity with a different vendor," or "assume the feature is unsupported." This is the single most important constraint governing every output of this protocol — restated here because Q3 in particular carries a natural temptation to report a clean absence as a confirmed differentiator, which the FINER/novel analysis in §3.1 explicitly warns against.

**Recency cut-off (technology domain, λ = 1.39/yr, ~6-month half-life, per source-evaluation-credibility-core §M5):** Today is 2026-09-04. Any source whose publish/last-updated date cannot be established, or that predates roughly 2026-03-04, must be flagged as stale and cannot be presented as describing current state without an explicit caveat. This applies most sharply to Q3's competitor landscape (a fast-moving space) and to any blog-sourced claim about Gemini's SDK (Q2) or API billing terms — consistent with the tech scout report's own treatment of the unfetched "Flash-only free tier" blog claim, which it correctly refused to adopt as verified.

---

## 7. CRAAP Screening Thresholds (apply before passing any source's claim through to the findings writeup)

Use the default weighted CRAAP formula from source-evaluation-credibility-core §M1 (no technology-specific override weighting is defined in the loaded skill, so use the stated defaults):

```
CredScore = 0.15·Currency + 0.20·Relevance + 0.25·Authority + 0.25·Accuracy + 0.15·Purpose
```

Decision rule:
- **CredScore ≥ 7.5** → reliable, cite directly.
- **CredScore 5.0–7.4** → usable, but must be corroborated by at least one independent source category before appearing in a definitive-answer finding (not required for an honest-gap finding).
- **CredScore < 5.0** → reject, or cite only as a flagged "unverified blog claim" the way the tech scout report handled the Gemini free-tier blog post.

**Fast-path scoring for this dispatch:** an official vendor doc/repo/godoc page fetched directly (PRIMARY tier per §4) scores Authority=10, Accuracy=9-10 by construction; do not spend retriever effort re-deriving a full CRAAP breakdown for every PRIMARY source — reserve explicit CRAAP scoring for any SECONDARY or SEARCH-SYNTHESIS source that is being seriously considered for inclusion in a definitive-answer finding (this should be rare, per §1.2/§2.2/§3.2's definitive-answer bars, which are written to require PRIMARY-tier evidence).

---

## 8. Stopping Rules and Saturation Criteria

| Question | Stop when... | Saturation criterion |
|---|---|---|
| Q1 | An explicit first-party statement on eligibility is found (stop immediately, do not spend the search), OR the pre-search fetches + Search 1 (+ fallback string) are exhausted with no explicit statement found. | One explicit, on-domain statement is sufficient to stop — this is a binary eligibility question, not a claim requiring triangulation across independent sources. |
| Q2 | All three sub-features (streaming, tools, caching) are each independently resolved (confirmed present, confirmed absent, or explicitly UNVERIFIED) after the three fetches + Search 2 (+ fallback). | Godoc method/type signatures are sufficient per feature — do not require a second independent source for an SDK's own documented API surface. |
| Q3 | Search 3 (+ optional reallocated second search) plus fetches on the top 3-5 candidates are exhausted. | Two consecutive fetched candidate sources that fail to meet §3.2's definitive-answer bar (hundreds-scale, vendor-curated, pre-built) count as saturation for "no prior art found in this pass" — do not continue fetching indefinitely once that pattern is established, but do not stop after only one negative candidate either. |

---

## 9. GRADE Handoff — What research-synthesis-analyst Must Grade

**Adaptation note:** GRADE (source-evaluation-credibility-core §4) is defined for evidence from research studies feeding a systematic review. These three questions are technology-verification questions, not clinical/scientific claims with study designs — so research-synthesis-analyst should apply GRADE's **certainty-level structure** (HIGH / MODERATE / LOW / VERY LOW, per §4.2) as a qualitative analog, not the literal RCT/observational-study downgrade mechanics of §4.1. Certainty should be driven by: source tier (§4 above), directness (does the source address the exact question, or require inference), and corroboration count — this is consistent with the skill's own §5 triangulation methods and Bayesian credibility updating (§M4) rather than a misapplication of clinical GRADE machinery.

All three questions' findings require GRADE-style certainty labeling:
- **Q1**: label the eligibility finding (or the honest-gap finding) HIGH only if a single explicit on-domain PRIMARY statement is found; otherwise VERY LOW/gap.
- **Q2**: label EACH of the three sub-features independently — do not assign one blended certainty level across streaming/tools/caching.
- **Q3**: given §3.1's explicit novelty stakes, this finding's certainty label carries the most downstream weight of the three. A REFUTING finding (prior art found) should be labeled per how directly the found product's own docs describe the corpus (PRIMARY + directly on-point = HIGH). A non-refuting/absence finding must be capped at LOW or VERY LOW per §6's anti-pattern — GRADE has no mechanism to promote a single-search-pass absence to HIGH certainty, and research-synthesis-analyst should not invent one.

---

## 10. Research Brief Skeleton (for deep-web-researcher to populate and hand to research-synthesis-analyst)

```markdown
# Research Findings — Phase 0.2 Gap Closure

## Q1 — OpenAI ChatGPT-Login OAuth: Third-Party Availability
- Fetches performed: [URLs + fetch outcome]
- Search 1 spent? [yes/no — if no, state which fetch resolved it]
- Finding: [definitive statement OR honest-gap statement per §1.2]
- Source tier: [PRIMARY/SECONDARY/SEARCH-SYNTHESIS]
- Recency check: [date of source vs. 2026-03-04 cutoff]
- CRAAP score (if SECONDARY/SEARCH-SYNTHESIS used): [score + rule applied]

## Q2 — Gemini Go SDK Feature Parity
- Fetches performed: [URLs + fetch outcome]
- Search 2 spent? [yes/no]
- Streaming: [confirmed/absent/UNVERIFIED + source]
- Tool/function calling: [confirmed/absent/UNVERIFIED + source]
- Prompt caching: [confirmed/absent/UNVERIFIED + source]
- Recency check per source used

## Q3 — Specialist-Agent Corpus Prior Art
- Search 3 spent (mandatory): [query used, result summary]
- Reallocated second search spent? [yes/no + query if yes]
- Candidates fetched: [list, with tier + verdict against §3.2 bar for each]
- Finding: [REFUTING (name the product) OR non-refuting/gap per §3.2]
- Confidence: [per §9's capped-certainty guidance]

## Budget Reconciliation
- Total WebSearch calls used: [N / 3]
- Reallocations applied: [per §0's rule, if any]
- Any question left with an honest gap: [Y/N + which]
```

---

**Status:** complete
**Next:** deep-web-researcher executes this protocol (max 3 `WebSearch` calls, unlimited targeted `WebFetch`), then hands the populated Research Brief (§10) to research-synthesis-analyst for GRADE-style certainty grading (§9).
