"""kgf-selection: what work should run, and who should do it.

Read-only. Selection ranks lexically and closure walks edges, so nothing here
makes a model call -- which is what lets a caller ask "who would handle this"
for free before deciding whether to spend anything.

`kgf_topology` lives here rather than in its own server because it sits beside
`kgf_pattern`: both answer what work should run, one from the library's
decision tree and one from kgf's authored phase graph. Placing it here keeps
the user's four-way split rather than growing a fifth server for one verb.

`kgf_route` and `kgf_closure` return manifest fragments. The other three do
not: a role classification and a phase listing are facts about the library, not
decisions about a run.
"""

from __future__ import annotations

from pathlib import Path

from kgf import ids, manifest as manifest_module
from kgf.closure import build_closure
from kgf.mcp.base import READ_ONLY, ServerContext, annotations, make_server, start
from kgf.mcp.responses import envelope, tool_handler
from kgf.patterns import load_decision_tree
from kgf.roles import classify
from kgf.select import Selector
from kgf.topology import check_against_library, load_topology

mcp = make_server(
    "kgf-selection",
    instructions=(
        "Select an agent for a task with its confidence and edge path, expand a skill "
        "closure, classify a role, resolve a pattern, and inspect the phase topology. "
        "No model call."
    ),
)

_context: ServerContext | None = None
_selector: Selector | None = None

MAX_MATCHES = 10
"""Ceiling on ranked matches returned, so a wide query cannot flood a context."""


def _ctx() -> ServerContext:
    """The process's resolved context, built at launch by start()."""
    global _context
    if _context is None:
        _context = ServerContext()
    return _context


def _sel() -> Selector:
    """The process's Selector, built once.

    Construction walks every agent and skill, so building it per call would pay
    that on every request -- which is exactly what the CLI avoids too.
    """
    global _selector
    if _selector is None:
        context = _ctx()
        _selector = Selector(context.graph, context.source)
    return _selector


def _build(settings_file: Path | None = None) -> ServerContext:
    """Factory for start(), so a launch failure happens before serving."""
    global _context, _selector
    _context = ServerContext(settings_file)
    _selector = None
    return _context


@mcp.tool(annotations=annotations(**READ_ONLY))
@tool_handler
def kgf_route(task: str, limit: int = 3, correlation_id: str = "") -> dict:
    """Rank agents for a task, with the evidence that ranked each one.

    Args:
        task: Free-text task description. Prefer the engineered prompt if there
            is one -- that is what the consumer selects on.
        limit: Matches to return, capped at MAX_MATCHES.
        correlation_id: Ties this call's fragment and logs to one compose.

    The outcome matters as much as the match: `low_confidence` means kgf found
    something and does not trust it, which is different from `no_match`, and a
    caller should treat them differently.
    """
    context = _ctx()
    capped = min(max(limit, 1), MAX_MATCHES)
    result = _sel().select(task, limit=capped)

    data = {
        "outcome": result.outcome.value,
        "considered": result.considered,
        "query_terms": list(result.query_terms),
        "disambiguation_considered": list(result.disambiguation_considered),
        "matches": [
            {
                "agent": match.agent,
                "name": match.name,
                "domain": match.domain,
                "confidence": round(match.confidence, 4),
                "lexical_score": round(match.lexical_score, 4),
                "top_skill": match.top_skill,
                "edge_path": list(match.edge_path),
            }
            for match in result.matches
        ],
    }
    if result.best is not None:
        assignment = classify(result.best.agent)
        data["role"] = {"role": assignment.role, "reason": assignment.reason}

    fragment = manifest_module.build(
        task, context.source, result, correlation_id=correlation_id
    )
    return envelope(
        "kgf_route",
        data,
        library_version=context.library_version,
        fingerprint=context.fingerprint(),
        correlation_id=correlation_id,
        manifest_fragment=fragment.to_dict(),
    )


