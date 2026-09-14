# Changelog

All notable changes to this project are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [1.0.4] - 2026-09-14

### Fixed

**Self-heal was never shown the file it was asked to fix — closes #62.** The
Java path could not repair a project at any attempt budget, and the reason was
not the model.

The diagnosis prompt spends a 6,000-char file budget in generation order, which
is effectively alphabetical. On a 16-file Spring project **10 files were
omitted, including both files the compiler named** — so the reasoner was asked
to fix code it had never seen. Two further defects in the same path, each
sufficient alone:

- `current_files = artifact.files` **replaced** the file list with whatever the
  coder chose to rewrite, so the model's view shrank every attempt while the
  runner kept compiling all 16 from disk;
- the history block repeated the whole file listing per attempt, putting the
  prompt at **~7,900 tokens against Groq's 7,000 ITPM ceiling** — five 413s, an
  exhausted candidate chain, and a dead run.

Files the failure output names now come first and are exempt from the per-file
cap; matching is on basename **or type name**, because javac reports
`location: variable ex of type ...OrderAlreadyExistsException` and never the
filename. Fixes are merged rather than replacing the file list, and history
carries what changed plus the error instead of another copy of the source.

Measured on the project that exposed it: prompt **7,912 → 3,957 tokens**, broken
files **omitted → shown in full**, visible lines of the broken file **41 → 103**,
and **3 of the 4 original compile errors now get fixed where previously none
could be**.

Not yet green: the loop now converges and then oscillates — an attempt that
fixes one file can break another it had already changed. Tracked separately.

## [1.0.3] - 2026-09-14

### Fixed

**A run that wrote no tests reported "All tests passed" — closes #59.** Found by
running the tool, not reading it: `run "add a REST endpoint for creating an
order" --lang java` produced **seven Java sources and zero test files**, and
reported success, because `mvn test` prints *"No tests to run."* and exits 0.

An exit code answers *"did anything fail"*, never *"did anything run"*. So a
generation with no tests was indistinguishable from one whose tests all passed —
in the direction that looks like success — which falsified the headline claim
that this tool writes the code *and its own tests*.

It also corrupted self-heal: the cheapest way to make a runner exit 0 is to write
no tests, so the repair loop was being **rewarded for deleting them**.

Three independent checks now, because no single one covers every runner: test
files must exist before the runner is invoked; a runner that documents an empty
collection is believed (pytest's exit 5); and where the runner prints a count,
**the count decides** — surefire's `Tests run: N` and pytest's summary are parsed,
and exit-0-with-zero-executed is a failure. `BUILD SUCCESS` is not evidence that
anything was verified. Maven accordingly loses `-q`, which was hiding that very
line.

Measured live after the fix, same task: **3 test files** in the correct Maven
layout instead of none, and an honest `FAILED` on a real compile error instead of
a false pass.

## [1.0.2] - 2026-09-14

### Fixed

**A reasoning trace could invert the task classifier's answer — closes #53.**
`strip_reasoning_trace` is applied at 17 call sites across the engine and was
absent from exactly two: `detect_language` and `classify_complexity`, the pair
whose parsing is most fragile. Both match by substring and both fall back
*silently* rather than raising, so a mis-parse was invisible at runtime.

Measured against the pre-fix parse, `<think>This is not complex at all, just one
function.</think>simple` made `classify_complexity` return **`"complex"`** — the
opposite of the model's own conclusion, because the word sat in the trace being
discarded. That answer decides which phases run and whether generation
parallelises, so the failure was a silently different pipeline, not a cosmetic
one.

Neither function had any test; `tests/test_orchestrator.py` stubs both wholesale
to reach `run_task`'s branching. Eight added, calling the real functions. Both
trace tests are verified negative controls — the language case deliberately names
an option sorting *earlier* than the true answer, because a later one passes
against the old code too, by luck of iteration order.

**The two classification call sites no longer hardcode `reasoning_effort` —
closes #54.** They passed `"low"` as a literal, reaching past
`_light_reasoning_effort_for`, which exists because each Groq reasoning family
defines that parameter differently and the wrong family's value is a hard 400.
Behaviour-preserving today only by coincidence: the adapter independently returns
`"low"` for the current model. It stops being a coincidence the moment
`models.yaml` names a different one — a config edit — where the cost is a
`BadRequestError` retried five times (31–39s) and reported as a withdrawn model.

## [1.0.1] - 2026-09-14

### Fixed

**`pip install .` labelled the package 0.1.0 — closes #50.** `pyproject.toml`
carried its own `version = "0.1.0"` while `VERSION` and this changelog said
1.0.0, so a recipient installing the project received metadata announcing a
pre-release on the day 1.0.0 shipped. `VERSION` is now the single source of truth
and `pyproject.toml` reads it (`[tool.setuptools.dynamic]`) rather than keeping a
copy, which removes the drift class instead of guarding against it.

Found because the push gate — inert for this repo's entire life until 1.0.0 added
`VERSION` — did its job and **blocked** this branch for having no version bump.

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
  (~508ms against a 300ms budget) while passing in isolation. *Fixed in 1.0.1 —
  see above.* The two figures first quoted here were not
  comparable: 508ms was the assertion's own measurement, while the 0.31–0.33s
  cited beside it was pytest's reported duration for the whole test, which
  includes an untimed warm-up load.
