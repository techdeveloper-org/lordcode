"""Typed nodes, typed edges, and the adjacency structure over them.

Records in this library are ragged: 90 distinct keys appear across the 528
agent records but only 11 on every one; 116 across the 1034 skills but only 7
on every one. delegates_math_to is present on 13 of 528 records;
allowed_tools on 569 of 1034; description absent on 147 agents and 134 skills.

So absence is the normal case, not an anomaly, and every non-universal field
is reached through an accessor that returns a typed empty value. A record
class here never raises KeyError -- a traversal that blows up two layers deep
because one of 1562 records omitted an optional field would be a worse
failure than a missing value, and the absence is already reported as INFO by
the loader.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from kgf import ids

EDGE_TYPES = (
    "AGENT_BELONGS_TO_DOMAIN",
    "AGENT_USES_SKILL",
    "COORDINATES_WITH",
    "CROSS_DOMAIN_REF",
    "DELEGATES_MATH_TO",
    "DOMAIN_DEPENDS_ON",
    "HAS_TOOL_ACCESS",
    "OPTIONAL_SKILL",
    "PROPAGATES_CHANGE_TO",
    "REGULATED_BY",
    "SECONDARY_MATH_DELEGATION",
    "SKILL_BELONGS_TO_DOMAIN",
    "SKILL_REQUIRES_SKILL",
    "SKILL_SIMILAR_TO",
)
"""The 14 edge types schema.json declares, all of which occur in the data."""

TOOL_TIERS = ("tool:readonly", "tool:implementation", "tool:web_write")
"""Synthetic nodes with no registry of their own.

HAS_TOOL_ACCESS targets a TIER, not a tool: 50 edges point at
tool:implementation, 29 at tool:web_write, 15 at tool:readonly. No registry
declares these nodes, so without synthesising them all 94 of those edges
dangle. The underscore in web_write follows the edges rather than
schema.json's hyphenated pattern -- see ids.tool_tier_id.
"""


@dataclass(frozen=True)
class Record:
    """Base for a registry-backed node: a canonical id plus its raw mapping."""

    id: str
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def text(self, *keys: str) -> str:
        """First non-empty string among keys, or "" if none is present."""
        for key in keys:
            value = self.raw.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return ""

    def strings(self, *keys: str) -> tuple[str, ...]:
        """Flattened string list from the first key that holds one.

        Tolerates the library's two shapes for the same idea: a real list, and
        a comma-separated string (74 of 569 allowed_tools values are written
        as `"Read,Glob,Grep"` rather than as a YAML list).
        """
        for key in keys:
            value = self.raw.get(key)
            if isinstance(value, str):
                parts = [part.strip() for part in value.split(",")]
                return tuple(part for part in parts if part)
            if isinstance(value, (list, tuple)):
                return tuple(str(item).strip() for item in value if str(item).strip())
        return ()

    def flag(self, key: str) -> bool:
        """Boolean field, False when absent."""
        return bool(self.raw.get(key))


@dataclass(frozen=True)
class Agent(Record):
    """One agent from agents_all.json."""

    @property
    def name(self) -> str:
        """Human-readable name, falling back to the id's slug."""
        return self.text("name") or ids.slug_of(self.id)

    @property
    def description(self) -> str:
        """Description prose, "" for the 147 agents that carry none."""
        return self.text("description")

    @property
    def model(self) -> str:
        """Declared model tier.

        NOT a capability signal: 77 of the 78 `opus` agents are math masters,
        so this field marks math mastery rather than seniority. Never derive a
        pipeline role from it.
        """
        return self.text("model")

    @property
    def declared_tools(self) -> tuple[str, ...]:
        """The agent's own tools list -- the ceiling on what it may be granted."""
        return self.strings("tools")

    @property
    def is_math_master(self) -> bool:
        """Whether this agent is a mathematics authority for its domain."""
        return self.flag("is_math_master")

    @property
    def primary_domain(self) -> str:
        """Canonical id of the agent's primary home domain, or ""."""
        slug = self.text("primary_home_kg", "domain")
        return ids.domain_id(slug) if slug else ""


@dataclass(frozen=True)
class Skill(Record):
    """One skill from skills_all.json."""

    @property
    def name(self) -> str:
        """Human-readable name, falling back to the id's slug."""
        return self.text("name") or ids.slug_of(self.id)

    @property
    def description(self) -> str:
        """Description prose, "" for the 134 skills that carry none."""
        return self.text("description")

    @property
    def allowed_tools(self) -> tuple[str, ...]:
        """Tools this skill permits; may only narrow an agent's ceiling."""
        return self.strings("allowed_tools", "allowed-tools")

    @property
    def m_sections(self) -> tuple[str, ...]:
        """Declared M1-M6 mathematical section titles, if any."""
        return self.strings("m_sections")

    @property
    def domain(self) -> str:
        """Canonical id of the skill's home domain, or ""."""
        slug = self.text("domain")
        return ids.domain_id(slug) if slug else ""


