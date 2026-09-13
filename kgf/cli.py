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
from kgf.context import DEFAULT_TOKEN_BUDGET, Intent, assemble_context
from kgf.errors import LibraryNotFoundError, ProblemLog, Severity
from kgf import manifest as manifest_module
from kgf.loader import load_graph
from kgf.patterns import load_decision_tree
from kgf.roles import classify
from kgf.select import Selector
from kgf.source import locate_library
from kgf.tools import grant_for
from kgf.topology import (
    LIBRARY_PRECEDENCE,
    check_against_library,
    describe,
    load_topology,
    seed_chain_links,
    unsatisfied_library_precedence,
    unsatisfied_seed_chain,
)
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
    manifest_path: Path = typer.Option(
        None, "--manifest", help="Write an ADR-7 run manifest here for later replay."
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

    if manifest_path is not None:
        written = manifest_module.build(task, source, result).write(manifest_path)
        typer.echo(f"manifest: {written}")


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
def tools(
    agent_name: str = typer.Argument(..., help="Agent slug or id."),
    library: Path = _LIBRARY_OPTION,
    with_closure: bool = typer.Option(
        True, "--closure/--no-closure", help="Apply closure-wide narrowing."
    ),
) -> None:
    """Show an agent's effective tool grant, how it was derived, and any defects."""
    graph, _log = _load(library)
    record = graph.agent(agent_name)
    if record is None:
        typer.secho(f"no agent matching {agent_name!r}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    agent_closure = build_closure(graph, record.id) if with_closure else None
    grant = grant_for(graph, record.id, closure=agent_closure)

    typer.echo(f"{grant.agent}")
    typer.echo(f"  ceiling (agent `tools`): {', '.join(sorted(grant.ceiling)) or '(none)'}")
    typer.echo(f"  tiers:                   {', '.join(grant.tiers) or '(none)'}")
    typer.echo(f"  effective grant:         {', '.join(grant.sorted_tools()) or '(empty)'}")
    withheld = sorted(grant.ceiling - grant.tools)
    if withheld:
        typer.echo(f"  withheld by narrowing:   {', '.join(withheld)}")
    for step in grant.narrowed_by:
        typer.echo(f"  narrowed by: {step}")
    for defect in grant.defects:
        typer.secho(f"  ! {defect}", fg=typer.colors.YELLOW)

    typer.echo("")
    typer.echo("Sandbox posture for this grant (both flags default to False):")
    typer.echo(f"  Bash granted:     {grant.permits('Bash')}  -- requires allow_bash=True to run")
    typer.echo(f"  network granted:  {grant.permits('WebFetch') or grant.permits('WebSearch')}"
               f"  -- requires allow_network=True to run")


@app.command()
def context(
    task: str,
    library: Path = _LIBRARY_OPTION,
    agent_name: str = typer.Option(
        "", "--agent", help="Force an agent instead of selecting one for the task."
    ),
    intent: str = typer.Option(
        Intent.IMPLEMENT.value, "--intent", help="implement | design | review."
    ),
    budget: int = typer.Option(DEFAULT_TOKEN_BUDGET, "--budget", help="Token ceiling."),
    show_text: bool = typer.Option(False, "--show-text", help="Print the assembled context."),
    manifest_path: Path = typer.Option(
        None, "--manifest", help="Write an ADR-7 run manifest here for later replay."
    ),
) -> None:
    """Assemble budgeted prompt context for a task."""
    graph, _log = _load(library)
    source = locate_library(library)

    try:
        resolved_intent = Intent(intent.strip().lower())
    except ValueError:
        typer.secho(
            f"unknown intent {intent!r}; expected one of "
            f"{', '.join(item.value for item in Intent)}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)

    if agent_name:
        chosen = agent_name
        selection = None
    else:
        result = Selector(graph, source).select(task, limit=1)
        selection = result
        if result.best is None:
            typer.secho("no agent matched this task", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        chosen = result.best.agent
        typer.echo(
            f"selected {result.best.name} ({result.outcome.value}, "
            f"confidence {result.best.confidence:.2f})"
        )

    agent_closure = build_closure(graph, chosen)
    if agent_closure is None:
        typer.secho(f"no agent matching {chosen!r}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    assembled = assemble_context(
        graph, source, agent_closure, intent=resolved_intent, budget_tokens=budget
    )
    typer.echo(assembled.summary())

    for item in assembled.included:
        typer.echo(f"  + [{item.kind}] {item.tokens:>4} tok  {ids.slug_of(item.entity)} :: {item.heading}")

    if assembled.defects:
        for defect in assembled.defects:
            typer.secho(f"  ! {defect}", fg=typer.colors.YELLOW)

    if not assembled.within_budget:
        typer.secho("assembled context exceeds its budget", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    if show_text:
        typer.echo("\n" + assembled.text)

    if manifest_path is not None:
        written = manifest_module.build(
            task,
            source,
            selection,
            agent_closure,
            assembled,
            intent=resolved_intent.value,
            budget_tokens=budget,
            forced_agent=selection is None,
        ).write(manifest_path)
        typer.echo(f"manifest: {written}")


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


@app.command()
def topology(
    library: Path = _LIBRARY_OPTION,
    validate: bool = typer.Option(
        False, "--validate", help="Check the authored phases against the library's phases.json."
    ),
    prune: str = typer.Option(
        "", "--prune", help="Comma-separated phase ids to prune, e.g. phase:A.6,phase:H."
    ),
    show_rationale: bool = typer.Option(
        False, "--show-rationale", help="Print each phase's provenance and rationale."
    ),
) -> None:
    """Print kgf's authored phase topology, or validate it against the library.

    The topology is kgf's own data (ADR-5): the library declares 44 phases and
    no dependency between any two of them, so this graph is authored and must
    be re-checked against phases.json on every library bump. --validate is
    that check, and it exits non-zero when the two disagree.
    """
    topo = load_topology()
    pruned = tuple(item.strip() for item in prune.split(",") if item.strip())

    unknown = tuple(item for item in pruned if item not in topo.phases)
    if unknown:
        typer.secho(f"not a phase id: {', '.join(unknown)}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)

    if validate:
        source = locate_library(library)
        log = ProblemLog()
        report = check_against_library(topo, source, log)
        unsatisfied = unsatisfied_library_precedence(topo)
        seed_links = seed_chain_links(topo)
        seed_failures = unsatisfied_seed_chain(topo)

        typer.echo(f"library_version   {report.library_version}")
        typer.echo(f"authored phases   {report.authored_count}")
        typer.echo(f"library phases    {report.library_count}")
        typer.echo(f"levels            {report.level_count}")
        typer.echo(
            f"traversal.md#6.3  {len(LIBRARY_PRECEDENCE) - len(unsatisfied)}"
            f"/{len(LIBRARY_PRECEDENCE)} MUST constraints satisfied"
        )
        typer.echo(
            f"seeded order      {len(seed_links) - len(seed_failures)}"
            f"/{len(seed_links)} links satisfied"
        )

        for problem in log.problems:
            colour = typer.colors.RED if problem.severity is Severity.FATAL else typer.colors.YELLOW
            typer.secho(f"  {problem}", fg=colour, err=True)
        for before, after in unsatisfied + seed_failures:
            typer.secho(f"  FATAL TOPOLOGY_PRECEDENCE: {before} must precede {after}",
                        fg=typer.colors.RED, err=True)

        if log.fatals or unsatisfied or seed_failures or not report.ok:
            raise typer.Exit(code=1)
        typer.echo("")
        typer.secho("topology agrees with the library.", fg=typer.colors.GREEN)
        return

    typer.echo(describe(topo, pruned))
    if pruned:
        typer.echo("")
        typer.echo(f"pruned {len(pruned)}: {', '.join(pruned)}")
    if show_rationale:
        typer.echo("")
        for phase_id, phase in topo.phases.items():
            if phase_id in pruned:
                continue
            typer.echo(f"{phase_id}  [{phase.provenance}]")
            typer.echo(f"    {phase.rationale}")


@app.command()
def replay(
    manifest_file: Path = typer.Argument(..., help="A manifest written by --manifest."),
    library: Path = _LIBRARY_OPTION,
) -> None:
    """Re-derive a recorded run from the current library and report what changed.

    ADR-7. Makes no model call: selection ranks lexically and context assembly
    reads markdown, so a replay is disk and arithmetic. Exits non-zero when
    anything differs, which is what makes it usable as a drift gate rather than
    something a human has to read and compare by eye.
    """
    if not manifest_file.is_file():
        typer.secho(f"no manifest at {manifest_file}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)

    try:
        recorded = manifest_module.load(manifest_file)
    except (ValueError, TypeError) as exc:
        typer.secho(f"{manifest_file} is not a readable manifest: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc

    typer.echo(f"manifest:        {manifest_file}")
    typer.echo(f"written:         {recorded.created_at}")
    typer.echo(f"schema:          v{recorded.manifest_version}")
    typer.echo(f"task:            {recorded.task[:80]}")
    typer.echo(f"recorded agent:  {recorded.agent or '(none)'} ({recorded.outcome or 'n/a'})")

    try:
        report = manifest_module.replay(recorded, library)
    except LibraryNotFoundError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc

    typer.echo("")
    if report.matches:
        typer.secho(report.summary(), fg=typer.colors.GREEN)
        return
    typer.secho(report.summary(), fg=typer.colors.YELLOW, err=True)
    raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