@mcp.tool(annotations=annotations(**READ_ONLY))
@tool_handler
def kgf_closure(agent: str, correlation_id: str = "") -> dict:
    """Expand one agent into the working set the graph asserts it needs.

    Mandatory skills, their transitive requirements, math delegation,
    coordinating peers and regulations. The median agent needs 4 mandatory
    skills; anything that sends one is under-serving it.
    """
    context = _ctx()
    closure = build_closure(context.graph, agent)
    if closure is None:
        raise KeyError(f"no agent matching {agent!r}")

    fragment = manifest_module.build(
        "", context.source, None, closure, forced_agent=True, correlation_id=correlation_id
    )
    return envelope(
        "kgf_closure",
        {
            "agent": closure.agent,
            "domain": closure.domain,
            "mandatory_skills": list(closure.mandatory_skills),
            "required_skills": list(closure.required_skills),
            "optional_skills": list(closure.optional_skills),
            "math_agents": list(closure.math_agents),
            "coordinating_agents": list(closure.coordinating_agents),
            "regulations": list(closure.regulations),
            "truncated": list(closure.truncated),
            "depth_reached": closure.depth_reached,
            "all_skills": list(closure.all_skills),
        },
        library_version=context.library_version,
        fingerprint=context.fingerprint(),
        correlation_id=correlation_id,
        manifest_fragment=fragment.to_dict(),
    )


@mcp.tool(annotations=annotations(**READ_ONLY))
@tool_handler
def kgf_role(agent: str, correlation_id: str = "") -> dict:
    """Classify one agent as reasoner or primary_coder, with the rule that decided.

    The role is COMPUTED, not read: 0 of the library's 1562 documents declare
    one, which is the defect ADR-6 exists to work around. The reason is
    returned so a surprising classification can be traced to its rule rather
    than guessed at.
    """
    context = _ctx()
    record = context.graph.agent(agent)
    if record is None:
        raise KeyError(f"no agent matching {agent!r}")
    assignment = classify(record.id)
    return envelope(
        "kgf_role",
        {"agent": record.id, "role": assignment.role, "reason": assignment.reason},
        library_version=context.library_version,
        fingerprint=context.fingerprint(),
        correlation_id=correlation_id,
    )


@mcp.tool(annotations=annotations(**READ_ONLY))
@tool_handler
def kgf_pattern(domain: str, complexity: str = "", correlation_id: str = "") -> dict:
    """Resolve the library's decision tree to a pattern and its phase set.

    Args:
        domain: Domain id or slug to route.
        complexity: solo | squad | enterprise -- the D13 answer. Supplying it
            matters: D13::B2 alone prunes 8 phases, so omitting it yields an
            over-broad set.
        correlation_id: Ties this call's logs to one compose.
    """
    context = _ctx()
    tree = load_decision_tree(context.source)
    route = tree.route(ids.domain_id(domain), complexity)
    data = {
        "domain": ids.domain_id(domain),
        "complexity": complexity,
        "phases": [phase.id for phase in route.phases],
        "pruned": list(route.pruned),
    }
    if route.pattern is not None:
        data["pattern"] = {
            "id": route.pattern.id,
            "title": route.pattern.title,
            "lead_agent": route.pattern.lead_agent,
            "lead_domain": route.pattern.lead_domain,
        }
    return envelope(
        "kgf_pattern",
        data,
        library_version=context.library_version,
        fingerprint=context.fingerprint(),
        correlation_id=correlation_id,
    )


@mcp.tool(annotations=annotations(**READ_ONLY))
@tool_handler
def kgf_topology(pruned: list[str] | None = None, validate: bool = False, correlation_id: str = "") -> dict:
    """kgf's authored 44-phase graph as execution levels.

    Args:
        pruned: Phase ids to prune, e.g. a Solo run's A.6/A.6.1/H. Pruning
            SPLICES rather than drops -- a pruned node's dependents inherit its
            dependencies -- because merely removing it floated the security
            audit to level 0 in testing.
        validate: Also check every authored phase against the library's
            phases.json, in both directions.
        correlation_id: Ties this call's logs to one compose.
    """
    context = _ctx()
    topology = load_topology()
    removed = tuple(pruned or ())
    unknown = [item for item in removed if item not in topology.phases]
    if unknown:
        raise KeyError(f"not a phase id: {', '.join(unknown)}")

    levels = topology.levels(removed)
    data = {
        "phase_count": len(topology.phases),
        "pruned": list(removed),
        "levels": levels,
        "level_count": len(levels),
        "gates": list(topology.gates()),
    }
    if validate:
        report = check_against_library(topology, context.source)
        data["validation"] = {
            "ok": report.ok,
            "authored_count": report.authored_count,
            "library_count": report.library_count,
            "missing_from_library": list(report.missing_from_library),
            "missing_from_topology": list(report.missing_from_topology),
        }
    return envelope(
        "kgf_topology",
        data,
        library_version=context.library_version,
        fingerprint=context.fingerprint(),
        correlation_id=correlation_id,
    )


if __name__ == "__main__":
    start(_build, mcp)
