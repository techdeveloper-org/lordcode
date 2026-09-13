"""Assemble prompt context from selected documents, within a token budget.

What this replaces: the consumer injects the first 800 characters of one
document. On java-spring-boot-microservices that window ends at offset 796,
while the section a code-generation prompt actually wants sits at 8476 -- so the
injected text is the name, the description and a dependency list, and nothing
that would change generated code.

The problem is not truncation, it is POSITION. Taking a different 800 characters
from the right section is strictly better than taking 800 more from the front.

Budget arithmetic, measured
  A skill document has a median size of ~38,600 bytes (~9,650 tokens); an agent
  document ~14,400 bytes (~3,600 tokens). A median closure is one agent plus
  four mandatory skills, so roughly 52,000 tokens of candidate material. Into a
  2,000-token budget that is a ~4% selection ratio.

  At that ratio whole documents cannot be included, and neither can every
  section. So each entity gets a sub-budget, sections are ranked by the caller's
  intent, and whole sections are taken until the sub-budget is gone. Sections
  are dropped entire -- a section cut mid-sentence is worse than an absent one,
  because a model will act on a truncated rule as if it were complete.

Intent mapping is measured, not assumed
  An earlier draft targeted `## Coding Guidelines` for implementation work. That
  heading exists in exactly ONE of 1034 skill documents -- it was generalised
  from a single file. The headings that are actually universal are Response
  Rules, Output Expectations, Skill Scope, What Not to Do (all ~100%) and
  Anti-Patterns to Avoid (98.5%), so those are what the intents select.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from kgf import ids
from kgf.closure import Closure
from kgf.documents import Document, Section, agent_document, skill_document
from kgf.graph import KnowledgeGraph
from kgf.source import LibrarySource

CHARS_PER_TOKEN = 4
"""Chars-to-tokens ratio for budgeting.

Approximate by design: the exact count belongs to whichever tokenizer the
consumer's model uses, and kgf must not depend on one. Four characters per token
is the standard approximation for English prose and code, and it is used only to
decide what fits -- never reported as a true usage figure.
"""

DEFAULT_TOKEN_BUDGET = 2000
"""Default assembled-context budget.

Chosen for context quality within one call rather than to unlock concurrency:
the consumer's coder role already requests up to 8000 completion tokens against
a ~6000 tokens-per-minute ceiling, so no context budget makes that node fit
inside a single minute. 2000 buys two or three well-chosen sections.
"""

AGENT_BUDGET_SHARE = 0.35
"""Share of the budget reserved for the agent's own document.

The agent carries the persona and the output contract, which shape the whole
response; the skills carry domain rules. A third to the frame, two thirds to the
substance.
"""

MIN_SECTION_TOKENS = 40
"""Below this a section is not worth including.

A heading plus two lines of a rule communicates less than nothing: it reads as
a complete instruction while omitting the part that mattered.
"""


class Intent(str, Enum):
    """What the assembled context is for.

    The intent decides which sections are worth their tokens. A prompt that
    writes code needs the rules that constrain output; one that reviews code
    needs the prohibitions; one that designs needs the reasoning material.
    """

    IMPLEMENT = "implement"
    DESIGN = "design"
    REVIEW = "review"


SKILL_SECTIONS_BY_INTENT: dict[Intent, tuple[str, ...]] = {
    Intent.IMPLEMENT: (
        "response rules",
        "output expectations",
        "anti-patterns to avoid",
        "what not to do",
        "skill scope",
    ),
    Intent.DESIGN: (
        "deep mathematical foundations",
        "mathematical foundations",
        "skill scope",
        "scope boundary",
        "description",
    ),
    Intent.REVIEW: (
        "anti-patterns to avoid",
        "what not to do",
        "response rules",
        "skill scope",
    ),
}
"""Skill sections in priority order per intent, with measured coverage.

