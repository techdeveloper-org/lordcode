# ADR-0008 — Outbound HTTP for granted tools only, denied by default

**Status:** accepted · **Decider:** project owner

## Context

The tool runtime grants personas eight tools, two of which — `WebFetch` and `WebSearch` — are
network-facing. They could ship as stubs. Implementing them for real crosses a boundary three earlier
statements had assumed shut, including [ADR-0003](0003-lexical-ranking-not-embeddings.md)'s "offline".

## Decision

Implement both, on `urllib.request` from the standard library so kgf gains **no new dependency**.

**The trust boundary is stated rather than implied:** the library on disk remains the only source of
KNOWLEDGE. Nothing fetched is ever treated as a skill, an agent or an edge. The network is reachable
only through a tool the graph granted **and** the sandbox enabled, and **both sandbox flags default to
`False`** — the default posture is no network.

## Consequences

**Accepted cost:** SSRF becomes kgf's problem, and the first design specified defences `urllib` cannot
deliver. All three were corrected by measurement:

- **Redirects.** `urlopen` follows them internally at `max_redirections = 10`, so "followed at most 3
  times, each re-checked" was unachievable by validating before the call — it yields **zero** per-hop
  checks. One open redirect defeats the whole design. Implemented as an `HTTPRedirectHandler` subclass
  re-validating every hop, cap 3.
- **Address rejection is property-based, not a CIDR list.** The literal list first drafted was measured
  to miss `::ffff:127.0.0.1` (IPv4-mapped), `fe80::1` (link-local — `fc00::/7` is *unique-local*, a
  different thing), `0.0.0.0`, `100.64.0.1` (CGNAT) and `64:ff9b::7f00:1` (NAT64 to loopback, which
  **no** `ipaddress` property catches).
- **DNS rebinding.** `AbstractHTTPHandler.do_open` passes the *hostname* to `http.client`, which
  resolves it **again** — two lookups, a genuine TOCTOU gap. The connection is made to the validated
  address, with `Host` and TLS `server_hostname` preserved.

A default opener also carries `FileHandler`, `FTPHandler` and `DataHandler`, so a `Location:
file:///etc/passwd` on a redirect defeats a scheme check applied only to the initial URL. The opener is
built without them.

**A named third-party dependency:** `WebSearch` defaults to DuckDuckGo's keyless HTML endpoint so it
works without credentials. That is an unversioned, ToS-governed, silently-blockable third party
embedded in the package. Overridable via `KGF_SEARCH_ENDPOINT`, and a 403 / CAPTCHA / HTML-shape change
is treated as a tool **failure**, never as an empty result — a search that silently returns nothing is
worse than one that errors.

**Replay cannot survive a fetch.** The manifest records a response hash and
[ADR-0007](0007-run-manifests-for-replay.md)'s replay **refuses to re-fetch**, reporting a mismatch
rather than silently producing different context.
