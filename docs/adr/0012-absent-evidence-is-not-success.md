# ADR-0012 — Absent evidence is not success

**Status:** accepted · the rule three separate defects were needed to arrive at

## Context

The product's headline claim is that it writes code **and its own tests**, runs them, and repairs the
code when they fail. Whether that happened is decided by reading a test runner's output.

Runners are not built to answer the question being asked of them. A test command exits 0 to mean
*"nothing failed"*, which is not the same as *"something passed"* — and on an empty test set most of
them report success:

| runner | no tests present |
|---|---|
| `pytest` | exit **5** (`EXIT_NOTESTSCOLLECTED`) |
| `mvn test` | exit **0** + *"No tests to run."* |
| `node --test` | exit **0** |
| `npm` default stub | exit 1 |

## Decision

**A value meaning "cannot tell" is never consumed as "fine".** Concretely, three independent checks,
because no single one covers every runner:

1. **Test files must exist** before the runner is invoked at all — the product contract stated
   directly, needing no toolchain.
2. **A runner that documents an empty collection is believed** (pytest's exit 5).
3. **Where the runner prints a count, the count decides.** `BUILD SUCCESS` is not evidence that
   anything was verified.

And the rule that generalises all three: **`None` means *cannot tell*, and must fail rather than
pass.**

## Consequences

**This was found by running the tool, not reading it.** A Java run produced **seven source files, zero
test files**, and reported *"All tests passed"* — because Maven printed `No tests to run.` and exited
0.

**It was also corrupting the repair loop**, which is the part worth keeping in mind: the cheapest way
to make a runner exit 0 is to write no tests, so `Attempt 0: FAILED → Attempt 1: PASSED` was the loop
being **rewarded for deleting the test file attempt 0 had written**.

**Python was safe, which is exactly why nobody noticed.** It is the language most runs use and the one
every end-to-end check was done in. The defect lived on the Java path, and Java is the stack the client
asked about.

**The rule had to be learned twice.** The first fix guarded `executed == 0` — which `None` fails — so
the lie returned through a second door: a `*Test.java` outside `src/test/java` satisfies the
file-presence check, Maven never compiles it, surefire prints **no count line at all**, and the run
reported success again. The same day, the same mistake in the heal loop let one unscoreable attempt
overwrite the champion **and** disable rollback for every later attempt.

**Accepted cost:** a project whose runner genuinely prints no count is now reported as failed even if
it did run tests. That is the correct direction for a tool whose output a client will trust, and the
message distinguishes *"reported running 0 tests"* from *"reported no test count at all"*, because they
need different remedies.

> A guard that treats missing evidence as success does not protect anything. It just moves where the
> lie comes from.
