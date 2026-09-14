# ADR-0003 — Lexical (BM25) ranking, no embeddings

**Status:** accepted, with a revisit condition that has since **fired**

## Context

Selecting an agent from 528 agents and 1,034 skills is a retrieval problem, and the default modern
answer is embeddings. Measured against the library's actual content: 900 of 1,034 skills have a
non-empty description and 220 carry a `Keywords:` tail, so there is real lexical signal to rank on.

An embedding backend adds a dependency, a model download, a vector store and a cache-invalidation
problem, in exchange for semantic matching this corpus may not need.

## Decision

Rank lexically with BM25. No embeddings.

**Scoped deliberately to *ranking*, not to the package.** [ADR-0008](0008-outbound-http-for-granted-tools-only.md)
later gave the tool runtime outbound HTTP, so "kgf is offline" is no longer true of the package as a
whole — only of selection and context assembly. That narrowing is recorded rather than left to be
discovered.

## Consequences

**Accepted cost:** 134 skills have no description at all. For those the corpus is `name` + `domain`,
and the held-out set was required to include such tasks so the weakness is measured rather than hidden.

**The revisit condition has fired, and this record says so rather than quietly holding.** The trigger
was top-3 domain accuracy below 75%. Measured on the frozen 33-case set: **66.7%**. So the condition
that would reopen this decision has been met.

It has *not* been reopened, for a reason that is itself measured: the obvious backend,
`sentence-transformers`, imports in **13.6–16.2 seconds**, against a 300ms warm-load budget and a
four-server MCP compose that would become a minute. A later evaluation identified Ollama's
`nomic-embed-text` as the better instrument — a separate process, so the cost is an HTTP call rather
than a 14-second import — and that remains the open path.

**A correction that removed one of the original motivations:** 281 registry records had lost their
description in the library build and recover it from markdown. That was the class embeddings were
being reserved for, and it turned out to be a parsing fix.
