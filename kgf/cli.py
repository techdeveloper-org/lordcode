"""Typer CLI for inspecting the knowledge graph.

Every command here runs offline against the library's files, with no API key
and no model call, so the graph can be inspected and validated independently
of whatever consumes it.
"""

from __future__ import annotations

import time
from pathlib import Path

import typer

from kgf import ids
from kgf.closure import build_closure
from kgf.errors import LibraryNotFoundError, Severity
from kgf.loader import load_graph
from kgf.patterns import load_decision_tree
from kgf.roles import classify
from kgf.select import Selector
from kgf.source import locate_library
from kgf.validate import summarize, validate_graph, validate_markdown

app = typer.Typer(help="Inspect and validate claude-global-library's knowledge graph.")

_LIBRARY_OPTION = typer.Option(None, "--library", help="Library root (default: sibling directory).")


def _load(library: Path | None):
    """Load the graph, reporting a missing library as a clean CLI error."""
    try:
        return load_graph(library)
    except LibraryNotFoundError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc


@app.command()
def stats(library: Path = _LIBRARY_OPTION) -> None:
    """Print node, edge and per-edge-type counts, plus load time."""
    started = time.perf_counter()
    graph, _log = _load(library)
    elapsed_ms = (time.perf_counter() - started) * 1000

    typer.echo(f"library_version: {graph.library_version}")
    typer.echo(f"load time:       {elapsed_ms:.0f}ms")
    typer.echo(f"nodes:           {graph.node_count}")
    typer.echo(f"  agents:        {len(graph.agents)}")
    typer.echo(f"  skills:        {len(graph.skills)}")
    typer.echo(f"  domains:       {len(graph.domains)}")
    typer.echo(f"  regulations:   {len(graph.regulations)}")
    typer.echo(f"  tool tiers:    {len(graph.tool_tiers)} (synthetic)")
    typer.echo(f"edges:           {graph.edge_count}")
    for edge_type, count in sorted(graph.edge_type_counts().items(), key=lambda pair: -pair[1]):
        typer.echo(f"  {edge_type:<28} {count}")


