# Research Findings — Round 2 (Access-Path Engineering Pass)

**Prepared by:** deep-web-researcher
**Date:** 2026-09-04
**Method directive executed:** access-path engineering first, search as fallback (per this dispatch's own instructions). Prior round's two access failures (HTTP 413 on AgentsRoom, HTTP 403 on TechTimes/G2) are the direct antecedent — this round retries those same underlying questions via alternate routes (GitHub org/API, search-engine index of the blocked page, sibling pages) instead of re-hitting the blocked URLs.
**Role boundary:** This document RETRIEVES and SCREENS sources only. It does not grade or synthesize — that is `research-synthesis-analyst`'s job downstream.
**Inputs read in full before starting:** `research_findings.md`, `research_synthesis.md`, `tech_scout_report.md`, `research_protocol.md` (all in this directory).

---

## Lead A — "AgentsRoom" (~270/230+ "expert agents")

**Question:** Does AgentsRoom ship a vendor-bundled, pre-built specialist-agent corpus, or is it a marketplace/community-installed collection?

**Routes tried, in order:**

| Route | Outcome |
|---|---|
| `https://web.archive.org/web/2026/https://agentsroom.dev/` | **Blocked at the tool level** — "Claude Code is unable to fetch from web.archive.org." Not a content failure; the fetch tool itself refuses this host. |
| `https://agentsroom.dev/` and `https://agentsroom.dev/agents` (direct, retried) | **HTTP 413 Payload Too Large** on both, same as prior round — confirmed still blocked, not a transient failure. |
| `https://agentsroom.dev/robots.txt` | Fetched successfully. Reveals a `Sitemap:` directive and that `/demo/` (an iframed compiled desktop-app bundle) is deliberately excluded from crawling — explains why the root/`/agents` pages are unusually large (413) if similar heavy client bundles load there. |
| `https://agentsroom.dev/sitemap.xml` | Fetched successfully. 60 URLs, all locale variants of `/`, `/alternatives`, and `/alternatives/conductor` — **does not list `/agents`, `/pricing`, `/faq`, `/docs`, or `/catalogue`**, meaning the sitemap itself doesn't expose a lighter path to the blocked page. |
| `https://agentsroom.dev/pricing` | Fetched successfully (PRIMARY). Describes "All 14 agent roles" on every plan, "The whole expert catalogue" on the Pro tier, and a Plus tier that is "earned, never sold" through community agent-sharing (25 installs). No mention of "270" or "The Agency" on this page. |
| `https://agentsroom.dev/alternatives` | Fetched successfully (PRIMARY). Positions the product as multi-agent **orchestration** across externally-supplied CLIs ("Claude, Codex, GitHub Copilot CLI, Cursor and 10 other agent CLIs"), "Bring your own" provider credentials — an orchestration/IDE layer over other vendors' tools, not itself a model or agent vendor. |
| `https://agentsroom.dev/faq`, `/docs`, `/catalogue`, `/experts` | All **HTTP 404** — guessed sub-paths do not exist. |
| WebSearch (2/3 used this round): `AgentsRoom "270 expert agents" "The Agency" review` | Surfaced the search engine's own indexed title/snippet of the still-blocked page: **"A full AI team: 14 built-in roles + 230+ experts from The Agency \| AgentsRoom"** (`agentsroom.dev/agents`), and separately, the snippet states **"The Agency is open-source and licensed under MIT."** SEARCH-SYNTHESIS tier for this specific quote — the page itself remains unfetched — but it names the object to chase next. |
| `https://github.com/AgentsRoomDev` (org listing) | Fetched successfully (PRIMARY — the vendor's own GitHub org). **Decisive.** Three repos total: `electron-mcp-for-agentsroom` (own tooling), `HelloWorld` (demo), and **`agency-agents` — explicitly noted as forked from `msitarzewski/agency-agents`.** |

**Decisive evidence:** `msitarzewski/agency-agents` is not a new discovery — it is the exact same candidate this dispatch's prior round already fetched and classified: *"Confirms '230+ Specialized Agents' but explicitly community-contributed and separately installed by users via scripts into each target tool's own agent directory... not bundled/embedded inside a single vendor's product"* (`research_findings.md`, Q3 table, row 1). AgentsRoomDev's own GitHub org shows they **forked** that same community/MIT-licensed repo rather than authoring an independent corpus.

**Classification: Marketplace/community-import pattern — does NOT meet the bar for a vendor-bundled, pre-built corpus.** AgentsRoom's own native, first-party contribution is 14 built-in roles (an order of magnitude below "hundreds"); the "270 / 230+" figure is an imported open-source, MIT-licensed, community-authored project already independently confirmed as a marketplace pattern, not proprietary vendor content. This does **not** refute LordCode's differentiation claim — it reconfirms the same pattern research round 1 already established for other candidates, now traced to its root for this specific candidate.

**CRAAP:** `agentsroom.dev/pricing`, `/alternatives`, and `github.com/AgentsRoomDev` are all PRIMARY, vendor-owned, fetched live on 2026-09-04 — Currency/Authority/Accuracy all high, no staleness. The one SEARCH-SYNTHESIS-tier quote ("The Agency is open-source and licensed under MIT") is used only as corroboration alongside the PRIMARY fork evidence, consistent with the protocol's rule that search-synthesis alone cannot support a definitive finding — here it doesn't have to, since the GitHub fork is independently PRIMARY and sufficient on its own.

---

## Lead B — claude-skills library (345 packages / 51 personas, per TechTimes)

**Question:** Same bar as Lead A.

**Routes tried, in order:**

| Route | Outcome |
|---|---|
| `https://techtimes.com/articles/claude-skills-library-345-packages` (guessed slug) | **HTTP 403 Forbidden** — same failure class as prior round's TechTimes attempts. |
| `https://registry.npmjs.org/-/v1/search?text=claude-skills&size=20` | Fetched successfully (PRIMARY — npm registry API, not a search-engine summary). Returned 20 real packages, none matching "345/51" exactly — useful negative signal, ruled out several false leads (`pm-claude-skills` = 244–249 skills, not 345/51; `claude-skills-library` = 1128 skills/17 categories, different project). |
| `https://github.com/search?q=%2251+personas%22+claude&type=repositories` and `%22345+packages%22...` | Both returned 0 results — GitHub's own repository-name/description search does not index this phrase. |
| WebSearch (1/3 used this round): `"345 packages" OR "51 personas" claude skills library portable Codex Cursor "Gemini CLI"` | **Resolved immediately.** Surfaced the exact TechTimes article (`techtimes.com/articles/318518/20260616/...-51-senior-engineer-personas.htm`) and the exact repository: **`github.com/alirezarezvani/claude-skills`**. |
| `https://raw.githubusercontent.com/alirezarezvani/claude-skills/main/README.md` | Fetched successfully (PRIMARY). |
| `https://api.github.com/repos/alirezarezvani/claude-skills` | Fetched successfully (PRIMARY — GitHub REST API, not the HTML page). |

**Decisive evidence (from the README, PRIMARY, fetched 2026-09-04):**
- Install methods are explicitly user-driven: `"/plugin marketplace add alirezarezvani/claude-skills"` (Claude Code), `"npx agent-skills-cli add alirezarezvani/claude-skills --agent codex"` (Codex), manual git-clone-and-copy, or a local `./scripts/convert.sh --tool all` conversion step for 9 target platforms.
- MIT licensed; "welcomes community contributions per CONTRIBUTING.md."
- Authored primarily by one maintainer (Alireza Rezvani); the library has grown past the TechTimes-reported 345/51 snapshot to 388 skills / 118 agents / 7 personas / 150 commands as of retrieval (counts drift upward release-to-release — the "51 personas" figure itself may already be stale relative to the repo's current state, independent of the 6-month domain decay window).
- GitHub API confirms: MIT license, 25,510 stars, 3,604 forks, 231 subscribers, created 2025-10-19, last pushed 2026-08-30 (actively maintained, not abandoned).

**Classification: Definitively a community-installed, open-source, MIT-licensed, single-maintainer GitHub library that users manually install into their own pre-existing AI coding tools.** Not bundled/compiled inside a vendor product. This is the same marketplace pattern as every other candidate resolved across both research rounds. Does **not** refute LordCode's claim.

**CRAAP:** Both sources PRIMARY (repo owner's own README + GitHub's own API, not a third-party mirror), fetched live 2026-09-04 (repo pushed 5 days prior) — Currency/Authority/Accuracy all high for the self-description claims being screened (installation mechanism, license, authorship). No staleness concern.

---

## Q3 combined verdict (both leads now resolved)

Both of the two previously-unreached "hundreds-scale" leads are now independently confirmed, via PRIMARY-tier evidence for each, to be **community-contributed/open-source marketplace patterns**, not vendor-bundled corpora. Combined with the two candidates the prior round already resolved (`agency-agents` directly, `mcpservers.org/agent-skills`), **all four candidates surfaced across both rounds now resolve to the same category.** This raises the Q3 finding's evidentiary weight — the prior round's VERY LOW grade was explicitly capped because two of four candidates were an unresolved Reporting gap, not because the resolved half looked weak. That gap is now closed. `research-synthesis-analyst` should re-grade Q3 with this closure in view; per the binding protocol constraint a non-refuting Q3 finding is still capped at LOW/VERY LOW regardless, but the *reason* for the cap changes from "half the candidates are inaccessible" to "the search itself is inherently budget-limited, not exhaustive" — a materially different and stronger footing for the same numeric grade.

**Still not claimable:** "novel," "first," "unmatched" — this remains a search-budget-limited landscape check (5 total candidates across two rounds), not an exhaustive competitive sweep.

---

## Q1 — OpenAI "Sign in with ChatGPT" OAuth: Third-Party Availability

**Prior state:** Round 1 found only that `learn.chatgpt.com/docs/auth` scopes the flow to OpenAI's own products by omission, with no explicit inclusion/exclusion statement, and one dead link (`platform.openai.com/docs/guides/authentication` → 404).

**New routes tried this round, in order:**

| Route | Outcome |
|---|---|
| `https://developers.openai.com/api/docs` (platform docs index, replacing the dead-linked page) | Fetched successfully (PRIMARY). Full nav lists Authentication topics: GPT Action auth, Workload Identity Federation, RBAC, Admin APIs, mTLS, IP allowlist. **No page on "Sign in with ChatGPT" or third-party app OAuth appears in this index at all** — closes the Round 1 dead-link Reporting gap: the content isn't hiding behind a different index entry, it simply isn't organized under this docs tree. |
| `https://developers.openai.com/apps-sdk`, `/apps-sdk/auth`, `/codex/`, `/codex/partners` | All **HTTP 404** or 308-redirected to `learn.chatgpt.com/docs` (already read in Round 1). |
| `https://developers.openai.com/plugins`, `/plugins/build`, **`/plugins/build/auth.md`** | Fetched successfully (PRIMARY — this is a genuinely new document this round, not re-fetching a Round-1 URL). This is OpenAI's actual third-party-developer OAuth documentation — but for the **reverse direction**: it documents how a third party runs *their own* authorization server that ChatGPT (as OAuth client) connects into, via CIMD/DCR/predefined-client registration. Explicit quote: **"ChatGPT does not support machine-to-machine OAuth grants such as client credentials, service accounts, or JWT bearer assertions."** This rules out one plausible mechanism (third parties self-registering as an OpenAI OAuth client the way they'd register with Google/GitHub) without directly answering whether "Sign in with ChatGPT" specifically is open to third parties. |
| `https://api.github.com/repos/openai/codex/contents` → `.../codex-rs` → `.../login/src` → `.../login/src/auth` (progressive directory drill-down) | All fetched successfully (PRIMARY — the GitHub REST contents API, not the HTML file browser, avoiding the size/rendering issues that hit `agentsroom.dev`). Located the actual shipped Rust source implementing Codex's OAuth login. |
| `https://raw.githubusercontent.com/openai/codex/main/codex-rs/login/src/server.rs` | Fetched successfully (PRIMARY — **this is the actual shipped implementation code**, the strongest possible primary source short of an explicit vendor policy statement). Decisive findings, quoted directly from source: `DEFAULT_ISSUER: &str = "https://auth.openai.com"`; redirect URI built as `http://localhost:{actual_port}/auth/callback`; scopes `"openid profile email offline_access api.connectors.read api.connectors.invoke"`; and critically, a code comment: **"Keep in sync with the Codex CLI Hydra redirect URI allow-list."** Hydra is an OAuth2/OIDC server product — this comment reveals OpenAI maintains a server-side allow-list of permitted redirect URIs for this flow, i.e., gated/registered access, not an open self-service grant. |
| `https://raw.githubusercontent.com/openai/codex/main/codex-rs/login/src/auth/default_client.rs` | Fetched successfully (PRIMARY). Found `DEFAULT_ORIGINATOR: &str = "codex_cli_rs"` and an internal header `x-openai-internal-codex-residency` — the client identifies itself specifically as Codex CLI on every request to OpenAI's backend, reinforcing that this is a purpose-built, tracked client rather than a generic reusable one. |
| `https://help.openai.com/en/articles/20001410-sign-in-with-chatgpt` (found via WebSearch below — an OpenAI-owned Help Center article titled exactly "Sign in with ChatGPT") | **HTTP 403 Forbidden — UNREACHED, not resolved.** This is the single most on-point candidate PRIMARY source found in either round and remains the top target for any further follow-up. |
| `https://api.github.com/repos/openai/codex/issues/10974` and the HTML issue page (title via search: *"'Sign in with ChatGPT' for third-party apps so users can bring their own plan"*) | **HTTP 404 on both routes — UNREACHED.** Issue may be renumbered, transferred, or access-restricted; not confirmed either way. |
| WebSearch (3/3 used this round): `OpenAI "Sign in with ChatGPT" third-party developers register client_id 2026` | Surfaced the two unreached URLs above plus `community.openai.com/t/oauth-client-id-is-no-longer-optional/1367103`, fetched successfully (SECONDARY — community forum, not vendor-authored, but directly quotes OpenAI's own docs inline). Confirms the OAuth client-registration machinery in active flux as of 2025-11-21–24, but this thread concerns the Apps SDK/MCP connector direction (same reverse-direction mechanism as `/plugins/build/auth.md`), not "Sign in with ChatGPT" specifically. |

**Verdict — upgraded from Round 1, but still not a fully explicit statement.** No OpenAI-owned source was found that explicitly states "third-party CLIs may/may not use Sign in with ChatGPT." However, this round moved the evidence from *pure silence* to *strong circumstantial PRIMARY code-level evidence*: the actual shipped OAuth client implementation is bound to a specific issuer (`auth.openai.com`), a localhost redirect URI that must be present on a server-side **allow-list** ("Hydra redirect URI allow-list"), and a hardcoded originator string identifying the client as Codex specifically. This is the pattern of a gated, registered, single-purpose OAuth client — not a documented, self-service, general-purpose grant a third party could adopt by registering their own redirect URI. This is meaningfully stronger evidence than Round 1 had, but it is inference from implementation structure, not an explicit vendor statement, and must be reported as such — not upgraded to "confirmed first-party-only."

**Remaining unreached leads, both worth a dedicated retry:** `help.openai.com/en/articles/20001410-sign-in-with-chatgpt` (403) and `github.com/openai/codex/issues/10974` (404 both routes).

---

## Third priority — tech scout report's other open follow-ups attempted

Two of the five follow-ups (`tech_scout_report.md` §6) had known target URLs and remaining fetch budget was available:

**Follow-up #3 — Gemini/Google One billing separation.** `https://ai.google.dev/gemini-api/docs/billing` fetched successfully (PRIMARY, 2026-09-04). Confirms: "New accounts begin on the Free Tier... A billing account is not required" and that linking a paid billing account is a separate, explicit opt-in step ("Prepay to move to the Paid Tiers"). This is now a PRIMARY-sourced confirmation replacing the Round-1/tech-scout SEARCH-SYNTHESIS tier for this specific claim. **Follow-up #3 is now CLOSED at PRIMARY confidence.**

**Follow-up #1 — Anthropic's own commercial/usage-policy page (the "third parties may not offer Claude.ai login" language).** Two candidate URLs fetched directly: `https://www.anthropic.com/legal/aup` (Usage Policy, effective 2025-09-15, PRIMARY) and `https://www.anthropic.com/legal/commercial-terms` (Commercial Terms, effective 2025-06-17, PRIMARY). **Neither page contains the specific "third-party developers are no longer allowed to offer Claude.ai login" language** that the Round-1 SECONDARY source (alternativeto.net) attributed to an unnamed Anthropic "Legal and compliance" page. This is a **Reporting gap, not a refutation**: the two most obvious candidate URLs were checked and don't contain it, but Anthropic maintains other legal/policy pages (e.g., a Claude Code-specific policy or a separate "Supplemental Terms") not yet located. **Follow-up #1 remains open** — report the SECONDARY source's claim as still uncorroborated by direct fetch of the exact page it cites, not as refuted.

Follow-up #2 was this dispatch's Q1 (see above, partially resolved). Follow-up #4 was already resolved in the prior round. Follow-up #5 was this dispatch's Q3/Leads A+B (now resolved, see above).

---

## Budget Reconciliation

- **WebSearch calls used: 3 / 3** (1 for Lead B repo identification; 1 for AgentsRoom "270/The Agency" corroboration; 1 for Q1 third-party OAuth registration). Each followed by synthesis before the next call, per the Cooldown Protocol.
- **WebFetch calls made: approximately 40** (all free/uncounted) — spanning direct vendor pages, GitHub REST API directory drill-downs, raw GitHub source files, npm registry API, and community forum pages.
- **Now resolved this round:**
  - **Lead A (AgentsRoom):** Resolved — marketplace/community-import pattern (forked `agency-agents`), does not meet the vendor-bundled-corpus bar.
  - **Lead B (claude-skills / alirezarezvani):** Resolved — community-installed, MIT-licensed, single-maintainer open-source library, does not meet the bar.
  - **Q3 overall:** Both previously-open Reporting-gap leads closed; combined finding across both rounds is now 4/4 resolved candidates, all in the marketplace pattern, still capped at LOW/VERY LOW per protocol (search-budget-limited, not exhaustive) but on stronger footing than Round 1.
  - **Tech-scout Follow-up #3 (Gemini billing):** Closed at PRIMARY confidence.
- **Still unreached (access failure, not negative findings):**
  - `https://help.openai.com/en/articles/20001410-sign-in-with-chatgpt` — HTTP 403. Single highest-value remaining target for Q1.
  - `https://github.com/openai/codex/issues/10974` — HTTP 404 on both the HTML page and the REST API.
  - `https://web.archive.org/*` — blocked at the tool level for this session, not a content-level failure; any future pass should not assume Wayback Machine is unusable in general, only that it was unusable in this session.
  - Tech-scout Follow-up #1 (Anthropic's specific "no third-party Claude.ai login" policy page) — the two most likely candidate URLs were checked directly and do not contain the claimed language; the actual source page remains unidentified.
- **Q1 status:** Meaningfully strengthened via PRIMARY source code (Codex CLI's own OAuth client implementation shows a gated, allow-listed, Codex-specific mechanism) but still short of an explicit vendor statement. Report as "no explicit inclusion/exclusion statement found; strong circumstantial PRIMARY evidence of a gated, Codex-specific implementation," not as a confirmed first-party-only policy.
