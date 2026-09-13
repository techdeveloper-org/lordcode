"""Decide which pipeline role an agent's persona may steer.

Issue #2 item 3 fixed an active mis-application: because no agent.md declares a
`role:` field, every persona defaulted to the coder role, so reviewers and
auditors were injected as the persona that WRITES the code they exist to
critique. The fix refused every undeclared role, which is safe but applies no
persona at all. This module supplies the missing classification.

Three sources were considered. Two are unusable, and saying why matters,
because both look plausible:

  `model` is NOT a capability tier. It reads 450 sonnet / 78 opus / 0 fable,
  and 77 of the 78 opus agents are math masters -- it marks math mastery, not
  seniority. Every reviewer persona is sonnet, so mapping sonnet to the coder
  role would recreate exactly the defect #2 just fixed.

  The prose `role` field is NOT a usable signal either. 65 agents whose role
  text mentions reviewing, auditing or validating are plainly builders
  (ast-graph-engineer, cosmwasm-contract-engineer, android-ui-designer):
  describing a job that includes review is not the same as being a reviewer.

  The NAME is usable, but only with a narrow vocabulary. A broad rule --
  auditor, reviewer, consensus, validator, architect, analyst, advisor --
  matches 82 of 528 and sweeps in obvious builders: 2d-game-engine-architect,
  cpu-architecture-specialist, credit-risk-analyst, five-g-core-architect. So
  the vocabulary is restricted to the three tokens that carry no builder
  reading, and the one remaining false positive is overridden by name.

Two fixtures guard this, and both are needed. A positive fixture alone would
pass while mislabelling distributed-consensus-engineer, which builds consensus
protocols rather than reviewing anything.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from kgf import ids
from kgf.graph import KnowledgeGraph

ROLE_REASONER = "reasoner"
ROLE_PRIMARY_CODER = "primary_coder"

REVIEWER_TOKENS = ("auditor", "reviewer", "consensus")
"""Name tokens that carry no plausible builder reading.

Deliberately excludes architect, analyst, advisor, specialist and validator.
Each of those is worn by builders in this library -- 2d-game-engine-architect
implements an engine, credit-risk-analyst builds models -- so including any of
them trades a missing persona for a wrong one, which is the worse failure and
the one #2 was about.
"""

_REVIEWER_PATTERN = re.compile(
    r"(?:^|[-_])(?:" + "|".join(REVIEWER_TOKENS) + r")(?:$|[-_])"
)

NEGATIVE_OVERRIDES: dict[str, str] = {
    "distributed-consensus-engineer": (
        "builds distributed consensus protocols (Raft, Paxos); 'consensus' here "
        "names the subject matter, not a reviewing function"
    ),
}
"""Agents the name rule matches but which are builders.

One entry, because the vocabulary was narrowed until only one false positive
remained. A growing list here would mean the vocabulary is wrong, not that more
exceptions are needed.
"""

POSITIVE_OVERRIDES: dict[str, str] = {}
"""Reviewers the name rule misses.

Empty, and deliberately so. solution-architect is the obvious candidate -- it
designs and reviews rather than implements -- but the consumer's own pipeline
already names it explicitly for that step, so classifying it here would change
behaviour on a path that is not asking this module anything. Left out until
something actually needs it.
"""


@dataclass(frozen=True)
class RoleAssignment:
    """One agent's classified role, with the reason it was classified."""

    agent: str
    role: str
    reason: str

    @property
    def is_reviewer(self) -> bool:
        """Whether this agent steers the reasoner role."""
        return self.role == ROLE_REASONER


def classify(agent_name: str) -> RoleAssignment:
    """Classify one agent by name.

    Args:
        agent_name: The agent's slug or id, in any reference form.

    Returns:
        A RoleAssignment naming the role and why, so a surprising assignment
        can be traced to the rule that made it rather than guessed at.
    """
    slug = ids.slug_of(ids.agent_id(agent_name)).replace("_", "-")

    if slug in NEGATIVE_OVERRIDES:
        return RoleAssignment(
            agent=ids.agent_id(agent_name),
            role=ROLE_PRIMARY_CODER,
            reason=f"negative override: {NEGATIVE_OVERRIDES[slug]}",
        )

    if slug in POSITIVE_OVERRIDES:
        return RoleAssignment(
            agent=ids.agent_id(agent_name),
            role=ROLE_REASONER,
            reason=f"positive override: {POSITIVE_OVERRIDES[slug]}",
        )

    match = _REVIEWER_PATTERN.search(slug)
    if match:
        return RoleAssignment(
            agent=ids.agent_id(agent_name),
            role=ROLE_REASONER,
            reason=f"name contains the reviewer token {match.group(0).strip('-_')!r}",
        )

    return RoleAssignment(
        agent=ids.agent_id(agent_name),
        role=ROLE_PRIMARY_CODER,
        reason="no reviewer token in the name",
    )


def classify_all(graph: KnowledgeGraph) -> dict[str, RoleAssignment]:
    """Classify every agent in the graph, keyed by canonical agent id."""
    return {agent_id: classify(agent.name) for agent_id, agent in graph.agents.items()}


def reviewers(graph: KnowledgeGraph) -> tuple[str, ...]:
    """Every agent classified as steering the reasoner role, sorted."""
    return tuple(
        sorted(
            agent_id
            for agent_id, assignment in classify_all(graph).items()
            if assignment.is_reviewer
        )
    )
