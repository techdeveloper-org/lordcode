# GLOBAL STATE DOCUMENT v1.0

**Project:** LordCode
**Created by:** `solution-architect` | 2026-09-04
**Status:** Initial — squad leads version this during execution
**Authoritative source:** `docs/phase-1-architecture/HLD.md` v1.0.0-draft. Where this GSD and the HLD disagree, the HLD wins and this document is corrected.

> **What this document is.** Not a summary of the architecture. It is the operational contract squad leads execute against: every field below must be specific enough that a squad lead can hand it to an implementing agent as an instruction without further interpretation. Anything not yet negotiated is marked `[TBD — requires squad lead negotiation]` rather than left blank.

---

## System Overview

LordCode is a single Go binary with two entry points — a cross-platform CLI and a network-exposed multi-tenant team daemon (`lordcode serve`) — that compiles the complete `claude-global-library` corpus (528 agents, 1034 skills, 104 domain knowledge graphs, 9,146 typed edges) into itself at build time and executes that library's full phase-gated SDLC pipeline for every user requirement. Model execution is routed per invocation across the user's own OpenAI, Anthropic and Google Gemini accounts (BYO key; LordCode brokers no inference and holds no billing surface). The architecture is **two cleanly layered engines**: the **harness** executes one agent invocation reliably (stop predicate, retries, budget, tool mediation), and the **SDLC engine** sequences phases and evaluates gates as a *client* of the harness. Model selection (router) and agent selection (SDLC engine) are strictly orthogonal and never consume each other's decision. Persistence is SQLite (pure-Go, CLI) and PostgreSQL (daemon); credentials live in a LordCode-owned envelope-encrypted vault whose KEK is held by one deterministically-selected provider. Security risk is **CRITICAL** because the daemon is network-exposed and holds multiple users' provider credentials.

---

## Squad Map for This Project

LordCode is a single-product build, so the classic four-squad split maps as follows. Squad names below are the ones used in every table in this document.

| Squad | Owns | Lead implementing agents |
|---|---|---|
| **Core Squad** | `sdlc-engine`, `router`, `harness`, `persona-dispatcher`, `corpus`, `buildgen`, `provider-adapters` | `go-systems-engineer` |
| **Surface Squad** | `cli`, `termui`, `daemon` HTTP surface, `evalapi` | `go-systems-engineer` + `ui-ux-designer` (documented seam — see Capability Gaps) |
| **Data Squad** | `state-store`, `costmeter`, `consent`, `telemetry` | `database-engineer` |
| **Infra Squad** | CI, build matrix, signing, notarization, release, staging | `devops-engineer`, `release-engineering-specialist` |
| **Security Squad** | Threat model, F.0–F.6 audit, ADR-4 veto | `security-lead-auditor` and the Phase F roster |
| **Eval Squad** | Python eval harness (B.10), task bank | `ai-model-testing-engineer` |

---

## Cross-Squad Interface Contracts

### Core Squad → Core Squad — SEAM 1: Router → Harness (Alignment 1)

**The record every routing decision emits.** Full schema: HLD §7.3. Binding fields and their owners:

| Field | Owner | Rule |
|---|---|---|
| `invocation_id` | `sdlc-engine` | **Stable across a provider substitution.** One invocation, one identity, one budget envelope. |
| `routing_decision_seq` | `router` | Monotone from 0 within an invocation. A breaker fallback emits `seq+1`, never mutates `seq`. |
| `fallback_from` | `router` | Set on any record with `seq > 0`. |
| `cost_estimate_usd` | `router` | Pre-flight, from the CPST table. **Never** used to answer FR-HRN-002. |
| `cost_actual_usd` | `harness` | Recorded on completion, per `seq`. This is what answers "what did invocation #7 cost". |
| `pricing_table_version` | `router` | Required. Without it a recorded cost decision is not reproducible. |
| `substitution` | `router` | Populated whenever FR-RTG-005's degrade-to-best-available path fires. |

**Non-negotiable:** the record is immutable once emitted. The router never re-invokes itself mid-loop against the same `(invocation_id, seq)`.

### Core Squad → Core Squad — SEAM 2: SDLC Engine → Harness (Alignment 6)

**Interface:** `InvocationExecutor.Execute(ctx, InvocationRequest) (InvocationResult, error)`. Full Go signature: HLD §7.4.

