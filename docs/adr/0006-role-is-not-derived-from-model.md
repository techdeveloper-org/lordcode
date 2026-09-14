# ADR-0006 — Role is classified by kgf, never derived from the `model` field

**Status:** accepted · replaces an earlier mapping that was wrong on the data

## Context

Each of the 528 agents declares a `model:` in its frontmatter. The tempting inference is that this
marks a capability tier — opus for hard reasoning, sonnet for implementation — and therefore that a
persona's model tells you which pipeline role it should fill.

An earlier draft proposed exactly that: `opus|fable → reasoner`, `sonnet → primary_coder`.

## Decision

**Role is decided by a kgf-owned classifier over the agent's `name` and its prose `role` field**, with
a hand-checked override table. `model` is used for math delegation only, never for role.

## Consequences

**The mapping was falsified by counting.** Measured across all 528 agents: **450 sonnet, 78 opus, 0
fable** — and **77 of the 78 opus agents are math masters.** `model` marks math masters, not capability
tiers.

Worse, all 20 reviewer/auditor/consensus personas (`consensus-agent`, `api-security-auditor`,
`architecture-conformance-auditor`, …) are **sonnet**. The proposed map would therefore have classified
every reviewer as a coder — re-creating the exact defect it was meant to fix, where a reviewer persona
fires the coder gate in the self-heal path.

**Accepted cost:** kgf maintains a classifier and an override table that the library could, in
principle, have made unnecessary by declaring `role:`. Measured: **0 of 1,562** markdown files declare
one, so there is nothing to read.

**The classifier needed two fixtures, not one, and that is the useful part.** A name/prose rule sweeps
**88 of 528** agents into `reasoner`, including `distributed-consensus-engineer` (a *builder* of
consensus protocols) and `2d-game-engine-architect` (an implementer, despite "architect"). A positive
fixture alone would pass while mislabelling both. So:

- **positive, frozen:** the 20 known reviewer personas must classify `reasoner`;
- **negative, frozen:** named builder personas whose titles contain a reviewer-ish word must classify
  `primary_coder`.

Both must pass. The override table exists for the residue, and every override carries a one-line
reason.
