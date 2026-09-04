# LordCode

**An agentic AI coding CLI that runs your whole SDLC — with 528 specialist agents compiled in, across any model you already pay for.**

> **Status: pre-implementation.** The architecture is designed and the orchestration plan is complete; no code has been written yet. There is nothing to install today. See [Status](#status) for exactly where things stand and [`docs/orchestration_prompt.md`](docs/orchestration_prompt.md) for the full design.

---

## Overview

Most AI coding tools give you one model and one loop, and expect you to write the prompts. LordCode is built on a different bet.

**1. The whole specialist library is compiled into the binary.**
Not a plugin registry, not a prompt folder you maintain. **528 agents, 1034 skills, 104 domain knowledge graphs, 77 mathematics specialists, 9,146 typed graph edges, 368 mapped regulations** — code-generated into Go source and compiled in. Each agent is a grounded persona carrying its own first-principles derivations, worked examples, and operating rules. You never author an agent or a skill; the capability set is already complete.

Because it is *code* rather than embedded data, an agent that references a skill which does not exist is a **compile error** — a hollow agent cannot be shipped.

**2. One requirement runs the whole SDLC, not one prompt.**
Give LordCode a requirement and it does not answer it with a single model call. It runs the pipeline:

```
requirement
  → business analysis      → functional requirements + acceptance criteria
  → solution architecture  → HLD + ADRs, gated by a binary consensus review
  → design                 → interface + UX specification
  → implementation         → domain specialists write the code
  → hallucination gate     → NLI + FactScore verification of every claim
  → QA pipeline            → strategy, unit, integration, contract, resilience
  → security audit         → threat model → SAST → secrets → dependencies → verdict
  → reliability gate       → RS = (NLI × FactScore × DRE × Coverage)^(1/4) = 1.0
  → ops readiness          → SLOs, DR, go/no-go
```

Typically **40–80+ specialist invocations per requirement**. That is the product, not a setting to tune down.

**3. Any model, any account.**
**OpenAI, Anthropic, and Google Gemini are all first-class.** Connect whichever accounts you have — one, or all three. A user with only a Gemini account gets a fully working tool. No provider is required and none is privileged. A real router picks the right model per task on capability, cost, and latency; per-provider circuit breakers handle outages and rate limits.

### What LordCode is not

- Not a foundation model — it does not train or fine-tune anything (see [Roadmap](#roadmap)).
- Not a reseller — it never brokers or resells inference. You use your own accounts and pay your own provider bill.
- Not a wrapper around one vendor's SDK.

---

## Status

| Area | State |
|---|---|
| Architecture & orchestration plan | ✅ Complete — [`docs/orchestration_prompt.md`](docs/orchestration_prompt.md) |
| Implementation language | ✅ Decided — Go |
| Requirements (PRD) | ⬜ Not started — Phase 0 |
| High-level design (HLD) | ⬜ Not started — Phase 1 |
| Code | ⬜ None yet |
| Installable release | ⬜ None yet |

**Open architectural decisions**, deliberately left for Phase 1 rather than guessed:

- **Router topology** — cascade, contextual bandit, classifier, or embedding-similarity
- **Corpus storage form** — plain Go constants (~90 MB binary) vs per-item compression (~25–30 MB)
- **Credential storage** — OS keychain plus the headless-Linux fallback design
- **Distribution channel** — see [Installation](#installation)
- **SDLC engine** — hardcoded in Go, or interpreted from the embedded decision-tree artifacts

---

## Prerequisites

### To use LordCode (once released)

**At least one provider account with API access.** One is enough; more is better, because the router has more to choose from.

> ⚠️ **A consumer subscription is not API access.** This trips up almost everyone, so it is worth being blunt:
>
> | You have | Does it work? |
> |---|---|
> | ChatGPT Plus / Pro | ❌ No — OpenAI API is billed separately. You need an API key with credits from `platform.openai.com`. |
> | Claude Pro / Max | ❌ No — the Anthropic API is billed separately via `console.anthropic.com`. |
> | Google account | ✅ Usually the easiest start — a Google AI Studio API key, with a free tier available. |
>
> LordCode's error messages will tell you precisely what is missing and where to get it, rather than saying "authentication failed". *(Exact current terms for each provider are being verified in Phase 0.2 — treat the table above as the working position, not gospel.)*

Everything else — agents, skills, knowledge graphs — is compiled into the binary. **No network access is needed to resolve a persona or a skill.** Only the model calls themselves go out.

### What a run costs

Be clear-eyed about this before you install. LordCode runs a **full SDLC** per requirement — typically **40–80+ specialist invocations**, not one model call — and every token is billed to *your* provider account.

| | Estimated cost per requirement |
|---|---|
| Typical range | **$4.5 – $39** |
| p95 | **$31 – $46** |
| Worst case (full self-correction re-route) | **$87 – $130** |

The spread is wide because it depends on how much of the pipeline a requirement actually triggers and which model tier the router selects for each invocation. Tier-C invocations are only ~15% of the count but drive most of the bill. The cascade router exists precisely to keep this down — it is roughly **100× cheaper than sending every invocation to the frontier tier** — but the honest headline is that a thorough run is not cheap, and LordCode does not pretend otherwise.

*These figures are derived, not measured — from published provider pricing and a modelled tier mix, with the range carrying that uncertainty. They will be replaced with measured numbers once the eval harness lands. The full derivation is in [`docs/phase-1-architecture/cost_model.md`](docs/phase-1-architecture/cost_model.md).*

### To build LordCode (contributors)

- Go toolchain (version pinned once Phase 1 fixes it)
- A local checkout of the agent/skill corpus, used as a **build input** by the code generator
- Standard Go tooling: `go build ./...`, `go vet ./...`, `go test -race ./...`, `govulncheck`

---

## Installation

**Not yet available.** No release exists.

The distribution channel is an open decision (ADR-5). Go was chosen partly because it *widens* rather than narrows the options — static single binaries cross-compile for Windows, macOS, and Linux on amd64 and arm64 from one CI runner. Candidates under consideration:

- Signed binaries on GitHub Releases
- Homebrew (macOS/Linux) and Scoop or winget (Windows)
- `go install`
- An npm wrapper that fetches the platform binary — reaching npm users without an npm dependency tree
- Docker

Shipping signed binaries brings macOS notarization and Windows Authenticode signing with it; both are accounted for in the plan.

---

## Usage

**Indicative only — the command surface is designed in Phase 1.5 and is not final.** Nothing below runs today. It is here so the intended shape is reviewable early, and it will be replaced by the real contract once that phase completes.

```bash
# Connect the accounts you have — one, some, or all
lordcode auth login openai
lordcode auth login anthropic
lordcode auth login gemini
lordcode auth list

# Hand it a requirement; it runs the full pipeline
lordcode build "add rate limiting to the payments API, 100 req/min per tenant"

# Machine-readable output for CI and scripting
lordcode build --json "..."

# Which corpus this binary carries
lordcode --version
```

Planned behaviours worth knowing about:

- **`NO_COLOR` is respected**, and no state is ever conveyed by colour alone — every status distinguished by colour is also distinguished by a symbol or word.
- **You see the estimated cost before a run starts, and the actual cost after it finishes** — the latter broken down per phase. The pre-run figure is a **range, not a point estimate**, and it does **not** block: the run proceeds without a confirmation keystroke. There is deliberately no spend ceiling and no approval prompt — a thorough run costing real tokens is the tool working as intended. Runaway loops are prevented structurally instead, by hard turn and budget bounds inside the agent loop.
- **A team daemon** with an HTTP/OpenAPI surface is in scope from v1, with per-user credential and context isolation.

---

## Architecture

Full design, including every architectural decision record and the complete agent roster: **[`docs/orchestration_prompt.md`](docs/orchestration_prompt.md)**.

Four components:

| Component | Responsibility |
|---|---|
| **Corpus (compiled)** | All 528 agents and 1034 skills as generated Go source. Missing skill ⇒ build error. |
| **SDLC pipeline engine** | Phase state machine, gate evaluators, bounded self-correction loop, decision-tree traversal. Decides **which agents** run. |
| **Multi-provider router** | Per-invocation model selection across OpenAI, Anthropic, and Gemini. Decides **which model** each agent runs on. |
| **Harness / control loop** | Executes one agent invocation reliably — stop conditions, budget guards, retry and backoff, per-provider circuit breakers, deterministic replay. |

**Agent selection and model selection are strictly orthogonal.** The pipeline engine may dispatch a threat-modelling specialist; the router independently routes that invocation to Gemini because no Anthropic key is configured. Merging the two would make *which specialist reviews your code* depend on *which API keys you happen to hold* — exactly backwards.

Measured corpus footprint: `agents/` 8.5 MB + `skills/` 47.7 MB + `knowledge-graph/` 28.1 MB = **84.3 MB raw, 24.7 MB compressed**.

One honest limit, stated so nobody designs against it: the persona and skill text alone is roughly **14 million tokens**. No context window holds all of it at once. Completeness comes from the pipeline's breadth across phases — every agent the requirement actually touches, each with its own bounded context — never from one enormous prompt.

### Compliance

Built against India's DPDP Act 2023 (§4/§8) for data handling and consent, CERT-In Directions 2022 for credential handling and incident reporting, and RPwD Act 2016 §40 for terminal accessibility.

---

## Roadmap

**LordCode's own models are planned for a future release.**

To be unambiguous about what that means today: v1 routes exclusively to third-party providers using your own accounts. There is **no training and no fine-tuning in the current scope**. First-party models are a stated direction, not a shipped or in-progress feature. The only obligation it places on the design right now is that the provider-adapter interface must not be shaped so that *only* a third-party HTTP API can satisfy it — so that a first-party model later becomes one more adapter rather than a rewrite.

Also on the list, ordered after the core lands: additional provider adapters, further router topologies, and expanded team-daemon capability.

---

## Contributing

**Contributions are welcome.** LordCode is built to be worked on in the open.

Because LordCode handles multiple users' provider credentials, the contribution path is deliberately hardened. This is not distrust of contributors — it is that a credential-handling binary is a supply-chain target, and the review path has to reflect that:

- Signed commits
- Mandatory maintainer review before merge
- Static analysis and secrets detection running on every external pull request
- Explicit review for any new dependency

`CONTRIBUTING.md` and a code of conduct will land alongside the first code. If you want to help before then, the highest-value contribution is **review of the architecture** in [`docs/orchestration_prompt.md`](docs/orchestration_prompt.md) — particularly the five open decisions listed under [Status](#status). Arguing one of those calls with evidence is worth more right now than any patch.

---

## License

**Not yet chosen.** The licence is an open decision being made in Phase 0, alongside the governance model. It will be settled before the first code is merged — an open contribution model without a licence in place would be unfair to anyone who contributed under it.

---

## Acknowledgements

LordCode's capability corpus is `claude-global-library` (v29.96.2, built 2026-08-29) — 528 agents, 1034 skills, and 104 domain knowledge graphs, consumed as a build input and compiled in. The library is not modified by this project.
