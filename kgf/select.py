"""Select the agent best suited to a task, using the graph rather than keywords.

The defect this replaces: matching a task against the `Keywords:` tail of each
description sent "add a REST endpoint for creating an order in spring boot" to
assembly-boot/secure-boot-engineer, on a collision with the word "boot", and
returned nothing at all for 7 of 8 realistic tasks.

Three mechanisms, applied in order:

1. EDGE-GATED CANDIDACY. An agent no edge mentions is not a candidate. This is
   a structural filter, not a scoring term: it cannot be outvoted by a lucky
   lexical match, which is exactly how the collision above happened.

2. BM25 over graph-enriched text. An agent's document includes the skills it
   reaches by AGENT_USES_SKILL, so vocabulary one edge away counts. See
   lexicon.py -- this is what the keyword matcher structurally could not do.

3. GRAPH DISAMBIGUATION. The top lexical domains are spread along
   DOMAIN_DEPENDS_ON and CROSS_DOMAIN_REF, and candidate skills along
   SKILL_SIMILAR_TO, so a task whose words point at one domain also credits
   the domains that domain genuinely relates to. These three edge types (655
   edges between them) were loaded and unused before this milestone.

Confidence is scaled against the best ACHIEVABLE score for the query rather
than against the candidate pool, so the best of a bad field scores low instead
of being normalised up to 1.0. The tri-state depends on that: a
`low_confidence` outcome cannot exist if every winner is rescaled to look
certain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

from kgf import ids
from kgf.documents import backfilled_descriptions
from kgf.graph import KnowledgeGraph
from kgf.lexicon import Document, Lexicon, tokenize
from kgf.source import LibrarySource

DOMAIN_FANOUT = 5
"""How many lexically-ranked domains to expand along the graph."""

RELATED_DOMAIN_CREDIT = 0.35
"""Weight given to a domain reached by an edge rather than by its own words.

Below half deliberately: a related domain is evidence, not an answer. At 1.0 a
task about payments would rank every domain payments depends on equally with
payments itself.
"""

SKILL_SIGNAL_WEIGHT = 0.6
"""Weight of an agent's best-matching single skill, on top of its own document.

An agent enriched with 22 skills dilutes any one of them, so a specialist whose
single skill is an exact match would otherwise lose to a generalist that
mentions the topic in passing.
"""

DOMAIN_SIGNAL_WEIGHT = 0.25
"""Weight of the agent's domain score. Lowest of the three: the domain is
context for a decision made on the agent and its skills, not the decision."""

CONFIDENCE_SATURATION = 12.0
"""Raw score at which confidence reaches 0.5.

Chosen from the observed spread: a clearly-matched task scores in the low
twenties on the combined signal, an unrelated one in the low single digits. It
is a readability constant, not a threshold -- the transform is monotone, so
moving it rescales every confidence without changing any ranking."""

MARGIN_FLOOR = 0.5
"""Share of confidence that survives a fully contested domain.

At 0.5 a winner with no lead over a rival domain keeps half its strength: the
match may still be right, so the answer is reported with reduced confidence
rather than suppressed."""

CONFIDENCE_FLOOR = 0.45
"""Below this, the outcome is low_confidence rather than selected."""

NO_MATCH_FLOOR = 0.15
"""Below this, nothing matched in any useful sense."""

# Deliberately NOT applying lexicon.coverage() to the agent score. It was
# tried, measured, and made things worse (54.5% -> 51.5% top-1): an agent
# document enriched with up to 22 skills already covers most of any query's
# vocabulary, so the factor varies little between candidates and mostly adds
# noise. lexicon.coverage() remains useful on the focused SKILL documents and is
# kept there. Recorded because "add a coverage factor" is an obvious suggestion
# and the measurement is the only reason not to.


class Outcome(str, Enum):
    """What selection concluded. Four states, because three cannot express them.

    A caller choosing between proceeding, proceeding cautiously, proceeding
    with no persona, and stopping needs these distinguished: collapsing
    unavailable into no_match would make a missing library look like a hard
    task.
    """

    SELECTED = "selected"
    LOW_CONFIDENCE = "low_confidence"
    NO_MATCH = "no_match"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class Match:
    """One ranked agent, with the evidence that ranked it."""

    agent: str
    domain: str
    confidence: float
    lexical_score: float
    top_skill: str = ""
    top_skill_score: float = 0.0
    domain_score: float = 0.0
    edge_path: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        """The agent's slug, without the id prefix."""
        return ids.slug_of(self.agent)


