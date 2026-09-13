"""Resolve a domain to its collaboration pattern and its phase set.

Scoped deliberately to what the decision tree actually contains. `patterns.json`
holds exactly five keys per record and `phases.json` exactly three, with no join
between the two files and no dependency, ordering or input/output data anywhere
in that directory -- so a workflow DAG cannot be read from here, only a pattern
and a set of phases. Inventing the rest would mean maintaining a graph the
library does not model.

What IS readable is better than expected. D14's 101 branches are not prose: each
condition carries a structured `domain:X` token and each branch's `emits` names
the pattern directly, so the node is a domain-to-pattern lookup. All 101 parse,
covering 100 of 104 domains, and every domain and pattern they name resolves.

Entry is at D14 rather than at the root. D01-D12 are human pre-flight questions
with no human present, and D14's 101 branches all target D15 with no
back-reference to an earlier answer, so entering there is structurally sound.
The one thing lost by skipping ahead is pruning: D13 carries it, and `D13::B2`
(Solo) alone prunes 8 phases. So the caller's complexity signal is fed in as the
D13 answer instead of being skipped, and an unknown complexity yields the
unpruned set rather than a guess.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from kgf import ids
from kgf.source import LibrarySource

D13_NODE = "D13"
D14_NODE = "D14"

COMPLEXITY_SOLO = "solo"
COMPLEXITY_SQUAD = "squad"
COMPLEXITY_ENTERPRISE = "enterprise"

_DOMAIN_TOKEN = re.compile(r"domain:[A-Za-z0-9_\-]+")


@dataclass(frozen=True)
class Pattern:
    """One collaboration pattern from patterns.json.

    Five fields because the record has five keys. There is no step list, no
    phase list and no ordering in this data, and a richer object here would
    imply otherwise.
    """

    id: str
    title: str
    lead_agent: str
    lead_domain: str
    lead_math: str


@dataclass(frozen=True)
class Phase:
    """One phase from phases.json: an id, a group, and a title."""

    id: str
    group: str
    title: str


@dataclass(frozen=True)
class PatternRoute:
    """A resolved pattern plus the phase set that survives pruning."""

    domain: str
    pattern: Pattern | None
    phases: tuple[Phase, ...] = ()
    pruned: tuple[str, ...] = ()
    complexity: str = ""
    trace: tuple[str, ...] = field(default_factory=tuple)

    @property
    def resolved(self) -> bool:
        """Whether a pattern was found for this domain."""
        return self.pattern is not None


@dataclass(frozen=True)
class DecisionTree:
    """The parts of the orchestration decision tree kgf reads."""

    patterns: dict[str, Pattern]
    phases: tuple[Phase, ...]
    domain_to_pattern: dict[str, str]
    prunes_by_complexity: dict[str, tuple[str, ...]]

    def pattern_for_domain(self, domain_ref: str) -> Pattern | None:
        """The pattern D14 maps this domain to, or None for the 4 unmapped ones."""
        pattern_id = self.domain_to_pattern.get(ids.domain_id(domain_ref))
        return self.patterns.get(pattern_id) if pattern_id else None

    def route(self, domain_ref: str, complexity: str = "") -> PatternRoute:
        """Resolve a domain to its pattern and surviving phases.

        Args:
            domain_ref: Any reference to the primary domain.
            complexity: "solo", "squad" or "enterprise" -- the D13 answer. An
                empty or unrecognised value prunes nothing, so an unknown
                complexity yields the full phase set rather than a guessed one.

        Returns:
            A PatternRoute carrying the pattern, the surviving phases, what was
            pruned and why.
        """
        domain = ids.domain_id(domain_ref)
        pattern = self.pattern_for_domain(domain)
        normalised = complexity.strip().lower()

        trace = [f"D14: primary domain {domain}"]
        if pattern is None:
            trace.append("D14: no branch for this domain; pattern unresolved")
        else:
            trace.append(f"D14 -> {pattern.id} ({pattern.title})")

        pruned = self.prunes_by_complexity.get(normalised, ())
        if normalised and normalised not in self.prunes_by_complexity:
            trace.append(f"D13: complexity {normalised!r} not recognised; pruning nothing")
        elif not normalised:
            trace.append("D13: no complexity signal supplied; pruning nothing")
        else:
            trace.append(f"D13: complexity {normalised} prunes {len(pruned)} phase(s)")

        surviving = tuple(phase for phase in self.phases if phase.id not in set(pruned))
        return PatternRoute(
            domain=domain,
            pattern=pattern,
            phases=surviving,
            pruned=tuple(pruned),
            complexity=normalised,
            trace=tuple(trace),
        )


def _records(payload, *keys: str):
    """Pull a record list out of either a bare list or a keyed envelope."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def load_decision_tree(source: LibrarySource) -> DecisionTree:
    """Read patterns, phases and the D13/D14 branch data.

    Returns:
        A DecisionTree. Missing files yield an empty tree rather than raising:
        the decision tree is an enrichment over selection, and a library
        without it should degrade to lexical selection alone rather than fail.
    """
    patterns: dict[str, Pattern] = {}
    for record in _records(_read(source, "patterns.json"), "patterns"):
        pattern_id = record.get("id")
        if not pattern_id:
            continue
        patterns[str(pattern_id)] = Pattern(
            id=str(pattern_id),
            title=str(record.get("title", "")),
            lead_agent=ids.agent_id(str(record["lead_agent"])) if record.get("lead_agent") else "",
            lead_domain=ids.domain_id(str(record["lead_domain"])) if record.get("lead_domain") else "",
            lead_math=ids.agent_id(str(record["lead_math"])) if record.get("lead_math") else "",
        )

    phases = tuple(
        Phase(
            id=str(record.get("id", "")),
            group=str(record.get("group", "")),
            title=str(record.get("title", "")),
        )
        for record in _records(_read(source, "phases.json"), "phases")
        if record.get("id")
    )

    branches = _records(_read(source, "decision_branches.json"), "branches")
    return DecisionTree(
        patterns=patterns,
        phases=phases,
        domain_to_pattern=_parse_d14(branches),
        prunes_by_complexity=_parse_d13(branches),
    )