@dataclass(frozen=True)
class Domain(Record):
    """One domain from domains_all.json.

    These records have no `id` field at all (0 of 104) -- only an integer
    domain_id and a hyphenated slug -- so the id here is synthesised.
    """

    @property
    def slug(self) -> str:
        """The hyphenated slug as written in the registry."""
        return self.text("slug") or ids.slug_of(self.id)

    @property
    def name(self) -> str:
        """Display name, falling back to the slug."""
        return self.text("name") or self.slug


@dataclass(frozen=True)
class Regulation(Record):
    """One regulation from regulations_all.json."""

    @property
    def name(self) -> str:
        """Display name, falling back to the id's slug."""
        return self.text("name", "title") or ids.slug_of(self.id)


@dataclass(frozen=True)
class ToolTier(Record):
    """One synthetic tool-access tier. See TOOL_TIERS."""

    @property
    def name(self) -> str:
        """The tier name without its prefix."""
        return ids.slug_of(self.id)


@dataclass(frozen=True)
class Edge:
    """One typed relationship between two canonical node ids."""

    type: str
    source: str
    target: str
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @property
    def rationale(self) -> str:
        """Why this edge exists, where the registry records it."""
        value = self.raw.get("rationale") or self.raw.get("note")
        return str(value) if value else ""

    @property
    def weight(self) -> float:
        """Edge weight, defaulting to 1.0 when unstated or unparseable."""
        try:
            return float(self.raw.get("weight", 1.0))
        except (TypeError, ValueError):
            return 1.0


class KnowledgeGraph:
    """Nodes and typed adjacency for one loaded library snapshot.

    Adjacency is indexed by (type, source) and (type, target) because every
    real query is type-scoped: "which skills does this agent use" is
    AGENT_USES_SKILL out of one node, never "all edges touching it".
    """

    def __init__(
        self,
        *,
        library_version: str,
        agents: Mapping[str, Agent],
        skills: Mapping[str, Skill],
        domains: Mapping[str, Domain],
        regulations: Mapping[str, Regulation],
        tool_tiers: Mapping[str, ToolTier],
        edges: Iterable[Edge],
    ):
        self.library_version = library_version
        self.agents = dict(agents)
        self.skills = dict(skills)
        self.domains = dict(domains)
        self.regulations = dict(regulations)
        self.tool_tiers = dict(tool_tiers)
        self.edges = list(edges)

        self._out: dict[tuple[str, str], list[Edge]] = defaultdict(list)
        self._in: dict[tuple[str, str], list[Edge]] = defaultdict(list)
        for edge in self.edges:
            self._out[(edge.type, edge.source)].append(edge)
            self._in[(edge.type, edge.target)].append(edge)

    @property
    def node_count(self) -> int:
        """Total nodes across all five registries plus the synthetic tiers."""
        return (
            len(self.agents)
            + len(self.skills)
            + len(self.domains)
            + len(self.regulations)
            + len(self.tool_tiers)
        )

    @property
    def edge_count(self) -> int:
        """Total edges loaded."""
        return len(self.edges)

    def has_node(self, node_id: str) -> bool:
        """Whether a canonical id names a node in any registry."""
        canonical_id = ids.canonical(node_id)
        return any(
            canonical_id in table
            for table in (self.agents, self.skills, self.domains, self.regulations, self.tool_tiers)
        )

    def agent(self, ref: str) -> Agent | None:
        """Look up an agent by any reference form."""
        return self.agents.get(ids.agent_id(ref))

    def skill(self, ref: str) -> Skill | None:
        """Look up a skill by any reference form, including a bare slug."""
        return self.skills.get(ids.skill_id(ref))

    def domain(self, ref: str) -> Domain | None:
        """Look up a domain by any reference form."""
        return self.domains.get(ids.domain_id(ref))

    def out_edges(self, node_id: str, edge_type: str) -> list[Edge]:
        """Edges of one type leaving a node."""
        return list(self._out.get((edge_type, ids.canonical(node_id)), ()))

    def in_edges(self, node_id: str, edge_type: str) -> list[Edge]:
        """Edges of one type entering a node."""
        return list(self._in.get((edge_type, ids.canonical(node_id)), ()))

    def neighbours(self, node_id: str, edge_type: str) -> list[str]:
        """Target ids reachable from a node along one edge type."""
        return [edge.target for edge in self.out_edges(node_id, edge_type)]

    def edges_of_type(self, edge_type: str) -> list[Edge]:
        """Every edge of one type."""
        return [edge for edge in self.edges if edge.type == edge_type]

    def edge_type_counts(self) -> dict[str, int]:
        """How many edges of each type, including types with none."""
        counts = {edge_type: 0 for edge_type in EDGE_TYPES}
        for edge in self.edges:
            counts[edge.type] = counts.get(edge.type, 0) + 1
        return counts

    def dangling_endpoints(self) -> dict[str, int]:
        """Referenced-but-absent node ids, mapped to their occurrence count.

        Expected to be non-empty on the real library: 25 occurrences across 21
        distinct ids at library_version 29.97.4, all covered by validate.py's
        two allowlists.
        """
        missing: dict[str, int] = {}
        for edge in self.edges:
            for endpoint in (edge.source, edge.target):
                if not self.has_node(endpoint):
                    missing[endpoint] = missing.get(endpoint, 0) + 1
        return missing
