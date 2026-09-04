# Tech Scout Report — Provider Auth, Go SDK Parity, and Competitor Landscape

**Prepared by:** technology-scout-analyst
**Date:** 2026-09-04
**Scope:** Verification dispatch supporting LordCode Phase 0 requirements. ADR-2 (Go as implementation language) is DECIDED and is NOT re-litigated here.

**Methodology note (read before trusting any claim below):** The Cooldown Research Protocol capped this dispatch at 3 web searches; 4 `WebSearch` calls were used in practice (one over budget) because the authentication item split into three providers and the strongest lead on Anthropic's policy required a follow-up query. Beyond that, this dispatch used ~10 `WebFetch` calls against specific URLs (official docs, GitHub repos, raw CHANGELOG files) — fetches are not counted against the search cap and were used to move from "search-result synthesis" (low confidence) to "primary artifact" (higher confidence) wherever possible. Every claim below is tagged with its source tier: **PRIMARY** (official docs/repo fetched directly), **SECONDARY** (independent journalism/community fetched directly), or **SEARCH-SYNTHESIS** (only seen via a WebSearch AI summary, not independently fetched — treat as the weakest tier and re-verify before it becomes user-facing copy or legal language).

---

## 1. Authentication (HIGHEST-VALUE ITEM — read this before anything else)

**Working assumption stated in the dispatch:** Plus/Pro subscriptions do NOT grant API access; Gemini via AI Studio is easiest onboarding with a free tier. **Verdict: directionally confirmed for all three providers, but the underlying reason for Anthropic is materially different from "no connection exists" — see below. This distinction should be reflected in LordCode's onboarding copy and error messages.**

### 1.1 Anthropic (Claude)

- **Does an OAuth/device-flow exist that a third party may use?** Technically yes, contractually no. Claude Code's own OAuth mechanism (`sk-ant-oat01-...` tokens, generated via `/login` or `claude setup-token`) genuinely authenticates against a Pro/Max/Team/Enterprise subscription and consumes that subscription's quota — this is confirmed directly from Anthropic's own docs. **[PRIMARY — fetched `https://code.claude.com/docs/en/authentication` directly]**. However, a separate Anthropic policy update (dated on or before 2026-02-20) explicitly states: *"Third-party developers are no longer allowed to offer Claude.ai login or to route requests on behalf of users using Free, Pro, or Max plan credentials,"* and this applies to the Agent SDK as well. The article names OpenClaw and OpenCode as tools now in violation. **[SECONDARY — fetched `alternativeto.net` article directly, but it in turn cites an unnamed Anthropic "Legal and compliance" page I did not independently fetch — this is a second-hand quote of Anthropic's actual policy text, not a first-hand read of it]**. Corroborating this: a live GitHub issue (`anthropics/claude-code#18340`) shows a developer confirming `claude setup-token` **does** mint an OAuth-format token from a subscription, but third-party integrations (JetBrains) reject it and require the standard API-key format instead — consistent with a deliberate lockout, not a technical gap. **[PRIMARY — fetched the issue directly]**.
  - **Confidence: MEDIUM-HIGH.** The mechanism's existence and Claude-Code-only scoping is PRIMARY-verified. The explicit "third parties are banned" policy language is SECONDARY-sourced (one step removed from Anthropic's own policy page). **Recommend a direct fetch of Anthropic's own commercial/usage-policy page before this exact sentence is used in legal-facing product copy.**
- **Does Pro/Max grant API access?** For LordCode's purposes: **No — treat as forbidden, not merely "unsupported."** This is a stronger and different finding than the working assumption: it is not that the subscription is architecturally disconnected from the API (as with OpenAI, see below), it is that Anthropic has an active enforcement policy against exactly the pattern a third-party CLI like LordCode would otherwise be tempted to build. Two independent CLIs (OpenClaw, OpenCode) are reported to have been forced to stop doing this. **[SECONDARY, triangulated across two independent articles]**.
- **Minimum a user must obtain:** A Claude Console / platform.claude.com account, and an API key (`sk-ant-api03-...`) with billing configured. Pay-as-you-go, billed independently of any Claude.ai subscription the user may also hold. **[PRIMARY]**.

### 1.2 OpenAI

