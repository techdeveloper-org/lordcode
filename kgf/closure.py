"""Expand a selected agent into the full working set the graph says it needs.

Today's consumer injects ONE skill per run. The graph says an agent needs a
median of 4 mandatory skills (mean 4.7, max 32), and those skills in turn
require others: SKILL_REQUIRES_SKILL carries 952 edges. A single skill is not a
smaller version of that -- it is a different thing.

The closure also pulls in what the agent cannot do alone: the mathematics agent
it delegates proofs to, the peers it coordinates with, and the regulations that
bind it.

Two safety properties, both load-bearing on real data rather than theoretical:

  Cycle safety. SKILL_REQUIRES_SKILL is not a DAG in this library, so a naive
  recursive walk does not terminate. Traversal is breadth-first over a visited
  set.

  Depth capping. Transitive requirements fan out quickly, and an unbounded
  closure would pull most of the skill graph into a prompt that has a token
  budget. The cap is a deliberate ceiling, and what it cut is recorded rather
  than dropped silently.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from kgf import ids
from kgf.graph import KnowledgeGraph

MAX_REQUIREMENT_DEPTH = 3
"""How many SKILL_REQUIRES_SKILL hops to follow past the mandatory set.

Three reaches genuine foundations -- a Spring skill requires rdbms-core, which
requires its own basics -- without dragging in the long tail. Raising it mostly
adds skills too general to help a specific task.
"""

MAX_CLOSURE_SKILLS = 40
"""Ceiling on skills in one closure, to stop a fan-out swallowing a budget.

Well above the observed median of 4 mandatory plus transitive requirements, so
it bites only on the outliers -- the max mandatory count alone is 32.
"""


@dataclass(frozen=True)
class Closure:
    """Everything the graph says one agent needs for a task."""

    agent: str
    mandatory_skills: tuple[str, ...] = ()
    optional_skills: tuple[str, ...] = ()
    required_skills: tuple[str, ...] = ()
    math_agents: tuple[str, ...] = ()
    coordinating_agents: tuple[str, ...] = ()
    regulations: tuple[str, ...] = ()
    domain: str = ""
    truncated: tuple[str, ...] = ()
    depth_reached: int = 0

    @property
    def all_skills(self) -> tuple[str, ...]:
        """Mandatory skills first, then transitive requirements, then optional.

        Ordered by how strongly the graph asserts them, because a caller
        fitting this into a token budget drops from the end.
        """
        seen: list[str] = []
        for group in (self.mandatory_skills, self.required_skills, self.optional_skills):
            for skill_id in group:
                if skill_id not in seen:
                    seen.append(skill_id)
        return tuple(seen)

    @property
    def size(self) -> int:
        """Total distinct skills in the closure."""
        return len(self.all_skills)

    def names(self) -> tuple[str, ...]:
        """Skill slugs, for display."""
        return tuple(ids.slug_of(skill_id) for skill_id in self.all_skills)


def build_closure(
    graph: KnowledgeGraph,
    agent_ref: str,
    *,
    max_depth: int = MAX_REQUIREMENT_DEPTH,
    max_skills: int = MAX_CLOSURE_SKILLS,
) -> Closure | None:
    """Expand an agent into its graph-asserted working set.

    Args:
        graph: The loaded graph.
        agent_ref: Any reference to the agent.
        max_depth: SKILL_REQUIRES_SKILL hops to follow past the mandatory set.
        max_skills: Ceiling on total skills; what is cut is recorded in
            Closure.truncated rather than dropped.

    Returns:
        The Closure, or None if no such agent exists.
    """
    agent = graph.agent(agent_ref)
    if agent is None:
        return None

    mandatory = tuple(graph.neighbours(agent.id, "AGENT_USES_SKILL"))
    optional = tuple(
        skill_id
        for skill_id in graph.neighbours(agent.id, "OPTIONAL_SKILL")
        if skill_id not in mandatory
    )

    required, depth_reached, truncated = _requirement_closure(
        graph, mandatory, max_depth=max_depth, budget=max_skills - len(mandatory)
    )

    return Closure(
        agent=agent.id,
        mandatory_skills=mandatory,
        optional_skills=optional,
        required_skills=required,
        math_agents=tuple(graph.neighbours(agent.id, "DELEGATES_MATH_TO"))
        + tuple(graph.neighbours(agent.id, "SECONDARY_MATH_DELEGATION")),
        coordinating_agents=tuple(graph.neighbours(agent.id, "COORDINATES_WITH")),
        regulations=tuple(graph.neighbours(agent.id, "REGULATED_BY")),
        domain=graph.domain_of(agent.id),
        truncated=truncated,
        depth_reached=depth_reached,
    )


def _requirement_closure(
    graph: KnowledgeGraph,
    seeds: tuple[str, ...],
    *,
    max_depth: int,
    budget: int,
) -> tuple[tuple[str, ...], int, tuple[str, ...]]:
    """Breadth-first transitive SKILL_REQUIRES_SKILL closure over seeds.

    Breadth-first rather than recursive because this relation contains cycles
    in the real library, so a depth-first walk without a visited set would not
    terminate. Breadth-first also means the budget cuts the most distant
    requirements rather than an arbitrary branch.

    Returns:
        (required skills excluding the seeds, deepest level reached, skills
        omitted because the budget ran out).
    """
    visited = set(seeds)
    found: list[str] = []
    truncated: list[str] = []
    depth_reached = 0

    frontier: deque[tuple[str, int]] = deque((seed, 0) for seed in seeds)
    while frontier:
        skill_id, depth = frontier.popleft()
        if depth >= max_depth:
            continue
        for target in graph.neighbours(skill_id, "SKILL_REQUIRES_SKILL"):
            if target in visited or target not in graph.skills:
                continue
            visited.add(target)
            if len(found) >= budget:
                truncated.append(target)
                continue
            found.append(target)
            depth_reached = max(depth_reached, depth + 1)
            frontier.append((target, depth + 1))

    return tuple(found), depth_reached, tuple(truncated)
