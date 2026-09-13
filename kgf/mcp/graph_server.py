"""kgf-graph: what the library says, and whether it is still the same library.

Read-only throughout. Every tool here is the same call its CLI verb makes, so
`kgf stats` and `kgf_stats` cannot drift into two behaviours -- a test asserts
they agree.

`kgf_replay` lives here rather than in its own server because it answers the
same question as `kgf_fingerprint`: is this still the library that produced a
recorded decision. Placing it beside the fingerprint keeps the user's four-way
split intact instead of growing a fifth server for one verb.

`kgf_validate` is the reason this surface has an output cap at all. M1
catalogues 6,696 EdgeID-pattern failures, 1,051 duplicate triples and 591 null
edge ids; a full inline list is tens of thousands of tokens landing in a
model's context. It returns counts by class, and detail only when asked for one
class with a limit.
"""

from __future__ import annotations

from pathlib import Path

from kgf import ids, manifest as manifest_module
from kgf.errors import Severity
from kgf.mcp.base import READ_ONLY, ServerContext, annotations, make_server, start
from kgf.mcp.responses import envelope, tool_handler
from kgf.validate import validate_graph, validate_markdown

mcp = make_server(
    "kgf-graph",
    instructions=(
        "Read claude-global-library's knowledge graph: counts, one agent, one skill, "
        "validation defects by class, the content fingerprint, and manifest replay."
    ),
)

_context: ServerContext | None = None

MAX_DEFECT_DETAIL = 50
"""Most defects returned for one class when detail is asked for by name."""


def _ctx() -> ServerContext:
    """The process's resolved context, built at launch by start()."""
    global _context
    if _context is None:
        _context = ServerContext()
    return _context


def _build(settings_file: Path | None = None) -> ServerContext:
    """Factory for start(), so a launch failure happens before serving."""
    global _context
    _context = ServerContext(settings_file)
    return _context


@mcp.tool(annotations=annotations(**READ_ONLY))
@tool_handler
def kgf_stats(correlation_id: str = "") -> dict:
    """Node and edge counts for the loaded library, plus per-edge-type totals."""
    context = _ctx()
    graph = context.graph
    return envelope(
        "kgf_stats",
        {
            "library_version": graph.library_version,
            "nodes": graph.node_count,
            "agents": len(graph.agents),
            "skills": len(graph.skills),
            "domains": len(graph.domains),
            "regulations": len(graph.regulations),
            "tool_tiers": len(graph.tool_tiers),
            "edges": graph.edge_count,
            "edge_type_counts": graph.edge_type_counts(),
        },
        library_version=context.library_version,
        fingerprint=context.fingerprint(),
        correlation_id=correlation_id,
    )


@mcp.tool(annotations=annotations(**READ_ONLY))
@tool_handler
def kgf_agent(name: str, correlation_id: str = "") -> dict:
    """One agent: its declared tools, model, and graph-derived relationships."""
    context = _ctx()
    record = context.graph.agent(name)
    if record is None:
        raise KeyError(f"no agent matching {name!r}")

    relationships = {}
    for label, edge_type in (
        ("uses_skills", "AGENT_USES_SKILL"),
        ("optional_skills", "OPTIONAL_SKILL"),
        ("delegates_math_to", "DELEGATES_MATH_TO"),
        ("coordinates_with", "COORDINATES_WITH"),
        ("belongs_to_domain", "AGENT_BELONGS_TO_DOMAIN"),
        ("tool_access_tier", "HAS_TOOL_ACCESS"),
        ("regulated_by", "REGULATED_BY"),
    ):
        targets = context.graph.neighbours(record.id, edge_type)
        if targets:
            relationships[label] = sorted(targets)

    return envelope(
        "kgf_agent",
        {
            "id": record.id,
            "name": record.name,
            "model": record.model,
            "is_math_master": record.is_math_master,
            "declared_tools": list(record.declared_tools),
            "description": record.description,
            "relationships": relationships,
        },
        library_version=context.library_version,
        fingerprint=context.fingerprint(),
        correlation_id=correlation_id,
    )


@mcp.tool(annotations=annotations(**READ_ONLY))
@tool_handler
def kgf_skill(name: str, correlation_id: str = "") -> dict:
    """One skill: its allowed tools, M-sections and dependencies."""
    context = _ctx()
    record = context.graph.skill(name)
    if record is None:
        raise KeyError(f"no skill matching {name!r}")

    relationships = {}
    for label, edge_type in (
        ("requires", "SKILL_REQUIRES_SKILL"),
        ("similar_to", "SKILL_SIMILAR_TO"),
        ("belongs_to_domain", "SKILL_BELONGS_TO_DOMAIN"),
    ):
        targets = context.graph.neighbours(record.id, edge_type)
        if targets:
            relationships[label] = sorted(targets)

    return envelope(
        "kgf_skill",
        {
            "id": record.id,
            "name": record.name,
            "domain": context.graph.domain_of(record.id),
            "allowed_tools": list(record.allowed_tools),
            "m_sections": list(record.m_sections),
            "description": record.description,
            "relationships": relationships,
        },
        library_version=context.library_version,
        fingerprint=context.fingerprint(),
        correlation_id=correlation_id,
    )


