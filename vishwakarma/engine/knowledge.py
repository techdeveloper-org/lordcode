"""The one module in vishwakarma that imports kgf.

ADR-2 makes kgf a same-repo sibling that imports nothing from vishwakarma.
The reverse direction is allowed but not unlimited: the plan's M6a contract
says run_task may reach kgf only through its two entry points and the
ExecutorPort adapter. Keeping every kgf import here is what makes that
checkable -- a grep for "import kgf" outside this module, engine/dag_executor.py
and engine/parallel_generate.py is the whole test.

What this replaces, and why it is not a refactor:

    selection   plugins.match_skill, a keyword match over skill names, plus
                engine/kg_routing.route_persona, which inserted a sibling
                repo on sys.path and returned None on 7 of 8 realistic tasks.
    context     plugins.py's position-blind 800-char head cut of ONE
                document. On java-spring-boot-microservices that window ends
                at offset 796 while "## Coding Guidelines" sits at 8476.
    closure     nothing. One skill per run, against a graph-asserted median
                of 4 mandatory skills.
    role        plugins.py defaulted every agent to primary_coder because 0
                of 1562 markdown files declare `role:`, which injected
                reviewer and auditor personas as the persona that writes code.

The four selection outcomes are consumed as four outcomes. Collapsing
`unavailable` into `no_match` would make a missing library look like a hard
task, which is exactly the bug class this replaces.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from kgf.closure import Closure, build_closure
from kgf.context import DEFAULT_TOKEN_BUDGET, Intent, assemble_context
from kgf.errors import LibraryNotFoundError
from kgf.loader import load_graph
from kgf.roles import classify
from kgf.select import Outcome, SelectionResult, Selector
from kgf.source import locate_library
from kgf.tools import grant_for
from vishwakarma.engine.calling import OnEvent, noop_event

INTENTS = {intent.value: intent for intent in Intent}


class KnowledgeUnavailable(Exception):
    """Raised when the library cannot be read at all.

    A hard error, deliberately. The other three outcomes degrade -- a task
    with no confident match still runs, just without a persona -- but a
    missing library is a configuration fault, and continuing silently would
    reproduce today's behaviour of a routing layer that quietly returns None.
    """


@dataclass(frozen=True)
class Knowledge:
    """Everything the graph contributes to one run, plus how it was derived.

    `context_text` is the assembled, budgeted prompt context and is what a
    persona's system prompt should be. It is not the raw agent.md: the old
    path injected a 14,454-byte persona uncapped, which is the defect M3
    exists to fix, so a caller must not substitute the document for this.
    """

    outcome: str
    library_version: str
    agent: str = ""
    agent_name: str = ""
    domain: str = ""
    confidence: float = 0.0
    edge_path: tuple[str, ...] = ()
    role: str = ""
    role_reason: str = ""
    context_text: str = ""
    context_tokens: int = 0
    budget_tokens: int = 0
    included: tuple[str, ...] = ()
    dropped: tuple[str, ...] = ()
    mandatory_skills: tuple[str, ...] = ()
    all_skills: tuple[str, ...] = ()
    regulations: tuple[str, ...] = ()
    math_agents: tuple[str, ...] = ()
    tools: frozenset[str] = frozenset()
    tool_defects: tuple[str, ...] = ()
    context_defects: tuple[str, ...] = ()
    considered: int = 0
    runner_up: str = ""

    @property
    def has_persona(self) -> bool:
        """Whether a persona may be applied to a coder role.

        False for low_confidence on purpose. A match kgf itself is not
        confident in is recorded in the manifest and reported, but the run
        uses the generic system prompt rather than steering the coder with a
        persona that may be wrong -- the same reasoning M0.3 applied when it
        refused personas of unknown role.
        """
        return self.outcome == Outcome.SELECTED.value and bool(self.context_text)

    @property
    def selected(self) -> bool:
        """Whether selection produced a match worth recording."""
        return self.outcome in (Outcome.SELECTED.value, Outcome.LOW_CONFIDENCE.value)


_CACHE: dict[str, tuple] = {}


def _graph_and_selector(library: Path | None):
    """Load the graph and build the Selector once per library root.

    Selector construction walks every agent and skill, so building it per
    call would pay that on every task. Keyed on the resolved root so a test
    pointing at a fixture library cannot collide with the real one.
    """
    try:
        source = locate_library(library)
    except LibraryNotFoundError as exc:
        raise KnowledgeUnavailable(str(exc)) from exc

    key = str(source.root)
    if key not in _CACHE:
        graph, log = load_graph(library)
        _CACHE[key] = (source, graph, log, Selector(graph, source))
    return _CACHE[key]


def reset_cache() -> None:
    """Drop the cached graph and selector. For tests and library changes."""
    _CACHE.clear()


def resolve(
    task: str,
    *,
    intent: str = Intent.IMPLEMENT.value,
    budget_tokens: int = DEFAULT_TOKEN_BUDGET,
    forced_agent: str | None = None,
    forced_skill: str | None = None,
    library: Path | None = None,
    on_event: OnEvent = noop_event,
) -> Knowledge:
    """Select an agent for a task and assemble its budgeted context.

    Args:
        task: The engineered task text. The engineered prompt, not the user's
            raw request, because that is what every other step works from.
        intent: One of Intent's values; decides which sections earn their
            tokens.
        budget_tokens: Ceiling for the assembled context.
        forced_agent: Skip ranking and use this agent. Its closure and context
            are still built, so forcing an agent does not mean forcing a
            truncated description.
        forced_skill: Put this skill at the front of the closure, so it is the
            first to earn context budget. It joins the closure rather than
            arriving as a separate prompt fragment, because two mechanisms for
            injecting library knowledge is one too many -- the fragment path is
            what plugins.py did with an 800-char head cut.
        library: Library root; None discovers the sibling directory.
        on_event: Progress sink, so a selection and its evidence appear in the
            CLI echo and the web UI activity log.

    Returns:
        A Knowledge whose `outcome` states how much to trust it.

    Raises:
        KnowledgeUnavailable: if the library cannot be located or read.
    """
    source, graph, _log, selector = _graph_and_selector(library)

    if forced_agent is not None:
        agent = graph.agent(forced_agent)
        if agent is None:
            raise KnowledgeUnavailable(f"no agent named {forced_agent!r} in the library")
        result = None
        agent_ref = forced_agent
        confidence = 1.0
        domain = ""
        edge_path: tuple[str, ...] = ()
        outcome = Outcome.SELECTED
    else:
        result = selector.select(task)
        best = result.best
        outcome = result.outcome
        if best is None:
            on_event(
                {
                    "type": "kgf_selection",
                    "outcome": outcome.value,
                    "library_version": result.library_version,
                    "considered": result.considered,
                }
            )
            return Knowledge(outcome=outcome.value, library_version=result.library_version)
        agent_ref = best.agent
        confidence = best.confidence
        domain = best.domain
        edge_path = best.edge_path

    closure = build_closure(graph, agent_ref)
    if closure is not None and forced_skill:
        closure = _with_forced_skill(graph, closure, forced_skill)
    if closure is None:
        raise KnowledgeUnavailable(f"agent {agent_ref!r} has no resolvable closure")

    assembled = assemble_context(
        graph,
        source,
        closure,
        intent=INTENTS.get(intent, Intent.IMPLEMENT),
        budget_tokens=budget_tokens,
    )
    grant = grant_for(graph, agent_ref, closure=closure)
    assignment = classify(agent_ref)

    knowledge = Knowledge(
        outcome=outcome.value,
        library_version=graph.library_version,
        agent=agent_ref,
        agent_name=_slug(agent_ref),
        domain=domain or closure.domain,
        confidence=confidence,
        edge_path=tuple(edge_path),
        role=assignment.role,
        role_reason=assignment.reason,
        context_text=assembled.text,
        context_tokens=assembled.assembled_context_tokens,
        budget_tokens=assembled.budget_tokens,
        included=tuple(str(section.heading) for section in assembled.included),
        dropped=tuple(str(section.heading) for section in assembled.dropped),
        mandatory_skills=closure.mandatory_skills,
        all_skills=closure.all_skills,
        regulations=closure.regulations,
        math_agents=closure.math_agents,
        tools=grant.tools if grant is not None else frozenset(),
        tool_defects=grant.defects if grant is not None else (),
        context_defects=assembled.defects,
        considered=result.considered if result is not None else 0,
        runner_up=_runner_up(result),
    )

    on_event(
        {
            "type": "kgf_selection",
            "outcome": knowledge.outcome,
            "agent": knowledge.agent_name,
            "domain": knowledge.domain,
            "confidence": round(knowledge.confidence, 3),
            "edge_path": list(knowledge.edge_path),
            "role": knowledge.role,
            "skills": len(knowledge.all_skills),
            "context_tokens": knowledge.context_tokens,
            "budget_tokens": knowledge.budget_tokens,
            "dropped_sections": len(knowledge.dropped),
            "tools": sorted(knowledge.tools),
            "library_version": knowledge.library_version,
        }
    )
    for defect in knowledge.context_defects + knowledge.tool_defects:
        on_event({"type": "kgf_defect", "detail": defect})

    return knowledge


@dataclass(frozen=True)
class Listing:
    """One catalogue entry, for `vishwakarma skills` and the web UI."""

    name: str
    description: str
    domain: str = ""
    role: str = ""


def list_skills(library: Path | None = None) -> list[Listing]:
    """Every skill in the graph, by name.

    Here rather than in the CLI because the CLI must not import kgf: M6a's
    contract keeps the boundary at this module and a test enforces it. This
    replaces plugins.load_all_skills, whose own loaders could never find
    anything -- vishwakarma/skills/ has never existed -- and whose library
    reader is now kgf's job.

    No domain is reported. `Skill.domain` is a display name on 175 of 1034
    records, which is the defect M1 fixed by reading membership from
    SKILL_BELONGS_TO_DOMAIN edges instead; using the field here would put it
    straight back. A listing does not justify 1034 edge lookups.

    134 skills carry no description at all, so an empty one is expected rather
    than a fault.
    """
    _source, graph, _log, _selector = _graph_and_selector(library)
    return sorted(
        (
            Listing(name=skill.name, description=skill.description.strip())
            for skill in graph.skills.values()
        ),
        key=lambda listing: listing.name,
    )


def list_agents(library: Path | None = None) -> list[Listing]:
    """Every agent in the graph, with the role kgf's classifier assigns it.

    The role is computed rather than read: 0 of the library's 1562 documents
    declare one, which is the defect ADR-6 exists to work around. 147 agents
    carry no description.
    """
    _source, graph, _log, _selector = _graph_and_selector(library)
    return sorted(
        (
            Listing(
                name=agent.name,
                description=agent.description.strip(),
                role=classify(agent.id).role,
            )
            for agent in graph.agents.values()
        ),
        key=lambda listing: listing.name,
    )


def _with_forced_skill(graph, closure: Closure, skill_ref: str) -> Closure:
    """Put one skill at the head of a closure's mandatory set.

    Front rather than back: context assembly spends its budget in order and
    drops from the end, so appending a forced skill would let it be the first
    thing dropped -- which is the opposite of forcing it.

    Raises:
        KnowledgeUnavailable: if no such skill exists. A silent miss would make
            a typo indistinguishable from a skill that contributed nothing.
    """
    skill = graph.skill(skill_ref)
    if skill is None:
        raise KnowledgeUnavailable(f"no skill named {skill_ref!r} in the library")
    if skill.id in closure.mandatory_skills:
        return closure
    return replace(closure, mandatory_skills=(skill.id,) + tuple(closure.mandatory_skills))


def _slug(agent_ref: str) -> str:
    """The agent's readable name, without the id prefix."""
    return agent_ref.split(":", 1)[-1].replace("_", "-")


def _runner_up(result: SelectionResult | None) -> str:
    """The second-ranked agent, for the manifest's record of what lost."""
    if result is None or len(result.matches) < 2:
        return ""
    return _slug(result.matches[1].agent)