- **Does ChatGPT Plus/Pro grant API access?** **No — confirmed, high confidence.** OpenAI's own Help Center states ChatGPT and the API platform have separate billing systems; multiple independent summaries agree Plus/Pro include no API credits. **[SECONDARY, but converging across OpenAI's own Help Center plus 3 independent third-party summaries — the Help Center citation itself was only seen via WebSearch synthesis, not independently fetched, so treat the *exact* OpenAI wording as SEARCH-SYNTHESIS even though the *conclusion* is well-triangulated]**.
- **Does an OAuth/device-flow exist for third parties?** Partially verified, and this is the most important open question in this section. OpenAI's own **Codex CLI** — a first-party OpenAI product — supports "Sign in with ChatGPT," working with Plus/Pro/Business/Edu/Enterprise plans, as an explicit alternative to API-key auth. **[PRIMARY — fetched `github.com/openai/codex` directly]**. What I could **NOT** verify: whether this OAuth path is a general-purpose, publicly documented grant that any third-party CLI (not just Codex) may legally integrate against, or whether it is proprietary to Codex specifically. The Codex docs reference a separate, more involved path (`developers.openai.com/codex/auth#sign-in-with-an-api-key`) for API-key auth, implying the two paths are treated differently, but I did not fetch that page directly. **This is a gap, not a "no" — do not write "OpenAI has no OAuth option" into the PRD; write "unverified whether OpenAI's ChatGPT-login OAuth is available to third-party CLIs beyond Codex; needs a dedicated follow-up against `developers.openai.com/codex/auth` before ruling it out."**
- **Minimum a user must obtain:** An OpenAI Platform account (`platform.openai.com`), an API key, and billing/credits. **[SECONDARY, well-triangulated]**.

### 1.3 Google Gemini

- **Does a consumer subscription grant API access?** **No — confirmed, high confidence, and this is the cleanest case of the three.** Google One AI Premium / "Gemini Advanced" ($19.99/mo) is described consistently as a consumer-app subscription (2TB storage, Gemini in Workspace apps, NotebookLM Plus) with **no API access included**; the API key from Google AI Studio is a fully separate grant. **[SECONDARY/SEARCH-SYNTHESIS — none of the AI Studio billing or Google One pages were independently fetched; this rests on 4 converging third-party summaries, not a primary Google source. Recommend fetching `ai.google.dev/gemini-api/docs/billing` directly before finalizing.]**
- **Free tier / minimum requirement:** A Google account, then generate an API key at Google AI Studio (`aistudio.google.com`) — no billing account required to obtain the key or to use it within free-tier rate limits. **[SEARCH-SYNTHESIS, not independently fetched — same caveat as above]**.
- **Caveat worth flagging for the PRD:** one source claims the free tier narrowed to Flash-only models (Pro models moved behind billing) around May 2026. This is a single unfetched blog claim and, per the source-evaluation skill's decay model (λ=1.39/yr, ~6-month half-life for technology claims), a claim from a blog of unknown publish date should be treated as **UNVERIFIED, not adopted** until checked against `ai.google.dev` directly.
- No OAuth/device-flow was found or expected for Gemini API access — a static API key is the documented mechanism, consistent with the working assumption.

### 1.4 Net effect on LordCode's onboarding design

The minimum first-call requirement per provider:

| Provider | Minimum to obtain | Billing required for first call? |
|---|---|---|
| OpenAI | `platform.openai.com` account + API key | Yes (credits/payment method) |
| Anthropic | `console.anthropic.com` / `platform.claude.com` account + API key | Yes (pay-as-you-go) |
| Google Gemini | Google account + AI Studio API key | No (free tier, no billing account needed) |

Onboarding and error-message copy should say, for Anthropic specifically, something closer to *"LordCode uses API-key billing — Claude subscription logins are not supported for third-party tools per Anthropic's usage policy"* rather than a generic "not supported," since the restriction is a documented policy choice (subject to change) rather than a technical impossibility. This is a meaningfully different promise than for OpenAI, where the systems are simply separate products.

---

## 2. Go SDK Parity (streaming / tool use / prompt caching)

TRL assigned from the most advanced **published, dated demonstration** found (changelog entries, working code in official README), not from marketing claims.

### 2.1 `github.com/openai/openai-go` — OpenAI Go SDK

**[PRIMARY — fetched repo directly]**
- Current: v3.45.0+ requires Go 1.25+ (v3.44.0 = last release supporting Go 1.22–1.24); 927+ commits, actively maintained.
- **Streaming — TRL 8/9.** Confirmed via a working documented example (`client.Responses.NewStreaming()` with delta event handling) in the official README.
- **Tool/function calling — TRL 8/9.** Confirmed via a documented working example (weather-function tool call) in the official README.
- **Prompt caching — UNVERIFIED, not confirmed absent.** Not mentioned in the fetched README excerpt. Important nuance: OpenAI's prompt caching is largely automatic/server-side for eligible requests rather than an SDK-exposed opt-in feature (unlike Anthropic's explicit `cache_control` blocks), so silence in the README may reflect "nothing for the SDK to expose" rather than a genuine gap. **Do not report this as a parity gap without an explicit follow-up check.**