@mcp.tool(annotations=annotations(**READ_ONLY))
@tool_handler
def kgf_validate(
    defect_class: str = "",
    limit: int = MAX_DEFECT_DETAIL,
    markdown: bool = False,
    correlation_id: str = "",
) -> dict:
    """Validate the graph, returning counts by class rather than every defect.

    Args:
        defect_class: Return detail for this one DEFECT code. Omit for counts
            only -- the whole point, since the full list is tens of thousands
            of tokens.
        limit: Most detail entries to return, capped at MAX_DEFECT_DETAIL.
        markdown: Also parse every SKILL.md and agent.md. Slow, and the only
            way to see the 18 genuinely malformed files, which are all valid in
            the JSON registries.
        correlation_id: Ties this call's logs to the rest of one compose.
    """
    context = _ctx()
    from kgf.errors import ProblemLog

    log = ProblemLog(problems=list(context.log.problems))
    validate_graph(context.graph, log)

    data = {
        "fatal": [str(problem) for problem in log.fatals],
        "fatal_count": len(log.fatals),
        "defect_counts": log.counts_by_code(Severity.DEFECT),
        "info_counts": log.counts_by_code(Severity.INFO),
    }

    if markdown:
        report = validate_markdown(context.source)
        failed_items = sorted(report.failed.items())
        data["markdown"] = {
            "parsed": report.parsed,
            "total": report.total,
            "failed_count": len(report.failed),
            "bom_stripped_count": len(report.bom_stripped),
            "failed": dict(failed_items[: min(max(limit, 1), MAX_DEFECT_DETAIL)]),
        }

    if defect_class:
        capped = min(max(limit, 1), MAX_DEFECT_DETAIL)
        matching = [
            str(problem)
            for problem in log.of(Severity.DEFECT)
            if problem.code == defect_class
        ]
        data["detail"] = {
            "code": defect_class,
            "total": len(matching),
            "returned": matching[:capped],
            "truncated": len(matching) > capped,
        }

    return envelope(
        "kgf_validate",
        data,
        library_version=context.library_version,
        fingerprint=context.fingerprint(),
        correlation_id=correlation_id,
    )


@mcp.tool(annotations=annotations(**READ_ONLY))
@tool_handler
def kgf_fingerprint(correlation_id: str = "") -> dict:
    """The library's content identity: per-registry sha256 plus its version.

    Content rather than mtime, which is what makes this comparable across the
    four processes of one compose and across machines.
    """
    context = _ctx()
    return envelope(
        "kgf_fingerprint",
        {
            "library_version": context.library_version,
            "library_root": str(context.source.root),
            "registry_digests": [list(item) for item in context.fingerprint()],
        },
        library_version=context.library_version,
        fingerprint=context.fingerprint(),
        correlation_id=correlation_id,
    )


@mcp.tool(annotations=annotations(**READ_ONLY))
@tool_handler
def kgf_replay(fragments: list[dict], correlation_id: str = "") -> dict:
    """Replay one or more manifest fragments against the library as it stands.

    Args:
        fragments: Manifest fragments as returned by the four tools that
            produce them. Several are merged first, which refuses a set whose
            registry digests or correlation ids disagree -- two fragments from
            different composes would otherwise merge into a decision nobody
            made.
        correlation_id: Ties this call's logs to the rest of one compose.

    Makes no model call: selection ranks lexically and context assembly reads
    markdown, so a replay is disk and arithmetic.
    """
    if not fragments:
        raise ValueError("no fragments to replay")

    merged = manifest_module.merge([manifest_module.from_dict(item) for item in fragments])
    report = manifest_module.replay(merged, _ctx().settings.library_root)
    context = _ctx()
    return envelope(
        "kgf_replay",
        {
            "matches": report.matches,
            "differences": list(report.differences),
            "recorded_library_version": report.recorded_library_version,
            "current_library_version": report.current_library_version,
            "summary": report.summary(),
        },
        library_version=context.library_version,
        fingerprint=context.fingerprint(),
        correlation_id=correlation_id,
    )


if __name__ == "__main__":
    start(_build, mcp)
