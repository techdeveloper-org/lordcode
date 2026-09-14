# ADR-0011 — Self-heal keeps the best attempt, and must be shown the broken file

**Status:** accepted · two decisions the Java path could not work without

## Context

The self-heal loop diagnoses a test failure, asks the coder for a fix, re-runs, and repeats up to
`max_attempts`. On a single-file Python task it worked. On a 16-file Spring project it could not repair
anything at **any** attempt budget, and the reason was not the model.

## Decision

**1. The prompt is ordered by relevance to the failure, and the named files are exempt from the
per-file cap.** Files the runner's output names come first, matched on basename **or type name**.

**2. The loop keeps the best state reached, not the last produced.** Adapters report a
`failure_count`; an attempt that regresses is rolled back — on disk as well as in the prompt.

## Consequences

**Why 1 — the reasoner was being asked to fix code it had never seen.** The 6,000-char file budget was
spent in generation order, effectively alphabetically. Measured on the failing project: **10 of 16
files omitted, including both files the compiler named.**

Matching on filenames alone was still not enough, and only running it revealed why: javac names
**types**, not files — `location: variable ex of type
com.example.orders.exception.OrderAlreadyExistsException` never contains `OrderAlreadyExistsException.java`.

Exempting named files from the cap then blew the input ceiling (**413, ITPM limit 7000, requested
7127**), because the history block repeated the entire file listing per attempt. History now carries
which files changed plus the error, and no source — the prompt is in there once already.

| | before | after |
|---|---|---|
| prompt | 7,912 tokens | **3,957** |
| broken files | omitted | **shown in full** |
| original compile errors fixed | 0 | **3 of 4** |

**Why 2 — each fix is locally reasonable and the sequence need not be.** Errors went `3 → 1 → 5`, the
last five because an attempt rewrote a service against a constructor an *earlier attempt had itself
changed*. The loop had a bound and a success condition and **nothing in between**, so a regression was
carried forward exactly like an improvement.

**Accepted costs, both real:**

- Rollback re-runs the tests, so a rejected attempt costs an extra runner invocation.
- The counting rules are per-language and easy to get subtly wrong. Java counts **distinct error
  sites**, because Maven echoes every error in its own summary and a line count reports 10 where 5
  exist.

**Zero and "cannot tell" must stay distinct**, and conflating them cost two separate regressions the
same day — see [ADR-0012](0012-absent-evidence-is-not-success.md).

**What this does not claim.** The guarantee is narrow and stated exactly: **the loop can no longer go
backwards.** On the project that exposed it, a run that previously ended at 11 errors now ends at 1.
Java is not yet green.