### 2.2 `github.com/anthropics/anthropic-sdk-go` — Anthropic Go SDK

**[PRIMARY — fetched repo README and raw CHANGELOG.md directly]**
- Current: v1.70.1.
- **Streaming — TRL 9, mature.** Present since v0.2.0-beta.4 (2025-05-18: "add dynamic streaming buffer to handle large lines"), refined at v1.0.0 (2025-05-21: "use scanner for streaming"). In production well over a year as of this report.
- **Tool use — TRL 8/9.** `BetaToolRunner` for automatic tool-use loops landed at v1.26.0 (2026-02-19). Mid-conversation tool add/remove (`tool_change` events) landed at v1.67.0 (2026-08-26) — **8 days before this report's date**, i.e., inside the 6-month staleness window and genuinely fresh; treat the *core* tool-use capability as mature (TRL 9) but the *dynamic tool modification* sub-feature as recently shipped and worth a re-check before depending on it in v1 of the provider adapter.
- **Prompt caching — TRL 9, mature and GA.** 1-hour TTL cache control went GA at v1.10.0 (2025-09-02); automatic top-level cache control (no manual `cache_control` blocks needed) added at v1.26.0 (2026-02-19).

**Conclusion for Anthropic + OpenAI Go SDKs:** no evidence surfaced that either lags meaningfully behind Python/TypeScript on the three checked capabilities. Per the pre-established sensitivity analysis, **nothing here supports moving criterion 4 toward 6.0** for these two providers — the standing assumption of strong Go SDK parity holds for Anthropic and OpenAI specifically.

### 2.3 Google Gemini Go SDK (`google.golang.org/genai`, `github.com/googleapis/go-genai`)