| Contract point | Rule |
|---|---|
| Budget | The engine passes an **`InvocationClass`** (`R` \| `I` \| `S`), never `T_max` or `B`. The harness resolves both from `harness_control_policy.json`. The engine **cannot** raise or disable them. |
| Phase state | The harness receives `Phase` as an opaque audit label. It has no accessor for gate results, prior phases, or the SC counter. |
| Failure channel | A provider outage, tripped breaker or `T_max` abort is a **`Result`** (`FinishReason: aborted` + `AbortReason`), never an `error`. `error` is reserved for harness-internal faults. |
| Abort reporting | An `aborted` result is **never** reported as `stop`. `AbortReason ∈ {t_max, budget, stopWhen, cancelled}` is mandatory on abort. |
| Direction | `RoutingRecords` flow **upward** only. A breaker fallback never changes which agents the engine dispatches. |
| Import rule | `harness` **must not import** `sdlc-engine`. Enforced by the build-time import-graph check, not convention. |

### Core Squad → Data Squad

| Data | Schema location | Volume | Access pattern |
|---|---|---|---|
| `pipeline_runs`, `phase_records` | Phase 1.5 `openapi.yaml` schemas + `state-store` migrations | 1 run + N phase rows per requirement | Write on every phase checkpoint (one transaction); read on resume |
| `invocations`, `routing_records` | same | 40–80+ invocations per requirement; ≥1 routing record each | Append-only write; read for replay and audit |
| `tool_calls` | same | Bounded by `T_max` per invocation | Append-only; read for deterministic replay (FR-HRN-001) |
| `cost_ledger` | same | 1 row per invocation | Append-only; per-phase rollup on run completion |
| `audit_events` | same | See HLD §11.7 for derived volume | Append-only; **keyset pagination only** — offset pagination degrades to O(offset) on an unbounded table |
| `consent_records` | same | 1 per (user, provider) + amendments | Read before first transmission (blocking gate) |

**Binding rule:** no component outside `state-store` opens the database. Every access is through a typed repository port. This is the "shared database" anti-pattern's cure applied inside one binary, where nothing physically prevents the violation.

### Core Squad → Surface Squad

| Surface | Contract | Notes |
|---|---|---|
| Post-run cost display | `costmeter` emits a per-phase rollup; `termui` renders it | FR-COR-006. **No pre-run approval prompt, no spend ceiling.** |
| Streaming progress | `harness` emits turn-level events; `termui` renders styled / plain / JSON | Plain mode must convey the same information without colour, cursor movement, or spinner glyphs (FR-UXA-001) |
| Error surfacing | `provider-adapters` error taxonomy → `termui` | FR-AUT-007: never a bare "authentication failed" for a subscription-vs-API-key failure |
| `--json` mode | stdout carries **only** machine-parseable JSON; progress goes to stderr | FR-CLI-003, AC-FR-CLI-003 |

### Surface Squad → Eval Squad

| Endpoint | Purpose | Availability |
|---|---|---|
| `POST /v1/eval/invocations` | Single invocation, bypassing the SDLC engine, forced provider | **Contract in Phase 1.5; implementation in B.10** |
| `GET /v1/eval/routing-records/{invocation_id}` | Retrieve the routing decision record | same |
| Forced-provider override | Recorded as `substitution.unavailable_reason = "eval_forced_override"` | Eval records must never be mistaken for production routing evidence |

**Security contract on this surface (non-negotiable, HLD §8.3):** routes are **not registered** unless `--enable-eval-api` is passed; the `eval` scope is admin-mintable only and never attached to a user token; separate rate limit and concurrency semaphore; every eval invocation written to the same per-user audit log tagged `origin: eval`.

### Infra Squad → All Squads

| Contract | Value |
|---|---|
| Build | `CGO_ENABLED=0`, `-trimpath`, pinned Go toolchain. Six targets: {linux, darwin, windows} × {amd64, arm64}. |
| Release artifact | GitHub Releases is the **sole source of truth**. Homebrew tap, Scoop bucket and npm wrapper all download and checksum-verify *that* artifact. |
| Signing | cosign signature + SLSA v1 provenance on every artifact; macOS notarized and stapled; Windows Authenticode-signed. A release without provenance does not publish. |
| Build-time gates (all fail the build) | 1 hollow-persona check · 2 no string-keyed skill resolution · 3 routability audit ratio = 1.0 · 4 blob-offset integrity · 5 gate-kind completeness · 6 import-graph check · 7 corpus regeneration byte-match against the SHA-pinned library · 8 secret-leak lint · 9 `library_version` stamp · 10 `govulncheck` |
| External PR gates | 2, 7, 8, 10 plus signed-commit verification, F.2 static analysis and secrets detection — all run on external PRs |
| Staging | Phase F.0 environment for F.3 dynamic/API testing against a live daemon |

