# Research Findings — Phase 0.2 Gap Closure

**Prepared by:** deep-web-researcher
**Date:** 2026-09-04
**Protocol executed:** `docs/phase-0-requirements/research_protocol.md` (research-strategist, 2026-09-04) — executed as designed, not redesigned.
**Role boundary:** This document RETRIEVES and SCREENS sources only. It does not grade evidence or draw conclusions — that is `research-synthesis-analyst`'s job per §9 of the protocol (GRADE-style certainty labeling).

---

## Q1 — OpenAI ChatGPT-Login OAuth: Third-Party Availability

**Fetches performed:**
| URL requested | Outcome |
|---|---|
| `https://developers.openai.com/codex/auth` | 308 redirect → `https://learn.chatgpt.com/docs/auth` (fetched, see below) |
| `https://developers.openai.com/codex/auth#sign-in-with-an-api-key` | 308 redirect → same target as above |
| `https://platform.openai.com/docs/guides/authentication` | 301 redirect → `https://developers.openai.com/api/docs/guides/authentication` → **404 Not Found** |
| `https://learn.chatgpt.com/docs/auth` (redirect target, fetched) | Live page fetched. States: *"The ChatGPT desktop app, Codex CLI, and IDE extension support both sign-in methods for local work."* Scope is limited to these three OpenAI-owned products. No mention of third-party OAuth client registration, no explicit statement admitting or excluding third-party CLIs. No visible last-updated date on the page. |
| `https://techcrunch.com/2025/05/27/openai-may-soon-let-you-sign-in-with-chatgpt-for-other-apps/` (fetched for dating/context after Search 1) | Article dated **2025-05-27**. States OpenAI "is exploring ways for users to sign in to third-party apps using their ChatGPT account" and "is currently gauging interest from developers" — described explicitly as exploratory/not-yet-shipped for general third parties, with timeline "unclear." The only shipped item named is "a preview of the 'Sign in with ChatGPT' experience for developers in Codex CLI" (i.e., the same Codex-scoped mechanism already covered by the PRIMARY source above). |

**Search 1 spent?** **Yes.** Fetches did not meet the §1.2 definitive-answer bar (an explicit first-party statement naming third-party eligibility either way). Query executed:
```
"sign in with ChatGPT" OAuth third-party site:developers.openai.com OR site:platform.openai.com
```
Results did not return content from `developers.openai.com` or `platform.openai.com` specifically (search engine returned general web results instead — Wikipedia, TechCrunch, an AOL syndication of the same TechCrunch piece, and unrelated GitHub repos). Result count was non-zero, so the fallback string's trigger condition ("zero relevant results") was not met and the fallback was not spent — remaining budget was preserved for Q3 per §0's reallocation priority.

**Finding:** **Honest "cannot verify."** Per §1.2's required language: *OpenAI's ChatGPT-login OAuth availability to third-party CLIs remains unconfirmed after a targeted primary-source check; only Codex-scoped documentation was found.* The current live OpenAI/ChatGPT-Learn documentation describes the OAuth sign-in flow only in terms of OpenAI's own products (ChatGPT desktop app, Codex CLI, IDE extension) — this is implicit scoping by omission, not an explicit statement that third parties are included or excluded. A stale (15+ months old) secondary source indicates OpenAI was, as of May 2025, exploring a *general* third-party "Sign in with ChatGPT" capability separate from the Codex-specific preview, with no confirmed shipped/general-availability date found in this pass. No inference toward "probably first-party only" is drawn from the Anthropic precedent, per the protocol's explicit prohibition on that cross-vendor inference.

**Source tier:** PRIMARY (`learn.chatgpt.com/docs/auth` — current live OpenAI-owned doc, for the scoping observation) + SECONDARY (TechCrunch, for the exploratory-feature context only, not used to support any definitive claim).