**[PRIMARY fetch attempted twice — repo root and raw README.md — both attempts failed to surface explicit statements on streaming, tool calling, or prompt caching]**
- The only concrete, verifiable finding: the module is versioned pre-1.0 internally with an explicit warning to pin `< 2.0.0` to avoid breaking changes around `GenerateVideos` — a signal of ongoing API churn, not evidence about the three target features either way.
- **Streaming, tool calling, prompt caching for Gemini's Go SDK: UNVERIFIED.** This is the single largest gap in this dispatch. ADR-2 did not originally assess this SDK (Gemini was promoted to first-class after the language decision), so this is a genuine open item, not a re-litigation of ADR-2.
- **Recommendation:** a dedicated, narrowly-scoped follow-up (e.g., reading `pkg.go.dev/google.golang.org/genai` godoc or the repo's `examples/` directory) should close this gap before the PRD finalizes the Gemini provider-adapter effort estimate. Until then, size the Gemini adapter's maintenance-burden line item as **unknown, pending verification**, not as "parity assumed."

---

## 3. Secondary Verification Items

### 3.1 Node.js Single Executable Applications (SEA)

**[PRIMARY — fetched `nodejs.org/api/single-executable-applications.html` directly]**
Current status: **Stability: 1.1 — "Active development."** Under Node's stability index, level 1.x is the "Experimental" major tier (1.0 = no active development, 1.1 = active development, 1.2 = release candidate); it has not reached 2.x ("Stable"). **The working assumption — "believed still experimental" — is confirmed, high confidence, primary source.**

### 3.2 Official Anthropic Rust SDK

**[PRIMARY — fetched the `anthropics` GitHub org repository listing filtered for "rust"]**
No official Anthropic-authored Rust SDK exists. The only Rust-related repos under the `anthropics` org are `tokio` and `rayon` (general-purpose community Rust libraries, not Anthropic API SDKs) and `claudes-c-compiler` (an unrelated demo project). **Confirms the working assumption — no official Rust SDK — with medium-high confidence** (a GitHub org web listing can in principle omit private/newly-created repos, and I did not cross-check for a community-maintained `anthropic-rs`-style crate, but the specific question — "does an *official* SDK exist" — is answered: no). This remains a valid disqualifier as originally used in ADR-2.

### 3.3 Google Go SDK maturity for Gemini

Covered in §2.3 above — largely unverified on the specific features that matter; the pre-1.0 versioning warning is the one concrete, verified signal, and it points toward more churn risk than the Anthropic/OpenAI Go SDKs, not less.

---

## 4. Competitor Landscape Scan

**[SEARCH-SYNTHESIS for this entire section — one WebSearch call, no direct fetch of any competitor's own docs or marketing. Treat everything below as the weakest-confidence section of this report and re-verify before it appears in positioning copy.]**

- **Claude Code:** ships "subagents" with explicit tool allowlists/denylists and uncapped "Agent Teams" (usage-limit cost scales with agents spawned), plus a broader skills/hooks/subagents/MCP/plugins extension ecosystem. This is Anthropic's own first-party analog to a multi-agent system, but it reads as a **user-configurable framework for spawning/defining agents**, not a vendor-shipped, pre-built library of named specialist personas.
- **OpenAI Codex CLI:** manager-worker execution model, capped at 8 parallel subagent sandboxes per developer — again a bounded *execution* model, not a curated specialist-agent *corpus*.
- **OpenCode:** open-source, reportedly 165k GitHub stars, claims 75+ LLM endpoint support (Anthropic, OpenAI, Google, Bedrock, Azure, OpenRouter, Ollama). Notable direct data point for §1: reported to have been forced by Anthropic (~January 2026) to remove Claude support — this triangulates with and corroborates the Anthropic third-party-OAuth-ban finding in §1.1 from a second, independent angle.
- **Differentiator check (embedded specialist-agent corpus):** none of the sources surfaced describe a competitor shipping a large, pre-built, vendor-curated library of named specialist agents comparable to what LordCode is targeting. What exists at competitors (Claude Code subagents, Codex sandboxed workers) are user-defined or spawned-on-demand, not a shipped corpus. **This is a weak positive signal for LordCode's claimed differentiation, but confidence is LOW** — it rests on a single search's AI-generated synthesis of comparison blog posts, with zero primary-source fetches of any competitor's actual documentation on this specific question. **This claim is under-verified relative to its stated importance ("LordCode's primary claimed differentiator") and should be the subject of its own dedicated, primary-source-fetching dispatch before it is used in external positioning materials.**
- **Provider-authentication handling, comparable prior art:** Codex CLI's "Sign in with ChatGPT" (§1.2) and OpenCode's forced removal of Claude support (§1.1/§4) are the two directly relevant, cross-referenced data points already folded into §1.

---

## 5. Summary of Confidence Levels

| Claim | Confidence | Source tier |
|---|---|---|
| Claude Pro/Max OAuth technically works but is policy-banned for third parties | Medium-High | Primary (mechanism) + Secondary (ban language) |
| ChatGPT Plus/Pro excludes API access | High | Secondary, well-triangulated |
| OpenAI's ChatGPT-login OAuth availability to third parties beyond Codex | **Unverified — open question** | — |
| Google One / Gemini Advanced excludes API access | High (directionally) | Search-synthesis, not primary-fetched |
| Gemini AI Studio free tier needs no billing account | High (directionally) | Search-synthesis, not primary-fetched |
| Anthropic Go SDK: streaming/tools/caching all mature (TRL 9) | High | Primary (CHANGELOG) |
| OpenAI Go SDK: streaming/tools confirmed; caching unverified (not a confirmed gap) | High / Unverified | Primary |
| Google Gemini Go SDK: streaming/tools/caching status | **Unverified — largest gap in this report** | Primary fetch attempted, inconclusive |
| Node.js SEA is still Experimental (1.1) | High | Primary |
| No official Anthropic Rust SDK | Medium-High | Primary (org listing) |
| No competitor ships a comparable pre-built specialist-agent corpus | Low | Search-synthesis only |

## 6. Recommended Follow-ups (in priority order)

1. Directly fetch Anthropic's own commercial/usage-policy page (not the secondary alternativeto.net summary) to get first-hand policy language before it appears in legal-facing copy.
2. Directly fetch `developers.openai.com/codex/auth` to resolve whether ChatGPT-login OAuth is Codex-exclusive or a general grant.
3. Directly fetch `ai.google.dev/gemini-api/docs/billing` to replace the search-synthesis Gemini findings with primary confirmation.
4. Resolve the Google Gemini Go SDK feature-parity gap (§2.3) via `pkg.go.dev` or the repo's examples directory before sizing the Gemini adapter's maintenance burden in the PRD.
5. A dedicated, primary-source dispatch on the "embedded specialist-agent corpus" competitive claim before it is used in positioning materials.