@app.command()
def agent(name: str, library: Path = _LIBRARY_OPTION) -> None:
    """Show one agent: its tools, model, and graph-derived relationships."""
    graph, _log = _load(library)
    record = graph.agent(name)
    if record is None:
        typer.secho(f"no agent matching {name!r}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    typer.echo(f"{record.id}")
    typer.echo(f"  name:         {record.name}")
    typer.echo(f"  model:        {record.model or '(unstated)'}")
    typer.echo(f"  math master:  {record.is_math_master}")
    typer.echo(f"  tools:        {', '.join(record.declared_tools) or '(none declared)'}")
    typer.echo(f"  description:  {record.description[:150] or '(none)'}")

    for label, edge_type in (
        ("uses skills", "AGENT_USES_SKILL"),
        ("optional skills", "OPTIONAL_SKILL"),
        ("delegates math to", "DELEGATES_MATH_TO"),
        ("coordinates with", "COORDINATES_WITH"),
        ("belongs to domain", "AGENT_BELONGS_TO_DOMAIN"),
        ("tool access tier", "HAS_TOOL_ACCESS"),
        ("regulated by", "REGULATED_BY"),
    ):
        targets = graph.neighbours(record.id, edge_type)
        if targets:
            typer.echo(f"  {label} ({len(targets)}): {', '.join(sorted(targets)[:8])}")


@app.command()
def skill(name: str, library: Path = _LIBRARY_OPTION) -> None:
    """Show one skill: its allowed tools, M-sections and dependencies."""
    graph, _log = _load(library)
    record = graph.skill(name)
    if record is None:
        typer.secho(f"no skill matching {name!r}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    typer.echo(f"{record.id}")
    typer.echo(f"  name:          {record.name}")
    typer.echo(f"  domain:        {graph.domain_of(record.id) or '(no membership edge)'}")
    typer.echo(f"  allowed tools: {', '.join(record.allowed_tools) or '(none declared)'}")
    typer.echo(f"  M sections:    {len(record.m_sections)}")
    for section in record.m_sections:
        typer.echo(f"    - {section[:100]}")
    typer.echo(f"  description:   {record.description[:150] or '(none)'}")

    for label, edge_type in (
        ("requires", "SKILL_REQUIRES_SKILL"),
        ("similar to", "SKILL_SIMILAR_TO"),
        ("belongs to domain", "SKILL_BELONGS_TO_DOMAIN"),
    ):
        targets = graph.neighbours(record.id, edge_type)
        if targets:
            typer.echo(f"  {label} ({len(targets)}): {', '.join(sorted(targets)[:8])}")


@app.command()
def route(
    task: str,
    library: Path = _LIBRARY_OPTION,
    limit: int = typer.Option(3, "--limit", help="How many ranked matches to show."),
    complexity: str = typer.Option(
        "", "--complexity", help="solo | squad | enterprise -- the D13 answer, used for phase pruning."
    ),
) -> None:
    """Select the agent best suited to a task, showing why."""
    graph, _log = _load(library)
    source = locate_library(library)
    result = Selector(graph, source).select(task, limit=limit)

    typer.echo(f"outcome:    {result.outcome.value}")
    typer.echo(f"considered: {result.considered} edge-named agents")
    typer.echo(f"terms:      {' '.join(result.query_terms)}")

    if not result.matches:
        typer.secho("no candidate scored above zero", fg=typer.colors.YELLOW)
        raise typer.Exit(code=0)

    for rank, match in enumerate(result.matches, start=1):
        typer.echo(
            f"\n{rank}. {match.name}  confidence={match.confidence:.2f}"
            f"  domain={ids.slug_of(match.domain) or '(none)'}"
        )
        typer.echo(
            f"   scores: lexical={match.lexical_score:.2f}"
            f" top_skill={match.top_skill_score:.2f} domain={match.domain_score:.2f}"
        )
        if match.top_skill:
            typer.echo(f"   strongest skill: {ids.slug_of(match.top_skill)}")
        for step in match.edge_path:
            typer.echo(f"   via: {step}")

    best = result.best
    assignment = classify(best.agent)
    typer.echo(f"\nrole: {assignment.role}  ({assignment.reason})")

    tree = load_decision_tree(source)
    pattern_route = tree.route(best.domain, complexity)
    if pattern_route.pattern is not None:
        pattern = pattern_route.pattern
        typer.echo(f"pattern: {pattern.id} {pattern.title}  lead={ids.slug_of(pattern.lead_agent)}")
        typer.echo(
            f"phases: {len(pattern_route.phases)} surviving"
            + (f", {len(pattern_route.pruned)} pruned" if pattern_route.pruned else "")
        )
    else:
        typer.echo("pattern: no D14 branch for this domain")


@app.command()
def closure(
    agent_name: str = typer.Argument(..., help="Agent slug or id."),
    library: Path = _LIBRARY_OPTION,
) -> None:
    """Expand an agent into the full working set the graph says it needs."""
    graph, _log = _load(library)
    result = build_closure(graph, agent_name)
    if result is None:
        typer.secho(f"no agent matching {agent_name!r}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    typer.echo(f"{result.agent}")
    typer.echo(f"  domain:      {ids.slug_of(result.domain) or '(none)'}")
    typer.echo(f"  skills:      {result.size} total (depth reached {result.depth_reached})")
    typer.echo(f"    mandatory ({len(result.mandatory_skills)}): "
               f"{', '.join(ids.slug_of(s) for s in result.mandatory_skills) or '-'}")
    typer.echo(f"    required  ({len(result.required_skills)}): "
               f"{', '.join(ids.slug_of(s) for s in result.required_skills) or '-'}")
    typer.echo(f"    optional  ({len(result.optional_skills)}): "
               f"{', '.join(ids.slug_of(s) for s in result.optional_skills) or '-'}")
    for label, values in (
        ("math", result.math_agents),
        ("coordinates with", result.coordinating_agents),
        ("regulations", result.regulations),
    ):
        if values:
            typer.echo(f"  {label}: {', '.join(ids.slug_of(v) for v in values)}")
    if result.truncated:
        typer.secho(
            f"  truncated {len(result.truncated)} skill(s) at the closure ceiling",
            fg=typer.colors.YELLOW,
        )


@app.command()
def validate(
    library: Path = _LIBRARY_OPTION,
    markdown: bool = typer.Option(
        True, "--markdown/--no-markdown", help="Also parse every SKILL.md and agent.md."
    ),
    show_info: bool = typer.Option(False, "--show-info", help="List INFO problems too."),
) -> None:
    """Validate the graph and, by default, the markdown behind it.

    Exits non-zero only on FATAL. Defects are real data damage that the
    library's own QA gate also tolerates, so reporting them is the job here --
    failing on them would mean kgf could never read the live library.
    """
    graph, log = _load(library)
    validate_graph(graph, log)

    markdown_report = None
    if markdown:
        markdown_report = validate_markdown(locate_library(library))

    typer.echo(summarize(graph, log, markdown_report))

    if show_info:
        counts = log.counts_by_code(Severity.INFO)
        typer.echo("INFO: " + (", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "none"))

    fatals = log.of(Severity.FATAL)
    if fatals:
        typer.secho(f"\n{len(fatals)} FATAL problem(s):", fg=typer.colors.RED, err=True)
        for problem in fatals[:20]:
            typer.secho(f"  {problem}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    typer.secho("\n0 FATAL -- graph is usable.", fg=typer.colors.GREEN)


if __name__ == "__main__":
    app()