**Recency check:** `learn.chatgpt.com/docs/auth` — no visible date; treated as current since it is the live, currently-served page. TechCrunch source — 2025-05-27, which is **STALE** relative to the 2026-03-04 cutoff (roughly 15 months old against Technology's ~6-month half-life, λ=1.39/yr → decay weight w ≈ e^(-1.39×1.25) ≈ 0.19, i.e., ~81% decayed). Used only as historical/exploratory context, never as a claim about current state.

**CRAAP score (TechCrunch, SECONDARY, used only for context, not a definitive claim):** Currency scores very low (stale, ~19% residual credibility weight under the decay model); Authority/Accuracy are reasonable for a named tech-industry publication reporting on record. Per §7's fast-path rule, no full CRAAP breakdown was computed since this source does not appear in a definitive-answer finding — it is cited only to explain why the honest-gap finding includes exploratory context.

---

## Q2 — Gemini Go SDK Feature Parity

**Fetches performed:**
| URL | Outcome |
|---|---|
| `https://pkg.go.dev/google.golang.org/genai` | Fetched successfully. Godoc confirms exported API surface for all three features (see below). |
| `https://github.com/googleapis/go-genai/tree/main/examples` | Fetched successfully. Directory listing: `batches, caches, chats, files, filesearchstores, live, live_with_ephemeral_token, mcptoolbox, models, tunings`. `caches/` directly names caching; `live/` and `chats/` correspond to streaming; `mcptoolbox/` corresponds to tool integration. |
| `https://github.com/googleapis/go-genai/blob/main/CHANGELOG.md` | Fetched successfully (raw CHANGELOG). Dated entries found for all three features (below). |

**Search 2 spent?** **No.** All three sub-features were independently resolved to CONFIRMED status via PRIMARY-tier fetches alone (godoc + CHANGELOG + examples directory), meeting §2.2's definitive-answer bar without needing the allocated search. This search was reallocated to Q3 per §0.

**Streaming:** **CONFIRMED present.**
- Godoc: `Models.GenerateContentStream(ctx, model, contents, config)`, `Chat.SendStream(ctx, ...*Part)`, `Chat.SendMessageStream(ctx, ...Part)` — all return `iter.Seq2[*GenerateContentResponse, error]`.
- CHANGELOG: v1.0.0 (2025-04-09) "Add support for Chats streaming in Go SDK"; v1.5.0 (2025-05-13) Send/SendStream methods added to chats module.
- Source: PRIMARY (pkg.go.dev + raw CHANGELOG.md, both fetched directly).

**Tool/function calling:** **CONFIRMED present.**
- Godoc: `type Tool`, `type FunctionDeclaration`, `type FunctionCall`, `type FunctionResponse`, `type FunctionCallingConfig`, `type FunctionCallingConfigMode`; helpers `NewPartFromFunctionCall(...)`, `NewPartFromFunctionResponse(...)`.
- CHANGELOG: v1.22.0 (2025-08-27) "Add VALIDATED mode into FunctionCallingConfigMode"; v1.26.0 (2025-09-25) "Add FunctionResponsePart & ToolComputerUse.excludedPredefinedFunctions"; v1.36.0 (2025-11-17) "support Function call argument streaming for all languages."
- Source: PRIMARY (pkg.go.dev + raw CHANGELOG.md, both fetched directly).

**Prompt caching:** **CONFIRMED present.**
- Godoc: `type CachedContent`; `Caches.Create(ctx, model, config)`, `Caches.Get(...)`, `Caches.Update(...)`, `Caches.Delete(...)`; `type CreateCachedContentConfig`, `type UpdateCachedContentConfig`.
- CHANGELOG: v0.1.0 (2025-01-29) "support caches create/update/get/update in Go SDK"; v1.6.0 (2025-05-19) "support customer-managed encryption key in cached content."
- Source: PRIMARY (pkg.go.dev + raw CHANGELOG.md, both fetched directly).

**Recency check:** The godoc listing itself (`pkg.go.dev/google.golang.org/genai`) reflects the **currently published, live API surface** as of retrieval on 2026-09-04 — i.e., these three features are present in the SDK *right now*, not merely "were added at some point historically." Individual CHANGELOG dates (Jan 2025 – Nov 2025) establish when each capability was introduced/matured but do not themselves need to fall inside the 6-month recency window, because the claim being verified ("does the current SDK support X") is anchored to the live godoc snapshot, which is current by construction. This fully closes the tech scout report's self-identified "largest gap in this dispatch" (§2.3 of that report) and reverses it from UNVERIFIED to CONFIRMED for all three sub-features.

---

## Q3 — Specialist-Agent Corpus Prior Art

**Search 3 spent (mandatory):**
```
coding CLI "hundreds of" OR "500+" pre-built specialist agents shipped -jobs -hiring
```
Result summary: Surfaced `great_cto` (34 specialist agents across SDLC roles, cross-tool via AGENTS.md+MCP — below hundreds-scale), `open-claude-cowork` (500+ *SaaS integrations*, not specialist personas — different category of claim), Kilo CLI (500+ hosted *models* via a gateway, not agents), and `OpenCastle` (19 coordinated specialist agents). None reached the hundreds-scale, vendor-curated bar.

**Reallocated second search spent?** **Yes** (Q2's unspent allocation, per §0's stated priority Q3 > Q2 > Q1):
```
"agent library" OR "agent marketplace" OR "agent catalog" hundreds specialists coding tool vendor-shipped -tutorial
```
Result summary: Surfaced stronger-sounding candidates — **AgentsRoom** ("14 core roles" + "270 expert agents from The Agency" + "a growing marketplace of agents created by the community"), a **claude-skills library** referenced by a TechTimes article (345 packages including 51 senior-engineering personas, portable across Claude Code/Codex/Cursor/Gemini CLI), **agency-agents** (msitarzewski, 230+ personas), and **Nagent AI Marketplace** ("hundreds of pre-vetted AI agents").

**Candidates fetched:**

| Candidate | Fetch outcome | Tier | Verdict vs. §3.2 bar |
|---|---|---|---|
| `github.com/msitarzewski/agency-agents` | Fetched successfully (README) | PRIMARY | **Does NOT meet bar.** Confirms "230+ Specialized Agents" but explicitly community-contributed and separately installed by users via scripts into each target tool's own agent directory (Claude Code, Copilot, Cursor, OpenCode, etc.) — not bundled/embedded inside a single vendor's product. |
| `mcpservers.org/agent-skills` | Fetched successfully | PRIMARY | **Does NOT meet bar.** Explicitly a multi-contributor community marketplace/directory (skills published independently by Anthropic, OpenAI, GitHub, Microsoft, Vercel, and community authors); tools "can *use*" these skills but do not ship them pre-installed. Manual installation required. |
| `agentsroom.dev/agents` and `agentsroom.dev/` (root) | **FETCH FAILED** — HTTP 413 Payload Too Large, both attempts | SEARCH-SYNTHESIS only (unverifiable in this pass) | **Cannot be resolved either way.** Search-engine summary phrasing separates "270 expert agents from **The Agency**" (a possibly separately-branded product/integration) from "a growing marketplace... created by the community," which if accurate would place this in the same community-marketplace pattern as the other candidates — but this cannot be confirmed from a primary source in this pass. |
| `techtimes.com` article (345-package / 51-persona claude-skills library) | **FETCH FAILED** — HTTP 403 Forbidden, twice; underlying GitHub repo also not locatable via a targeted GitHub search (0 results) | SEARCH-SYNTHESIS only (unverifiable in this pass) | **Cannot be resolved either way.** |
| `g2.com/products/nagent-ai/discuss` | **FETCH FAILED** — HTTP 403 Forbidden | SEARCH-SYNTHESIS only | Even at SEARCH-SYNTHESIS tier, the search snippet itself described Nagent AI as a "cloud-based catalog" of agents "built by a domain specialist" (plural/multi-party) — i.e., self-describes as a marketplace, not a single vendor's own bundled corpus, so it would not meet the bar even if independently verified, but this was not confirmed via direct fetch. |

**Finding:** **Non-refuting / honest gap**, per §3.2. Every candidate independently verified via a direct PRIMARY-tier fetch (`agency-agents`, `mcpservers.org/agent-skills`) turned out to follow the same pattern already identified by the tech scout report for Claude Code subagents, Codex CLI, and OpenCode: a **community-contributed, user-installed marketplace/directory**, not a single vendor's pre-built corpus shipped *inside* a product. Two consecutive fetched candidates failing the §3.2 bar were obtained, meeting the protocol's stated saturation criterion (§8). Two further candidates with stronger surface-level numbers (AgentsRoom's "270 expert agents"; the TechTimes-reported 345-package/51-persona claude-skills library) could **not** be independently verified in this pass (repeated 413/403 fetch failures) and remain at SEARCH-SYNTHESIS tier only, which per §4 can never support a definitive finding in either direction. Per §3.2's exact required language: *"No comparable prior art found among the candidates searched in this pass (see list of candidates checked). This is a search-budget-limited finding, not an exhaustive-landscape finding, and should not be cited as confirming novelty without the dedicated follow-up dispatch the tech scout report already recommended (Follow-up #5)."* The AgentsRoom and claude-skills/345-package leads specifically should be the first targets of that follow-up dispatch, since they are the two candidates in this entire research effort (across both the tech scout report and this dispatch) that used "hundreds"-scale language and were not ruled out — they were simply inaccessible to this pass's fetch attempts, not confirmed absent.

**Confidence:** LOW to VERY LOW for the "no comparable prior art found in this pass" finding, per §9's capped-certainty guidance for a non-refuting Q3 finding — explicitly a fetch/search-budget-limited result, not an exhaustive-landscape finding. Must not be cited as confirming LordCode's differentiation claim without the recommended follow-up.

---

## Budget Reconciliation

- **Total WebSearch calls used: 3 / 3**
  - Q1: 1 (primary string only — fallback not triggered, since Search 1 returned non-zero/relevant-but-inconclusive results, not zero results)
  - Q2: 0 (fully resolved via free, unlimited WebFetch against `pkg.go.dev` godoc + raw CHANGELOG.md + examples directory listing)
  - Q3: 2 (mandatory Search 3, plus one reallocated search using Q2's unspent allocation, per §0)
- **Reallocations applied:** Yes. Q2 required zero of its allocated search budget, and per §0's explicit priority order (Q3 > Q2 > Q1) that unspent search was reallocated to Q3 as its second search. Q1's fallback string was available but was not spent — its trigger condition ("Search 1 returns zero relevant results") was not met, and remaining discretionary effort was directed to Q3 per the protocol's stated priority.
- **Total WebFetch calls used:** approximately 17 (unlimited/free, not counted against the cap) — 6 for Q1 (including two redirect follow-throughs and one context fetch of the TechCrunch article), 3 for Q2, and roughly 8 for Q3 (including 4 fetch failures: two HTTP 413 on AgentsRoom, two HTTP 403 on TechTimes/G2, plus one zero-result GitHub search).
- **Any question left with an honest gap:** **Yes — two of three.**
  - **Q1**: Third-party OAuth eligibility for OpenAI's "Sign in with ChatGPT" remains unconfirmed — current docs scope the flow to OpenAI's own products only, by omission rather than explicit statement; a stale (2025-05) secondary source describes a general third-party version as exploratory/unshipped as of that date, with no more current confirmation found.
  - **Q3**: Overall finding is non-refuting (no confirmed comparable prior art among candidates actually verified), but two promising leads (AgentsRoom, the 345-package/51-persona claude-skills library) remain genuinely unverified due to repeated fetch failures (HTTP 413/403), not confirmed to fail the bar — these require a dedicated follow-up dispatch before Q3's finding can be treated as more than provisional.
  - **Q2 has no gap** — fully resolved, all three sub-features independently CONFIRMED via PRIMARY-tier evidence.