### Infra Squad → Data Squad

| Contract | Value |
|---|---|
| CLI store | SQLite via `modernc.org/sqlite` (pure Go). `mattn/go-sqlite3` is **prohibited** — it requires CGO and breaks the cross-compile matrix. |
| Daemon store | PostgreSQL via `jackc/pgx`. SQLite is **prohibited** for the daemon: its single-writer lock makes the pipeline-state write path a serial section, and Amdahl's ceiling on it is what NFR-DAE-001 forbids. |
| Directory resolution | `os.UserConfigDir()` / `os.UserCacheDir()` for config, vault, state store and logs. **No hardcoded literals** (`~/.lordcode`, `%APPDATA%`) anywhere. |
| Migrations | Versioned, forward-only, applied at daemon start behind an advisory lock |

---

## Shared Data Schemas

Owned by **Data Squad**, read across squad boundaries:

| Entity | Owner | Cross-squad readers | Notes |
|---|---|---|---|
| `RoutingRecord` | Core (router writes, harness appends actuals) | Surface (cost display), Eval (paired data), Security (audit) | Immutable per `(invocation_id, seq)` |
| `InvocationResult` | Core (harness) | Data (persistence), Surface (rendering), Eval | Contains `ToolTrace` for replay |
| `GateVerdict` | Core (sdlc-engine) | Data, Surface, Security | Carries `Measured map[string]float64` — a bare bool is prohibited, because the SC loop and the audit trail both need the reason |
| `AuditEvent` | Data | Security (F.5/F.6), compliance reviewers | Mandatory classes: auth success/failure, credential access, cross-tenant access attempt, provider transmission with consent state, retention deletion |
| `ConsentRecord` | Data (`consent`) | Core (blocking gate), Surface (user-retrievable) | DPDP §4 |
| `Secret` | Data (`credstore`) | **`provider-adapters` only** | `String`/`GoString`/`MarshalJSON`/`MarshalText` all return `[REDACTED]`. `.Reveal()` is lint-restricted to `provider-adapters`. |

---

## Infrastructure Contracts (Infra Squad provides to all)

- **Secrets injection:** none at the OS level. Credentials live in the LordCode vault (HLD §4); the KEK provider is one of `os_keychain` \| `passphrase` \| `ephemeral` \| `external_kms`, recorded in the vault header and **never silently changed**.
- **CI-mode credentials:** `ephemeral` only — supplied per run from the CI secret store via `lordcode auth login <provider> --stdin --ephemeral`. **No vault file is written.** Putting the KEK in an environment variable is prohibited.
- **Observability:** structured JSON logs to stdout with a fixed field set (`timestamp`, `level`, `service`, `version`, `library_version`, `correlation_id`, `requirement_id`, `invocation_id`, `phase`, `agent`, `provider`, `model`, `duration_ms`). Metrics in Prometheus exposition format. `[TBD — requires squad lead negotiation]`: the concrete log shipper and metrics backend for a daemon deployment, which is an operator choice, not a LordCode-shipped component.
- **Clock:** NTP-synchronized; CERT-In audit correlation depends on it.

---

## Security Policies (mandatory for all squads)

1. **Authentication:** every daemon route is authenticated. There is no anonymous route and no localhost bypass. Unauthenticated requests are rejected **before** any pipeline or provider action.
2. **Secrets management:** credentials never enter an environment variable, a config file, a log, a metric, a telemetry payload, or an error body. Enforcement is the `Secret` type plus a CI lint, not review discipline.
3. **Per-user isolation is cryptographic, not procedural:** per-user DEK via `HKDF(KEK, "lordcode/dek/v1" ‖ user_id)`, and the AEAD's AAD binds `user_id ‖ provider` so a swapped row fails authentication rather than decrypting.
4. **Egress:** allowlist-only. Outbound calls are permitted to the three provider endpoints and declared integrations. Adding a host requires explicit approval. `InsecureSkipVerify` is banned by CI lint.
5. **Tool mediation:** always require approval for recursive delete, deletion outside PROJECT_PATH, protected-branch push, and force-push. Allow-with-audit for pipeline-created feature-branch push. Allow ungated for read-only operations.
6. **Rate limiting is two-layered:** an HTTP token bucket *and* a per-user concurrent-pipeline-run semaphore. The second is load-bearing, because one authenticated request amplifies into 40–80+ upstream provider calls; an HTTP-only limit does not bound the real load.
7. **Least privilege:** `CredentialReader` (1 operation) is the only credential surface the router and harness see; `CredentialAdmin` (3 operations) is wired only to the auth command layer and the daemon account endpoints. Target `|permissions_used| / |permissions_granted| > 0.8` is met at 1.0 for both.
8. **Supply chain:** no install-time-script dependencies; `govulncheck` (reachability-based) in CI on every dependency change; every dependency-adding PR gets a review distinct from ordinary code review.
9. **Security holds veto over ADR-4** at Phase F.1/F.4/F.6. This is not advisory input.

