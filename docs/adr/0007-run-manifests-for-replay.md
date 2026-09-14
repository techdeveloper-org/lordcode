# ADR-0007 — Run manifests give determinism and replay

**Status:** accepted · **Cited 7 times in code**

## Context

A selection is a judgement: this agent, at this confidence, along this edge path, with these context
sections included and those dropped. Without a record, a surprising choice can only be guessed at, and
a library change that alters every future selection is invisible until someone notices the output got
worse.

## Decision

`kgf route` and `kgf context` write a **run manifest**: `library_version`, per-registry content
hashes, the agent selected with its confidence and edge path, the skill closure, and every context
section included or dropped with its token count.

`kgf replay <manifest>` re-derives all of it from the library as it stands now and reports what
changed. **No model call**, so it is cheap enough to run as a drift gate — exit 0 unchanged, 1 on
drift, 2 when the manifest itself cannot be read.

## Consequences

**Accepted cost:** every selection path must thread a manifest through, and a caller that drops a
fragment gets a refused replay rather than a partial one.

**The fingerprint basis had to change, and the original would not have worked.** `source.fingerprint()`
was keyed on `mtime_ns`. A fresh `git clone` renews every mtime, so a manifest keyed on it reports
drift on byte-identical content and could **never replay on another machine**. Now sha256 per
registry, measured at 0.009s — the convention the library's own discovery index already uses.

That was not a cosmetic fix. It is the reason the MCP surface's cross-process fingerprint check means
anything: on mtimes, four servers on one machine would have agreed and the check would have looked
fine while being worthless the moment a manifest moved.

**Two fields had to be exempted from the strict conflict rule**, and the first version refused every
real merge:

- `created_at` describes the **fragment**, not the run, so four servers stamping four times is not a
  disagreement — the earliest is kept.
- `forced_agent` is resolved from the fragments that carry an *outcome*. `False` is indistinguishable
  from unset for a bool, so the empty-field rule let any fragment claiming `True` override a selection
  that genuinely ranked — **and a manifest recording a forced agent makes replay skip re-ranking**,
  silently retiring the check replay exists to perform.

**A gap this decision closed by accident:** the third embedding trigger was unfalsifiable because
nothing recorded which disambiguation edges were consulted. `SelectionResult` always carried the
field; the manifest is what made it observable.
