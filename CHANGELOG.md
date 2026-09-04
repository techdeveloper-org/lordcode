# Changelog

All notable changes to LordCode are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> **No release has been made yet.** LordCode is pre-implementation: the architecture and
> orchestration plan are complete, but no source code exists. Everything below sits under
> `[UNRELEASED]` until the first shipped artifact. `VERSION` reads `0.1.0` as the target
> under development, not as a version that has been released.

## [UNRELEASED]

### Added

- **Orchestration plan** (`docs/orchestration_prompt.md`) — full phase-gated SDLC plan covering
  Phase 0–8 pre-processing and Phase A → Ops.5 execution, with per-agent dispatch prompts,
  interface contracts, and gate criteria.
- **README** (`README.md`) — project overview, prerequisites, architecture summary, roadmap,
  and contribution policy.
- **Documentation governance files** — this changelog and `VERSION`.

### Decided

Architectural decisions settled before implementation, recorded in full in
`docs/orchestration_prompt.md`:

- **ADR-2 — Implementation language: Go.** Chosen over Rust, Node.js/TypeScript, and Python on
  eight weighted criteria (Go 885/1000, Rust 753, Node+TS 718, Python 718). Decisive factors:
  first-class code generation via `go generate`, stdlib strength for a long-lived daemon, and the
  strongest supply-chain posture of the four — notably that Go modules execute no install-time
  scripts, which matters for a binary holding third-party provider credentials.
- **ADR-3 — Library consumption: full corpus, compiled into Go code.** All 528 agents, 1034
  skills, and 104 domain knowledge graphs are code-generated into Go source rather than embedded
  as runtime-parsed data. This makes a missing mandatory skill a *build error* instead of a silent
  runtime failure. Measured corpus: 84.3 MB raw, 24.7 MB compressed.
- **ADR-6 — Team daemon in scope from v1**, network-exposed and multi-user, which raises the
  security posture to CRITICAL and brings a literal OpenAPI surface into Phase 1.5.
- **Providers:** OpenAI, Anthropic, and Google Gemini are all first-class. Any combination of
  user accounts works; none is required and none is privileged.
- **Per requirement, the full SDLC runs** — typically 40–80+ specialist invocations rather than a
  single model loop.
- **Monetization:** bring-your-own account, free tool, telemetry opt-in and off by default. No
  brokered inference, no payment surface.
- **Token cost is accepted, not gated** — no spend ceilings and no pre-run approval prompts.
  Post-run per-phase cost reporting only; runaway protection comes from the agent loop's mandatory
  turn and budget bounds.
- **Contributions are welcome**, through a hardened review path (signed commits, mandatory
  maintainer review, static analysis and secrets detection on every external pull request).

### Known open items

Deliberately unresolved, to be decided in Phase 1 rather than assumed:

- ADR-1 — router topology (cascade / contextual bandit / classifier / embedding-similarity)
- ADR-3 — corpus storage form (plain Go constants vs per-item compression)
- ADR-4 — credential storage mechanism and the headless-Linux fallback
- ADR-5 — distribution and packaging channel
- ADR-7 — SDLC engine: hardcoded in Go, or interpreted from the embedded decision-tree artifacts
- **Licence** — not yet chosen; must be settled before the first external contribution is merged.

### Verification notes

- Whether a consumer subscription (ChatGPT Plus, Claude Pro/Max) grants provider API access is
  documented as a working position, not a verified fact. Phase 0.2 confirms the current terms per
  provider before any user-facing claim depends on it.
- Feature parity of the official Go SDKs for OpenAI, Anthropic, and Gemini is unverified and is
  checked in Phase 0.2. The outcome sizes an ongoing maintenance cost; it does not change ADR-2.