def _read(source: LibrarySource, filename: str):
    """Read one decision-tree file, returning None when absent."""
    path = source.tree_dir / filename
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_d14(branches) -> dict[str, str]:
    """Map each domain to the pattern its D14 branch emits.

    The condition reads like "primary domain == domain:backend-engineering ->
    Pattern 2", so the domain is extracted from its structured token rather
    than by interpreting the sentence, and the pattern comes from `emits`
    rather than from the prose tail. That distinction matters: reading the
    prose is how a keyword matcher sent a Spring Boot task to assembly-boot.
    """
    mapping: dict[str, str] = {}
    for branch in branches:
        if branch.get("source") != D14_NODE:
            continue
        emits = branch.get("emits") or []
        match = _DOMAIN_TOKEN.search(str(branch.get("condition", "")))
        if not match or not emits:
            continue
        mapping[ids.canonical(match.group(0))] = str(emits[0])
    return mapping


def _parse_d13(branches) -> dict[str, tuple[str, ...]]:
    """Map each complexity classification to the phases its branch prunes.

    The classification is the first word of the condition ("Solo: single
    domain, clear scope"), which is why it is split on the colon rather than
    pattern-matched: the tail is a human gloss and carries no data.
    """
    prunes: dict[str, tuple[str, ...]] = {}
    for branch in branches:
        if branch.get("source") != D13_NODE:
            continue
        condition = str(branch.get("condition", ""))
        label = condition.split(":", 1)[0].strip().lower()
        if label:
            prunes[label] = tuple(str(phase) for phase in (branch.get("prunes") or ()))
    return prunes


@lru_cache(maxsize=4)
def cached_decision_tree(root: str) -> DecisionTree:
    """load_decision_tree memoised per library root for the process lifetime."""
    return load_decision_tree(LibrarySource(root=Path(root), library_version=""))
