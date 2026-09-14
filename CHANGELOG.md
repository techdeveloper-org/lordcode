# Changelog

All notable changes to this project are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [UNRELEASED]

### Fixed

**The warm-load budget test no longer fails on a busy machine — closes #49.** It
took a single wall-clock sample and compared it to a fixed 300ms, and had gone
red three times under full-suite runs (~508ms) while passing every time in
isolation. The budget was never the problem: idle, a warm load is 73–85ms, so the
assertion had ~4x headroom and still failed. A single sample on a machine that is
not dedicated cannot be made reliable by any choice of ceiling.

It now asserts on the **minimum of five samples** — contention can only make a
sample slower, so the minimum estimates the uncontended cost — and prints every
sample on failure, because `min=412 samples=[412,455,430,501,447]` and
`min=310 samples=[310,315,312,318,311]` are different bugs.

Reproduced on demand rather than assumed: 18 concurrent graph-building processes
produced `[384, 231, 242, 559, 807]`, **three of five over budget**, so the old
assertion had a 60% chance of failing that window and passed only on the luck of
its draw. Pure CPU spin did *not* reproduce it — the contention that matters is
allocator and memory pressure from concurrent processes, not busy loops.

Recorded rather than oversold: **this reduces the flake, it does not eliminate
it.** min-of-N fails with `p^N`, and at the oversubscription that produced 508ms
no practical N helps. If it fires a fourth time the answer is a `-m perf` marker,
not a larger N or a larger budget.

### Changed

**The load-cost figures were re-measured and given one canonical home.** Seven
prose copies across four files had drifted to roughly **twice** the truth — a
cold process is ~152ms, not 0.28s, and a four-server MCP compose ~0.6s, not 1.1s
— and the warm figure was a cold measurement mislabelled, which understated
ADR-4's own no-cache case by ~2.4x. `kgf/loader.py`'s module docstring is now the
single place they are stated, with the cache condition recorded. The MCP surface
is also correctly described as **15 tools**, not 17.

---

## [1.0.0] - 2026-09-14

First versioned release. The project had no `VERSION` file before this, which
meant `push-gate` reported *"tracks no VERSION file, so the version rule does
not apply"* on every push — the safety gate was silently inert (#47).

### Fixed

**A transient provider fault no longer spends a candidate — closes #45.** Found
by running the tool end to end, not by reading code. A real run died with
`ConfigError: every configured candidate is unavailable ... Add more candidates
to models.yaml` while the configuration was fine: the very next run of the same
command wrote 25 files with tests passing. Two transient 5xx/timeouts inside one
run walked `router_fast` off its 2-candidate chain.

Two defects, the second outliving the run: the diagnosis was **false** (it told
the operator to edit working configuration in response to a provider blip), and
the demotion was **permanent** — `_active_index` has no reset, so even a
surviving run stayed pinned to its fallback model for the whole session. These
errors arrive already retried (5 attempts, 1→30s backoff), so the fix is not
more retrying but not billing a candidate for a fault that was never its own.
`call_role` now restores the index and raises `ProviderTroubleError`; a
genuinely withdrawn model still raises `ConfigError` naming `models.yaml`.

**Startup survives a provider it cannot verify — closes #41.** `validate_startup`
probes each candidate with a live `GET /v1/models` and caught only one error
class, so a key that was *set but wrong*, or an unreachable host, killed the
process with a message naming neither the role nor the provider. Now classified
three ways: a rejected credential skips at WARNING naming the env var, an
unreachable host skips at INFO, and a **429 does not skip at all** — a throttled
catalogue listing says nothing about whether the model works. The except
ordering is load-bearing and verified: those types are all `APIStatusError`
subclasses.

**Groq's real token ceiling is 8000, not the 6000 assumed — closes #43.**
Measured from live response headers on all three configured models. A quarter of
the granted budget was unused, and every coder call logged *"exceeds the whole
ceiling; throttled across minutes"*. `rpm_budget` was deliberately left at 30:
the same headers report 1000 requests but Groq returns both per-minute and
per-day ceilings and the observed reset window matches neither, and this
configuration's history is two providers added on published figures that did not
survive a real call.

**The confidence floor is calibrated on the text production actually ranks —
closes #16.** It was measured on raw task text and applied to LLM-engineered
prompts. Engineered confidence bottoms out at 0.4758, so the old 0.45 floor
admitted **33 of 33** held-out cases and reported every match as `selected`,
including all 15 whose domain was wrong — a threshold whose whole job is
withholding a weak match had never once fired. Now 0.59, the measured optimum.

Verified against the live pipeline: for `add a REST endpoint for creating an
order`, the personas the old floor would have applied were
`as_built_doc_generator` and `reverse_engineering_analyst` — a reverse-
engineering documentation persona steering Spring Boot code. The new floor
correctly returns `low_confidence` and uses the generic prompt instead.

Recorded rather than oversold: the Clopper-Pearson 95% interval on the new
precision is [0.476, 0.927], whose lower bound sits *below* the
admit-everything base rate, so at n=33 the improvement is **not statistically
established**. What is established is that 0.45 did nothing.

**Other correctness fixes.** The TPM concurrency cap is now enforced by slicing
in `run_dag` rather than computed, logged and ignored (#36). `Bash` no longer
inherits the caller's stdin, which hung every command when kgf runs as an MCP
server and would have let a granted child read the client's own protocol
traffic (#24). Tests that asserted the library *was* broken were converted to
synthetic fixtures so repairing the data could not silently retire them
(#27, #29, #34, #38).

### Added

**kgf's own MCP surface (#23)** — four stdio servers over the knowledge graph,
15 tools, with posture read from `~/.kgf/mcp.json` at launch. `Bash` stays
denied under the default flags, denied when a call argument asks for it, and
denied when the server is *spawned* with the environment variable set.

**Google Gemini and provider groundwork (#31)** — declared but wired to no role,
so it costs nothing at startup and becomes live the moment `GEMINI_API_KEY`
exists. Adding it required **no code change**, which is the "any LLM is just
configuration" claim actually holding.

### Changed

`claude-global-library` was repaired at source and rebuilt to **29.98.0**: 31
documents that would not load now do (1562/1562, up from 1544), and that
library's own `VERSION` was five releases behind its changelog. kgf's pinned
figures were re-measured against the rebuild rather than adjusted until green,
and a pin-freshness test now fails loudly instead of letting a stale pin
silently disarm three measured assertions.

### Known limitations

- **Selection quality is the ceiling.** Top-3 domain accuracy is 66.7% on the
  frozen held-out set. `spring-boot-microservices` exists in the library and is
  not in the top 3 for a mainstream REST task, so many runs correctly fall to
  `low_confidence` and use the generic prompt. `--agent <name>` forces a
  specific persona when you know which one you want.
- **The coder call is paced across minutes.** `MAX_CODER_TOKENS` (8000) plus
  prompt exceeds even the true 8000 TPM ceiling, so one generation cannot fit in
  a single minute's budget at any context size.
- **No SRS.md.** Required by `rules/44` at first Step-13; deliberately not
  invented to satisfy a checklist.
- `test_warm_load_is_within_budget` is timing-flaky under a full-suite run
  (~508ms against a 300ms budget) while passing in isolation. *Fixed after this
  release — see `[UNRELEASED]`.* The two figures first quoted here were not
  comparable: 508ms was the assertion's own measurement, while the 0.31–0.33s
  cited beside it was pytest's reported duration for the whole test, which
  includes an untimed warm-up load.
