# ADR-0010 — A rate limit must not spend a role's candidate chain

**Status:** accepted · the taxonomy three separate defects converged on

## Context

Each role in `models.yaml` is an **ordered failover chain**, not a pool: one `_active_index` per role,
advanced permanently by `handle_unavailable` when a candidate proves unusable. That is correct for a
withdrawn model — a model that is gone stays gone.

It is wrong for everything else, and "everything else" turned out to be most of what actually happens.

## Decision

Failures are classified by **what the operator should do about them**, and only one class spends a
candidate:

| Failure | Behaviour |
|---|---|
| model withdrawn (404/410/403) | advance permanently — the chain exists for this |
| **rate limit (429)** | **hold.** Never advance; the budget is exhausted, not the model |
| transient (5xx, timeout, empty response) | advance to try, but **give the index back** if the chain exhausts |
| credential rejected at startup | skip with a WARNING naming the env var |
| host unreachable at startup | skip at INFO |
| **429 at startup** | **do not skip** — a throttled catalogue says nothing about the model |

## Consequences

**Why 429 must not advance:** every candidate for a role resolves to the same provider key, so its
*budget* is exhausted, not the model. Advancing would silently spend the role's entire fallback chain
on one throttled minute and then raise `ConfigError("every configured candidate is unavailable")` as
though the models had been withdrawn.

**Why transient needs the index back — found by running the tool, not reading it.** A real run died
with `ConfigError: every configured candidate is unavailable … Add more candidates to models.yaml`
while the configuration was **fine**; the very next run of the same command wrote 25 files with tests
passing. Two transient faults inside one run had walked a 2-candidate chain off its end.

Two defects there, the second outliving the run: the diagnosis was **false** (it told the operator to
edit working configuration in response to a provider blip) and the demotion was **permanent**, because
`_active_index` has no reset. `call_role` now snapshots the index, and on an exhausted chain where at
least one failure was transient it restores it and raises `ProviderTroubleError` instead.

**Accepted cost:** `restore_active_index` is a second writer of state that `handle_unavailable`
otherwise owns exclusively. It is deliberately narrow — **it only ever rolls backwards**; passing a
larger index is ignored, so it cannot become an alternative way to advance.

**The except ordering is load-bearing and is verified, not assumed.** `AuthenticationError`,
`PermissionDeniedError`, `RateLimitError` and `InternalServerError` are **all** `APIStatusError`
subclasses, so a blanket `except openai.APIError` collapses every row of the table above into one.
The narrow arms must be caught first.

**One premise here has a known expiry**, recorded so it is not tripped over: *"every candidate resolves
to the same provider key"* holds only while every candidate is Groq. The moment a role names a second
provider with its own budget, refusing to advance means sitting on an exhausted bucket while a fresh
one goes unused — and the rule becomes *advance only to a genuinely separate budget, keyed on the rate
limiter's own `(provider, api_key_env)` tuple*.