response rules 100%, output expectations 100%, skill scope 100%, what not to do
99.9%, anti-patterns to avoid 98.5%, deep mathematical foundations 87.5%. The
design intent lists both the numbered and unnumbered spellings of the maths
heading because documents.normalise_heading folds the number but the library
also uses a genuinely shorter title in 120 files.
"""

AGENT_SECTIONS_BY_INTENT: dict[Intent, tuple[str, ...]] = {
    Intent.IMPLEMENT: (
        "operating rules",
        "output format",
        "output expectations",
        "what agent must not do",
    ),
    Intent.DESIGN: (
        "role",
        "core responsibilities",
        "operating rules",
        "mathematical delegation",
    ),
    Intent.REVIEW: (
        "what agent must not do",
        "operating rules",
        "applicable standards",
        "output expectations",
    ),
}
"""Agent sections in priority order per intent.

agent.md is far more regular than SKILL.md: role, core responsibilities,
operating rules, output format, output expectations, what agent must not do and
model usage strategy are each present in all 528 documents, and applicable
standards in 418.
"""


def estimate_tokens(text: str) -> int:
    """Approximate token count of a string."""
    return len(text) // CHARS_PER_TOKEN


@dataclass(frozen=True)
class IncludedSection:
    """One section that made it into the assembled context."""

    entity: str
    kind: str
    heading: str
    tokens: int


@dataclass(frozen=True)
class DroppedSection:
    """One section that did not fit, and why."""

    entity: str
    kind: str
    heading: str
    tokens: int
    reason: str


@dataclass(frozen=True)
class AssembledContext:
    """Assembled prompt context, with a full account of what it contains.

    The ledger is not decoration. A context block that cannot say what it left
    out is impossible to debug when a model ignores a rule -- the first question
    is always whether the rule was actually sent.
    """

    text: str
    intent: Intent
    budget_tokens: int
    assembled_context_tokens: int
    included: tuple[IncludedSection, ...] = ()
    dropped: tuple[DroppedSection, ...] = ()
    defects: tuple[str, ...] = ()
    entities: tuple[str, ...] = field(default_factory=tuple)

    @property
    def within_budget(self) -> bool:
        """Whether the assembled text fits the budget it was given."""
        return self.assembled_context_tokens <= self.budget_tokens

    @property
    def utilisation(self) -> float:
        """Share of the budget used."""
        return (self.assembled_context_tokens / self.budget_tokens) if self.budget_tokens else 0.0

    def summary(self) -> str:
        """One-line account, for logs and the CLI."""
        return (
            f"{self.assembled_context_tokens}/{self.budget_tokens} tokens "
            f"({self.utilisation:.0%}), {len(self.included)} section(s) from "
            f"{len(self.entities)} document(s), {len(self.dropped)} dropped"
            + (f", {len(self.defects)} defect(s)" if self.defects else "")
        )


def assemble_context(
    graph: KnowledgeGraph,
    source: LibrarySource,
    closure: Closure,
    *,
    intent: Intent = Intent.IMPLEMENT,
    budget_tokens: int = DEFAULT_TOKEN_BUDGET,
) -> AssembledContext:
    """Build prompt context for a closure, within a token budget.

    Args:
        graph: The loaded graph.
        source: The library, for reading the markdown documents.
        closure: The agent and skills selected for this task.
        intent: What the context is for; decides section priority.
        budget_tokens: Total token ceiling for the assembled text.

    Returns:
        An AssembledContext whose text fits the budget, with a ledger of every
        section included, every section dropped, and every document that could
        not be read.
    """
    included: list[IncludedSection] = []
    dropped: list[DroppedSection] = []
    defects: list[str] = []
    blocks: list[str] = []
    entities: list[str] = []

    agent = graph.agent(closure.agent)
    agent_budget = int(budget_tokens * AGENT_BUDGET_SHARE)

    if agent is not None:
        document = agent_document(source, agent.name)
        if not document.ok:
            defects.append(f"agent {agent.name}: {document.error}")
        else:
            entities.append(agent.id)
            spent = _take_sections(
                document=document,
                entity=agent.id,
                kind="agent",
                wanted=AGENT_SECTIONS_BY_INTENT[intent],
                budget=agent_budget,
                blocks=blocks,
                included=included,
                dropped=dropped,
            )
            agent_budget -= spent

    skill_ids = closure.all_skills
    remaining = budget_tokens - sum(item.tokens for item in included)
    per_skill = _allocate(remaining, len(skill_ids))

    for index, skill_id in enumerate(skill_ids):
        skill = graph.skills.get(skill_id)
        if skill is None:
            continue
        allowance = per_skill[index] if index < len(per_skill) else 0
        if allowance < MIN_SECTION_TOKENS:
            dropped.append(
                DroppedSection(
                    entity=skill_id,
                    kind="skill",
                    heading="(whole document)",
                    tokens=0,
                    reason="no budget left after higher-priority skills",
                )
            )
            continue

        document = skill_document(source, skill.name)
        if not document.ok:
            # The degradation path issue #4 requires. 18 library documents are
            # genuinely malformed and 15 of 528 agents list at least one of them
            # as mandatory, so this is reached in normal operation: record the
            # defect, drop that skill, and continue rather than failing the run.
            defects.append(f"skill {skill.name}: {document.error}")
            dropped.append(
                DroppedSection(
                    entity=skill_id,
                    kind="skill",
                    heading="(whole document)",
                    tokens=0,
                    reason=f"unparseable: {document.error}",
                )
            )
            continue

        entities.append(skill_id)
        _take_sections(
            document=document,
            entity=skill_id,
            kind="skill",
            wanted=SKILL_SECTIONS_BY_INTENT[intent],
            budget=allowance,
            blocks=blocks,
            included=included,
            dropped=dropped,
        )

    text = "\n\n".join(blocks)
    return AssembledContext(
        text=text,
        intent=intent,
        budget_tokens=budget_tokens,
        assembled_context_tokens=estimate_tokens(text),
        included=tuple(included),
        dropped=tuple(dropped),
        defects=tuple(defects),
        entities=tuple(entities),
    )


def _allocate(remaining: int, count: int) -> list[int]:
    """Split a budget across entities, front-loaded by closure order.

    Closure order is mandatory skills, then transitive requirements, then
    optional -- strongest assertion first. An even split would give a
    third-order optional skill the same room as a mandatory one, so shares
    decay: each entity gets a little less than the one before, and the tail
    falls below MIN_SECTION_TOKENS and is dropped outright rather than
    contributing a fragment.
    """
    if count <= 0 or remaining <= 0:
        return []

    weights = [1.0 / (index + 1) for index in range(count)]
    total = sum(weights)
    return [int(remaining * weight / total) for weight in weights]


def _take_sections(
    *,
    document: Document,
    entity: str,
    kind: str,
    wanted: tuple[str, ...],
    budget: int,
    blocks: list[str],
    included: list[IncludedSection],
    dropped: list[DroppedSection],
) -> int:
    """Take whole sections from one document until its sub-budget is spent.

    Returns:
        Tokens actually spent.
    """
    spent = 0
    label = ids.slug_of(entity)
    by_key: dict[str, Section] = {}
    for section in document.sections:
        by_key.setdefault(section.key, section)

    for name in wanted:
        section = by_key.get(name)
        if section is None:
            continue

        cost = estimate_tokens(section.text)
        if cost < MIN_SECTION_TOKENS:
            dropped.append(
                DroppedSection(entity=entity, kind=kind, heading=section.title, tokens=cost, reason="too small to be useful")
            )
            continue
        if spent + cost > budget:
            # Whole sections only. A rule cut in half reads as a complete rule,
            # so a model acts on the surviving clause as if nothing were missing
            # -- which is worse than never sending it.
            dropped.append(
                DroppedSection(entity=entity, kind=kind, heading=section.title, tokens=cost, reason="would exceed the sub-budget")
            )
            continue

        blocks.append(f"--- {label} :: {section.title} ---\n{section.body.strip()}")
        included.append(IncludedSection(entity=entity, kind=kind, heading=section.title, tokens=cost))
        spent += cost

    return spent
