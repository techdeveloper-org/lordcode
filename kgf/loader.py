"""Build a KnowledgeGraph from the five master registries.

No disk cache, deliberately. Reading all five registries with json.load takes
about 80ms warm, which already beats the 300ms budget by more than 3x, so a
cache would add an invalidation failure class to solve a problem that does not
exist. An earlier draft proposed one keyed on kg_version -- which would not
even have worked, since that field is `1.0.0` in every registry and never
moves. A process-level lru_cache on load_graph() is the whole of it.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

from kgf import ids
from kgf.errors import ProblemLog
from kgf.graph import (
    EDGE_TYPES,
    TOOL_TIERS,
    Agent,
    Domain,
    Edge,
    KnowledgeGraph,
    Regulation,
    Skill,
    ToolTier,
)
from kgf.source import LibrarySource, locate_library

OPTIONAL_AGENT_FIELDS = ("description", "model", "tools", "delegates_math_to")
OPTIONAL_SKILL_FIELDS = ("description", "allowed_tools", "m_sections")


def _entries(payload: Any, *candidate_keys: str) -> Sequence[Mapping[str, Any]]:
    """Pull the record list out of a registry document.

    Each registry wraps its records in a metadata envelope under a key named
    after the collection (`agents`, `skills`, ...), so the list has to be
    located rather than assumed to be the top level.
    """
    if isinstance(payload, list):
        return payload
    if isinstance(payload, Mapping):
        for key in candidate_keys:
            value = payload.get(key)
            if isinstance(value, list):
                return value
        for value in payload.values():
            if isinstance(value, list) and value and isinstance(value[0], Mapping):
                return value
    return ()


def _note_absences(
    log: ProblemLog, record: Mapping[str, Any], node_id: str, fields: Sequence[str]
) -> None:
    """Record an INFO for each absent optional field on one record."""
    for name in fields:
        if name not in record:
            log.info("ABSENT_FIELD", f"{name} not present", source=node_id)


def build_graph(source: LibrarySource, log: ProblemLog | None = None) -> tuple[KnowledgeGraph, ProblemLog]:
    """Read the five registries and assemble the graph.

    Args:
        source: A located library.
        log: Optional existing problem log to append to.

    Returns:
        The graph paired with the problem log describing everything wrong with
        the data it was built from.

    Raises:
        GraphBuildError: If any FATAL problem was found. Measured on the live
            library: none are, so this does not fire in practice -- but a
            registry that loses a `source` field must not silently produce a
            graph with missing edges.
    """
    log = log or ProblemLog()

    agents: dict[str, Agent] = {}
    for record in _entries(source.read_registry("agents_all.json"), "agents"):
        raw_id = record.get("id")
        if not raw_id:
            log.defect("MISSING_ID", "agent record has no id", source=str(record.get("name", "?")))
            continue
        node_id = ids.agent_id(str(raw_id))
        agents[node_id] = Agent(id=node_id, raw=record)
        _note_absences(log, record, node_id, OPTIONAL_AGENT_FIELDS)

    skills: dict[str, Skill] = {}
    for record in _entries(source.read_registry("skills_all.json"), "skills"):
        raw_id = record.get("id")
        if not raw_id:
            log.defect("MISSING_ID", "skill record has no id", source=str(record.get("name", "?")))
            continue
        node_id = ids.skill_id(str(raw_id))
        skills[node_id] = Skill(id=node_id, raw=record)
        _note_absences(log, record, node_id, OPTIONAL_SKILL_FIELDS)

    domains: dict[str, Domain] = {}
    for record in _entries(source.read_registry("domains_all.json"), "domains"):
        # These records carry no `id` at all (0 of 104), so the node id has to
        # be synthesised from the hyphenated slug. Without this, all 3930
        # domain-prefixed edge endpoints dangle.
        slug = record.get("slug") or record.get("name")
        if not slug:
            log.defect("MISSING_ID", "domain record has no slug", source=str(record.get("domain_id", "?")))
            continue
        node_id = ids.domain_id(str(slug))
        domains[node_id] = Domain(id=node_id, raw=record)

    regulations: dict[str, Regulation] = {}
    for record in _entries(source.read_registry("regulations_all.json"), "regulations"):
        raw_id = record.get("id")
        if not raw_id:
            log.defect("MISSING_ID", "regulation record has no id", source=str(record.get("name", "?")))
            continue
        node_id = ids.regulation_id(str(raw_id))
        regulations[node_id] = Regulation(id=node_id, raw=record)

    tool_tiers = {
        tier: ToolTier(id=tier, raw={"synthetic": True, "reason": "HAS_TOOL_ACCESS targets a tier"})
        for tier in TOOL_TIERS
    }

    edges = _build_edges(source, log)

    log.raise_if_fatal()

    graph = KnowledgeGraph(
        library_version=source.library_version,
        agents=agents,
        skills=skills,
        domains=domains,
        regulations=regulations,
        tool_tiers=tool_tiers,
        edges=edges,
    )

    _record_edge_defects(graph, log)
    return graph, log


def _build_edges(source: LibrarySource, log: ProblemLog) -> list[Edge]:
    """Parse edges_all.json, failing only on what prevents adjacency."""
    known_types = set(EDGE_TYPES)
    edges: list[Edge] = []
    seen_ids: set[str] = set()

    for record in _entries(source.read_registry("edges_all.json"), "edges"):
        edge_type = record.get("type")
        raw_source = record.get("source")
        raw_target = record.get("target")

        if not edge_type or edge_type not in known_types:
            log.fatal(
                "UNKNOWN_EDGE_TYPE",
                f"edge type {edge_type!r} is not one of the 14 declared types",
                source=str(record.get("id") or "?"),
            )
            continue
        if not raw_source or not raw_target:
            log.fatal(
                "MISSING_ENDPOINT",
                f"{edge_type} edge missing source or target",
                source=str(record.get("id") or "?"),
            )
            continue

        edge_id = record.get("id")
        if edge_id is None:
            log.defect("NULL_EDGE_ID", f"{edge_type} edge carries no id")
        else:
            text_id = str(edge_id)
            if text_id in seen_ids:
                log.defect("REUSED_EDGE_ID", f"edge id {text_id!r} is not unique")
            seen_ids.add(text_id)

        edges.append(
            Edge(
                type=edge_type,
                source=ids.canonical(str(raw_source)),
                target=ids.canonical(str(raw_target)),
                raw=record,
            )
        )
    return edges


def _record_edge_defects(graph: KnowledgeGraph, log: ProblemLog) -> None:
    """Record dangling endpoints and duplicate triples as DEFECTs."""
    for node_id, count in sorted(graph.dangling_endpoints().items()):
        log.defect("DANGLING_ENDPOINT", f"{count} edge(s) reference absent node", source=node_id)

    seen: dict[tuple[str, str, str], int] = {}
    for edge in graph.edges:
        key = (edge.source, edge.target, edge.type)
        seen[key] = seen.get(key, 0) + 1
    for (edge_source, target, edge_type), count in seen.items():
        if count > 1:
            log.defect(
                "DUPLICATE_TRIPLE",
                f"{count} copies of {edge_type}",
                source=f"{edge_source} -> {target}",
            )


def load_graph(root: Path | str | None = None) -> tuple[KnowledgeGraph, ProblemLog]:
    """Locate the library and build its graph.

    Args:
        root: Explicit library root; see source.locate_library.

    Returns:
        The graph and the problem log for this load.
    """
    return build_graph(locate_library(root))


@lru_cache(maxsize=4)
def cached_graph(root: str | None = None) -> tuple[KnowledgeGraph, ProblemLog]:
    """load_graph memoised for the life of the process.

    Keyed on the root string so a test pointing at a fixture library does not
    collide with the real one. There is no disk cache and no invalidation to
    get wrong -- a fresh process re-reads, which costs about 80ms.
    """
    return load_graph(root)