---

## Compliance Contracts (India layer)

| Obligation | Owning squad | Mechanism |
|---|---|---|
| DPDP §4 consent before third-party transmission | Data (`consent`) | Blocking gate; user-retrievable record |
| DPDP §4 purpose limitation | Data | Content used only for the requesting user's run; the telemetry payload type cannot express content |
| DPDP §4 context isolation (multi-tenant) | Core + Data + Surface | Per-user DEK/AAD, per-request context construction, cross-tenant similarity check |
| DPDP §8(7) auto-deletion | Data | Retention sweeper; every deletion audited |
| DPDP §11–13 data-principal rights | Surface + Data | Access / correct / erase endpoints with confirmation |
| CERT-In 6-hour incident readiness | Data + Security | Mandatory audit event classes; NTP-synchronized clock |
| CERT-In log retention vs DPDP §8(7) deletion | Security (**AI-2**) | **These pull in opposite directions.** Resolution pending compliance sign-off: CERT-In floor wins for security-event classes; the DPDP clock governs user-content artifacts. A naive sweeper would delete audit evidence. |
| RPwD §40 accessibility | Surface | `NO_COLOR`, colourblind-safe palette, screen-reader plain-text mode |
| GST / pricing | — | **Not applicable.** LordCode holds no billing surface (OAQ-5); provider costs and 18% GST RCM sit on the user's own account. |

---

## Capability Gaps Affecting Squad Composition

Recorded honestly, per PRD §15. These are gaps in the 528-agent roster **for building LordCode itself**, not gaps in the product.

| Gap | Resolution for this build |
|---|---|
| CLI/TUI construction (Bubble Tea, Windows console behaviour, streaming render) | **Surface Squad jointly owned** by `go-systems-engineer` (runtime, event plumbing) and `ui-ux-designer` (rendering model, accessibility). The seam is documented: `ui-ux-designer` owns the Phase 3 `terminal_ux_spec.md`; `go-systems-engineer` owns `termui`'s implementation against it. |
| Cross-platform packaging and code signing | `release-engineering-specialist` — confirmed sufficient at ADR-5. |
| Keychain / secure credential storage design | Jointly owned: `solution-architect` proposed ADR-4; `crypto-security-specialist` and `threat-modeling-specialist` review **with veto** at Phase F. |

---

## Blocking Dependencies Between Squads

| Blocked work | Blocked on | Squad boundary |
|---|---|---|
| B.5 persona dispatcher | B.4 code generator + B.1 SDLC engine | Core → Core |
| B.2 router **∥** B.3 harness | B.1 SDLC engine (foundational) — but B.2 and B.3 are parallel with each other **because** Seam 2 is a clean client/server layering | Core → Core |
| B.8 daemon | B.1, B.3, and the `state-store` port | Core → Surface, Data |
| B.10 eval harness | B.8 daemon + Phase 1.5 `openapi.yaml` eval operations | Surface → Eval |
| Effective-context table, SPRT δ/σ, τ* calibration | B.10 | Eval → Core (router) |
| ADR-3 final form | `go-systems-engineer`'s measured spike | Core → Architecture (**measurement wins over plan**) |
| ADR-4 final approval | Phase F.1/F.4/F.6 review | Security → Architecture (**veto**) |
| Release | Apple Developer account + code-signing certificate | Infra → external procurement |

---

## Change Log

| Version | Updated By | Change |
|---|---|---|
| v1.0 | `solution-architect` | Initial GSD — all sections drafted from HLD v1.0.0-draft. Alignment 6 resolved (two layered engines); ADR-3/4/5/7 resolved; Seams 1 and 2 contracted; RTM `HLD Component` column discharged. |

### GSD Maintenance Rules (for squad leads)

1. **Only update your squad's owned sections.** Never edit another squad's section without orchestrator authorization.
2. **Version every update** — v1.0 → v1.1 → v1.2.
3. **Log every change** in the table above, with version, squad lead, and what changed.
4. **Notify the orchestrator** after every update: "GSD v{n} updated — {affected squad leads} must re-align."
5. **Never delete prior versions.** Append; do not overwrite history.