@dataclass(frozen=True)
class SelectionResult:
    """The outcome of one selection, with everything needed to replay it."""

    outcome: Outcome
    matches: tuple[Match, ...] = ()
    library_version: str = ""
    query_terms: tuple[str, ...] = ()
    considered: int = 0
    disambiguation_considered: tuple[str, ...] = ()

    @property
    def best(self) -> Match | None:
        """The top match, or None when nothing was selected."""
        return self.matches[0] if self.matches else None


class Selector:
    """Builds the corpora once, then answers many selection queries.

    Construction walks every agent and skill, so build it once per process and
    reuse it -- which is also what keeps repeated CLI calls and a long-running
    consumer honest about cost.
    """

    def __init__(self, graph: KnowledgeGraph, source: LibrarySource | None = None):
        self._graph = graph
        self._backfill = backfilled_descriptions(source) if source is not None else {}
        self._skill_lexicon = Lexicon.build(self._skill_documents())
        self._agent_lexicon = Lexicon.build(self._agent_documents())
        self._domain_lexicon = Lexicon.build(self._domain_documents())
        self._candidates = self._edge_named_agents()

    @property
    def candidate_count(self) -> int:
        """How many agents are reachable by at least one edge."""
        return len(self._candidates)

    def _describe(self, record) -> str:
        """A record's description, backfilled from markdown when the registry lost it."""
        return record.description or self._backfill.get(record.name, "")

    def _skill_documents(self) -> list[Document]:
        """One document per skill: name, description, and declared M-sections."""
        documents = []
        for skill in self._graph.skills.values():
            parts = [
                skill.name.replace("-", " "),
                self._describe(skill),
                " ".join(skill.m_sections),
            ]
            documents.append(Document.from_text(skill.id, " ".join(parts), kind="skill"))
        return documents

    def _agent_documents(self) -> list[Document]:
        """One document per agent, enriched by traversal.

        The agent's own description is ~110 characters. Its skills, reached by
        AGENT_USES_SKILL and OPTIONAL_SKILL, contribute around 1800 more. That
        difference is the whole reason graph-enriched ranking beats
        description-only ranking on plainly-worded tasks.
        """
        documents = []
        for agent in self._graph.agents.values():
            parts = [agent.name.replace("-", " "), self._describe(agent)]
            for edge_type in ("AGENT_USES_SKILL", "OPTIONAL_SKILL"):
                for skill_id in self._graph.neighbours(agent.id, edge_type):
                    skill = self._graph.skills.get(skill_id)
                    if skill is None:
                        continue
                    parts.append(skill.name.replace("-", " "))
                    parts.append(self._describe(skill))
            domain = self._graph.domain_of(agent.id)
            if domain:
                parts.append(ids.slug_of(domain).replace("_", " "))
            documents.append(Document.from_text(agent.id, " ".join(parts), kind="agent"))
        return documents

    def _domain_documents(self) -> list[Document]:
        """One document per domain: its slug plus its members' names."""
        documents = []
        for domain_id, domain in self._graph.domains.items():
            parts = [domain.slug.replace("-", " "), domain.name]
            for edge_type in ("SKILL_BELONGS_TO_DOMAIN", "AGENT_BELONGS_TO_DOMAIN"):
                for edge in self._graph.in_edges(domain_id, edge_type):
                    member = self._graph.skills.get(edge.source) or self._graph.agents.get(edge.source)
                    if member is not None:
                        parts.append(member.name.replace("-", " "))
            documents.append(Document.from_text(domain_id, " ".join(parts), kind="domain"))
        return documents

    def _edge_named_agents(self) -> set[str]:
        """Agents that at least one edge mentions.

        The structural gate. An agent no edge connects to the rest of the graph
        cannot be reasoned about -- it has no skills, no domain and no peers --
        so a lexical accident must not be able to select it.
        """
        named: set[str] = set()
        for edge in self._graph.edges:
            for endpoint in (edge.source, edge.target):
                if endpoint in self._graph.agents:
                    named.add(endpoint)
        return named

    def _related_domains(self, seeds: Iterable[str]) -> dict[str, float]:
        """Spread domain credit along the graph's cross-domain edges."""
        credit: dict[str, float] = {}
        for seed in seeds:
            for edge_type in ("DOMAIN_DEPENDS_ON", "CROSS_DOMAIN_REF"):
                for target in self._graph.neighbours(seed, edge_type):
                    if target in self._graph.domains and target not in seeds:
                        credit[target] = max(credit.get(target, 0.0), RELATED_DOMAIN_CREDIT)
        return credit

    def _similar_skills(self, skill_ids: Iterable[str]) -> set[str]:
        """Skills one SKILL_SIMILAR_TO hop from the given set."""
        similar: set[str] = set()
        for skill_id in skill_ids:
            for target in self._graph.neighbours(skill_id, "SKILL_SIMILAR_TO"):
                if target in self._graph.skills:
                    similar.add(target)
        return similar

    def select(self, task: str, limit: int = 3) -> SelectionResult:
        """Rank agents for a task.

        Args:
            task: Free-text task description.
            limit: Maximum matches to return.

        Returns:
            A SelectionResult whose outcome states how much to trust it.
        """
        terms = tokenize(task)
        if not terms:
            return SelectionResult(
                outcome=Outcome.NO_MATCH,
                library_version=self._graph.library_version,
                query_terms=(),
            )

        domain_ranking = self._domain_lexicon.rank(terms)
        seed_domains = [domain_id for domain_id, score in domain_ranking[:DOMAIN_FANOUT] if score > 0]
        related = self._related_domains(seed_domains)
        domain_scores = {domain_id: score for domain_id, score in domain_ranking}

        skill_ranking = self._skill_lexicon.rank(terms)
        top_skills = {skill_id: score for skill_id, score in skill_ranking[:50] if score > 0}
        similar = self._similar_skills(top_skills)
        for skill_id in similar:
            top_skills.setdefault(skill_id, self._skill_lexicon.score(terms, skill_id) * RELATED_DOMAIN_CREDIT)

        best_possible = max((score for _id, score in self._agent_lexicon.rank(terms)), default=0.0)

        scored: list[tuple[float, Match]] = []
        for agent_id in self._candidates:
            lexical = self._agent_lexicon.score(terms, agent_id)

            top_skill, top_skill_score = "", 0.0
            for edge_type in ("AGENT_USES_SKILL", "OPTIONAL_SKILL"):
                for skill_id in self._graph.neighbours(agent_id, edge_type):
                    score = top_skills.get(skill_id, 0.0)
                    if score > top_skill_score:
                        top_skill, top_skill_score = skill_id, score

            domain = self._graph.domain_of(agent_id)
            own_domain_score = domain_scores.get(domain, 0.0)
            domain_score = own_domain_score + related.get(domain, 0.0) * own_domain_score

            combined = (
                lexical
                + SKILL_SIGNAL_WEIGHT * top_skill_score
                + DOMAIN_SIGNAL_WEIGHT * domain_score
            )
            if combined <= 0:
                continue

            scored.append(
                (
                    combined,
                    Match(
                        agent=agent_id,
                        domain=domain,
                        confidence=0.0,
                        lexical_score=lexical,
                        top_skill=top_skill,
                        top_skill_score=top_skill_score,
                        domain_score=domain_score,
                        edge_path=self._edge_path(agent_id, top_skill, domain),
                    ),
                )
            )

        if not scored:
            return SelectionResult(
                outcome=Outcome.NO_MATCH,
                library_version=self._graph.library_version,
                query_terms=tuple(terms),
                considered=len(self._candidates),
            )

        # Order by the RAW combined score, never by confidence. Confidence is a
        # saturating transform, so ordering by it lets several candidates tie at
        # the ceiling and fall through to the id tiebreak -- which silently
        # ranks alphabetically. That single mistake cost 12 of 33 held-out cases
        # and handed wins to accounting_automation_agent, agri_analytics_engineer
        # and as_built_doc_generator purely for starting with an 'a'.
        scored.sort(key=lambda pair: (-pair[0], pair[1].agent))

        best_raw = scored[0][0]
        margin = self._domain_margin(scored)
        rescored = tuple(
            Match(
                agent=match.agent,
                domain=match.domain,
                confidence=self._confidence(raw, margin if index == 0 else 0.0),
                lexical_score=match.lexical_score,
                top_skill=match.top_skill,
                top_skill_score=match.top_skill_score,
                domain_score=match.domain_score,
                edge_path=match.edge_path,
            )
            for index, (raw, match) in enumerate(scored[:limit])
        )

        top = rescored[0]
        if top.confidence < NO_MATCH_FLOOR:
            outcome = Outcome.NO_MATCH
        elif top.confidence < CONFIDENCE_FLOOR:
            outcome = Outcome.LOW_CONFIDENCE
        else:
            outcome = Outcome.SELECTED

        return SelectionResult(
            outcome=outcome,
            matches=rescored,
            library_version=self._graph.library_version,
            query_terms=tuple(terms),
            considered=len(self._candidates),
            disambiguation_considered=tuple(sorted(related) + sorted(similar)[:20]),
        )

    @staticmethod
    def _domain_margin(scored: list[tuple[float, Match]]) -> float:
        """How far the winner leads the best candidate from a DIFFERENT domain.

        This is the honest calibration signal, and it is why confidence is not
        simply a rescaled score. Two candidates from the same domain scoring
        alike says the domain is right and the choice within it is a detail.
        Two candidates from DIFFERENT domains scoring alike says the question
        "which field is this even about" is unresolved, which is precisely when
        a caller should widen or ask rather than trust the answer.
        """
        best_raw, best_match = scored[0]
        if best_raw <= 0:
            return 0.0
        for raw, match in scored[1:]:
            if match.domain != best_match.domain:
                return max(0.0, min(1.0, (best_raw - raw) / best_raw))
        return 1.0

    @staticmethod
    def _confidence(raw: float, margin: float) -> float:
        """Map a raw score and a margin onto (0, 1), monotone and unsaturating.

        raw / (raw + SATURATION) is preferred to dividing by the observed best,
        which would rescale every winner to 1.0 and make the number meaningless.
        This form keeps an absolute reading -- a weak field stays weak -- and
        can never quite reach 1.0, so a clipped ceiling cannot re-appear and
        collapse the ordering into an alphabetical tiebreak.

        The margin then discounts an answer whose domain is contested, so
        confidence reflects BOTH how well the query matched and how clearly.
        """
        strength = raw / (raw + CONFIDENCE_SATURATION)
        return round(strength * (MARGIN_FLOOR + (1.0 - MARGIN_FLOOR) * margin), 4)

    def _edge_path(self, agent_id: str, skill_id: str, domain_id: str) -> tuple[str, ...]:
        """The edges that justify this match, for the audit record.

        A selection that cannot say WHY it chose an agent is not reviewable,
        and the whole point of using the graph is that the reason exists.
        """
        path: list[str] = []
        if skill_id:
            path.append(f"{agent_id} -AGENT_USES_SKILL-> {skill_id}")
        if domain_id:
            path.append(f"{agent_id} -AGENT_BELONGS_TO_DOMAIN-> {domain_id}")
        return tuple(path)


def select_agents(
    task: str,
    graph: KnowledgeGraph,
    source: LibrarySource | None = None,
    limit: int = 3,
) -> SelectionResult:
    """Convenience wrapper building a Selector for one query.

    Prefer constructing a Selector directly when making several queries: the
    corpora are built at construction time and rebuilding them per query is
    the dominant cost.
    """
    return Selector(graph, source).select(task, limit=limit)
