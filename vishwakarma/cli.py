"""Typer CLI entrypoint for Vishwakarma."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from vishwakarma.config import ConfigError, load_config
from vishwakarma.engine.api_contract import (
    JOINT_VALIDATION_HEADING,
    _hld_describes_api_surface,
    api_contract_path_for,
    generate_api_contract,
    run_full_stack_reconciliation,
    run_joint_validation,
)
from vishwakarma.engine.documentation import (
    diagram_path_for,
    generate_docs,
    generate_traceability,
    list_source_files,
)
from vishwakarma.engine.figma_design import (
    design_tokens_path_for,
    extract_design_tokens,
    generate_css_from_figma,
    has_figma_token,
)
from vishwakarma.engine.generate import GenerationError
from vishwakarma.engine.git_ops import (
    commit_generated_code,
    ensure_git_repo,
    has_github_remote,
    push_and_create_pr,
)
from vishwakarma.engine.jira_sprint import create_sprint_plan, has_jira_credentials, jira_tickets_path_for
from vishwakarma.engine.orchestrator import run_task
from vishwakarma.engine.sdlc import generate_hld, generate_srs, hld_path_for, srs_path_for
from vishwakarma.llm_client import LLMClient
from vishwakarma.logging_config import configure_logging
from vishwakarma.plugins import load_all_agents, load_all_skills
from vishwakarma.router import Router

app = typer.Typer(help="Vishwakarma: local code-gen + auto-test tool on Groq's free API.")
sdlc_app = typer.Typer(help="Full-SDLC mode: raw idea -> SRS.md -> HLD.md -> implement.")
app.add_typer(sdlc_app, name="sdlc")


def _echo_event(event: dict) -> None:
    """Live progress echo for the CLI -- shows which provider/model is called for what."""
    event_type = event.get("type")
    if event_type == "call_start":
        typer.echo(f"  -> [{event['role']}] {event['provider']}/{event['model']}: {event['purpose']}")
    elif event_type == "call_fallback":
        typer.secho(
            f"     {event['provider']}/{event['model']} unavailable ({event['reason']}), falling back...",
            fg=typer.colors.YELLOW,
        )
    elif event_type == "token":
        typer.echo(event["content"], nl=False)
    elif event_type == "call_end":
        typer.echo(f"\n     ({event['duration_ms']}ms)")
    elif event_type == "language_detected":
        typer.echo(f"Detected language: {event['language']}")
    elif event_type == "complexity_classified":
        typer.echo(f"Complexity: {event['complexity']}")
    elif event_type == "heal_attempt_start":
        typer.echo(f"Self-heal attempt {event['attempt']}...")
    elif event_type == "heal_attempt_parse_failed":
        typer.secho(
            f"  Self-heal attempt {event['attempt']}: fix response could not be parsed -- {event['reason']}",
            fg=typer.colors.YELLOW,
        )
    elif event_type == "agent_spawned":
        typer.echo(f"  [agent] spawned {event['persona']} agent_id={event['agent_id'][:8]} pid={event['pid']}")
    elif event_type == "agent_completed":
        typer.echo(f"  [agent] agent_id={event['agent_id'][:8]} finished in {event['duration_ms']}ms")
    elif event_type == "kg_route_resolved":
        typer.echo(f"  [kg] routed to [{event['lead_agent']}] via {event['pattern_id']} ({event['domain']})")
    elif event_type == "kg_route_unavailable":
        typer.echo(f"  [kg] routing unavailable: {event['reason']}")
    elif event_type == "diagram_source":
        typer.echo(f"  [docs] {event['diagram_type']} diagram source: {event['source']}")
    elif event_type == "diagram_generated":
        typer.echo(f"  [docs] {event['diagram_type']} diagram generated")
    elif event_type == "diagram_generation_failed":
        typer.secho(
            f"  [docs] {event['diagram_type']} diagram failed: {event['reason']} -- skipping, others continue",
            fg=typer.colors.YELLOW,
        )
    elif event_type == "traceability_generated":
        typer.echo("  [docs] traceability matrix generated")
    elif event_type == "api_contract_skipped":
        typer.echo(f"  [api] skipped: {event['reason']}")
    elif event_type == "api_contract_generated":
        typer.echo("  [api] OpenAPI contract generated")
    elif event_type == "joint_validation_verdict":
        typer.echo(
            f"  [api] joint validation: {'APPROVED' if event['approved'] else 'REJECTED'} -- {event['reason']}"
        )
    elif event_type == "git_repo_initialized":
        typer.echo("  [git] initialized a new repo")
    elif event_type == "git_repo_already_exists":
        typer.echo("  [git] repo already exists")
    elif event_type == "git_commit_created":
        typer.echo(f"  [git] commit {event.get('commit_hash', '?')} created")
    elif event_type == "git_commit_skipped":
        typer.echo("  [git] nothing to commit")
    elif event_type == "git_branch_pushed":
        typer.echo(f"  [git] branch '{event['branch']}' pushed")
    elif event_type == "pr_created":
        typer.echo(f"  [git] PR created: {event.get('pr_url', '?')}")
    elif event_type == "figma_design_tokens_extracted":
        typer.echo(f"  [figma] design tokens extracted for {event['file_key']}")
    elif event_type == "figma_accessibility_scan_failed":
        typer.secho(f"  [figma] accessibility scan failed: {event['reason']} -- tokens still saved", fg=typer.colors.YELLOW)
    elif event_type == "figma_css_generated":
        typer.echo(f"  [figma] CSS generated for component '{event['component_name']}'")
    elif event_type == "full_stack_reconciliation_verdict":
        typer.echo(
            f"  [reconcile] {'APPROVED' if event['approved'] else 'REJECTED'} -- {event['reason']}"
        )
    elif event_type == "jira_epic_created":
        typer.echo(f"  [jira] epic {event['epic_key']} created")
    elif event_type == "jira_story_created":
        typer.echo(f"  [jira] story {event['issue_key']} created for {event['fr_id']}")
    elif event_type == "jira_epic_link_failed":
        typer.secho(f"  [jira] {event['issue_key']} not linked to epic: {event['reason']}", fg=typer.colors.YELLOW)
    elif event_type == "jira_sprint_created":
        typer.echo(f"  [jira] sprint {event['sprint_id']} ('{event['name']}') created")
    elif event_type == "jira_issues_moved_to_sprint":
        typer.echo(f"  [jira] {len(event['issue_keys'])} issue(s) moved to sprint {event['sprint_id']}")
    elif event_type == "file_manifest_planned":
        typer.echo(f"  [parallel] file manifest planned: {event['file_count']} files")
    elif event_type == "parallel_generation_group_completed":
        typer.echo(f"  [parallel] group '{event['label']}' completed: {event['file_count']} file(s)")
    elif event_type == "dependency_graph_computed":
        typer.echo(f"  [parallel] dependency graph computed: {event['edge_count']} edge(s)")
    elif event_type == "generation_wave_completed":
        typer.echo(f"  [parallel] wave {event['wave']} completed ({event['group_count']} group(s))")
    elif event_type == "dependency_cluster_exceeds_group_size":
        typer.secho(
            f"  [parallel] dependency cluster of {event['cluster_size']} file(s) exceeds the target group size: {event['paths']}",
            fg=typer.colors.YELLOW,
        )
    elif event_type == "dependency_cycle_fallback":
        typer.secho("  [parallel] cross-group dependency cycle detected -- falling back to wave 0", fg=typer.colors.YELLOW)
    elif event_type == "parallel_group_count_exceeded_target":
        typer.secho(
            f"  [parallel] {event['group_count']} groups exceeds the target of {event['max_parallel_groups']}",
            fg=typer.colors.YELLOW,
        )


def _build_pipeline() -> tuple[Router, LLMClient]:
    """Load config and construct the router + multi-provider client for one CLI run."""
    config = load_config()
    client = LLMClient(config.providers)
    router = Router(config.models, client)
    router.validate_startup()
    return router, client


@app.command()
def run(
    task: str = typer.Argument(..., help="Free-text description of what to build."),
    lang: str | None = typer.Option(None, "--lang", help="Force a target stack; auto-detected from the task if omitted."),
    workdir: Path = typer.Option(Path("./vishwakarma-output"), "--workdir", help="Directory to write generated files into."),
    no_heal: bool = typer.Option(False, "--no-heal", help="Disable the self-heal retry loop on test failure."),
    max_attempts: int = typer.Option(3, "--max-attempts", help="Maximum self-heal retries."),
    rag: bool = typer.Option(False, "--rag", help="Search an existing project directory for relevant context."),
    project_dir: Path | None = typer.Option(None, "--project-dir", help="Existing project root to search when --rag is set."),
    skill: str | None = typer.Option(None, "--skill", help="Force a specific skill by name instead of auto-matching."),
    agent: str | None = typer.Option(None, "--agent", help="Force a specific subagent persona by name."),
) -> None:
    """Generate code + tests for TASK, run them, and self-heal on failure."""
    configure_logging()
    try:
        router, client = _build_pipeline()
    except ConfigError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    workdir.mkdir(parents=True, exist_ok=True)
    result = run_task(
        task,
        workdir,
        router,
        client,
        language=lang,
        use_rag=rag,
        project_dir=project_dir,
        skill_name=skill,
        agent_name=agent,
        max_heal_attempts=0 if no_heal else max_attempts,
        on_event=_echo_event,
    )

    typer.echo(f"\nEngineered prompt:\n{result.engineered_prompt}\n")
    typer.echo(f"Language: {result.language} | Complexity: {result.complexity}")
    if result.plan:
        typer.echo(f"\nImplementation plan:\n{result.plan}\n")
    if result.skill_used:
        typer.echo(f"Skill used: {result.skill_used}")
    if result.agent_used:
        typer.echo(f"Agent persona used: {result.agent_used}")

    for record in result.attempts:
        status = "PASSED" if record.result.passed else "FAILED"
        typer.echo(f"Attempt {record.attempt}: {status}")
        if not record.result.passed:
            typer.echo(record.result.stderr)

    typer.echo("\nFiles written:")
    for file_spec in result.final_files:
        typer.echo(f"  {workdir / file_spec.path}")

    if result.passed:
        typer.secho("\nAll tests passed.", fg=typer.colors.GREEN)
    else:
        typer.secho("\nTests still failing after self-heal attempts.", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@app.command()
def skills() -> None:
    """List every auto-matchable skill (Vishwakarma's own + the global library)."""
    for skill in load_all_skills():
        typer.echo(f"{skill.name}: {skill.description}")


@app.command()
def agents() -> None:
    """List every available subagent persona (Vishwakarma's own + the global library)."""
    for agent in load_all_agents():
        typer.echo(f"{agent.name} [{agent.role}]: {agent.description}")


def _read_required_artifact(path: Path, label: str) -> str:
    """Read an SDLC artifact, failing clearly if it's missing or blank.

    A blank/whitespace-only file (e.g. from a mangled manual edit) is
    treated the same as missing -- folding it into a later stage's context
    silently would degrade that stage with no diagnostic.
    """
    if not path.exists():
        typer.secho(f"{label} not found at {path} -- run the earlier sdlc step first.", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    content = path.read_text(encoding="utf-8")
    if not content.strip():
        typer.secho(f"{label} at {path} is empty -- regenerate it before continuing.", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    return content


@sdlc_app.command("srs")
def sdlc_srs(
    idea: str = typer.Argument(..., help="Raw, free-text description of what you want to build."),
    workdir: Path = typer.Option(Path("./vishwakarma-output"), "--workdir", help="Project directory."),
) -> None:
    """Phase 0: turn a raw idea into docs/phase-0-requirements/SRS.md."""
    configure_logging()
    try:
        router, client = _build_pipeline()
    except ConfigError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    workdir.mkdir(parents=True, exist_ok=True)
    try:
        srs = generate_srs(idea, workdir, router, client, on_event=_echo_event)
    except GenerationError as exc:
        typer.secho(f"\n{exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    typer.echo(f"\n{srs}")
    typer.secho(f"\nWritten to {srs_path_for(workdir)} -- edit it directly, then run `sdlc hld`.", fg=typer.colors.GREEN)


@sdlc_app.command("hld")
def sdlc_hld(
    workdir: Path = typer.Option(Path("./vishwakarma-output"), "--workdir", help="Project directory."),
    task: str = typer.Option("", "--task", help="Short description of the concrete task/stack, if different from the SRS purpose."),
) -> None:
    """Phase 1: turn an approved SRS.md into docs/phase-1-architecture/HLD.md."""
    configure_logging()
    try:
        router, client = _build_pipeline()
    except ConfigError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    srs = _read_required_artifact(srs_path_for(workdir), "SRS.md")
    try:
        hld = generate_hld(srs, task or srs, workdir, router, client, on_event=_echo_event)
    except GenerationError as exc:
        typer.secho(f"\n{exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    typer.echo(f"\n{hld}")
    typer.secho(f"\nWritten to {hld_path_for(workdir)} -- edit it directly, then run `sdlc implement`.", fg=typer.colors.GREEN)


@sdlc_app.command("implement")
def sdlc_implement(
    task: str = typer.Argument(..., help="Free-text description of what to build."),
    workdir: Path = typer.Option(Path("./vishwakarma-output"), "--workdir", help="Project directory."),
    max_attempts: int = typer.Option(3, "--max-attempts", help="Maximum self-heal retries."),
) -> None:
    """Phase 2+: implement TASK using the approved SRS.md + HLD.md as context."""
    configure_logging()
    try:
        router, client = _build_pipeline()
    except ConfigError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    srs = _read_required_artifact(srs_path_for(workdir), "SRS.md")
    hld = _read_required_artifact(hld_path_for(workdir), "HLD.md")
    # run_task() has no separate "external context" parameter, and Milestone
    # 1 keeps it unmodified -- so the approved SRS+HLD are prepended onto the
    # task text itself. This is not a hack: run_task()'s own first step
    # (engineer_context -> engineer_prompt) exists precisely to digest a
    # larger raw request into a concise, structured prompt, so feeding it a
    # bigger raw request (task + SRS + HLD) is exactly the input shape that
    # step is designed to compress -- downstream calls still see only the
    # compact engineered prompt, not the raw SRS/HLD text.
    task_with_sdlc_context = (
        f"{task}\n\nApproved SRS (authoritative requirements):\n{srs}\n\n"
        f"Approved HLD (authoritative design):\n{hld}"
    )

    result = run_task(
        task_with_sdlc_context,
        workdir,
        router,
        client,
        max_heal_attempts=max_attempts,
        on_event=_echo_event,
    )
    typer.echo(f"\nEngineered prompt:\n{result.engineered_prompt}\n")
    typer.echo(f"Language: {result.language} | Complexity: {result.complexity}")
    if result.plan:
        typer.echo(f"\nImplementation plan:\n{result.plan}\n")

    for record in result.attempts:
        status = "PASSED" if record.result.passed else "FAILED"
        typer.echo(f"Attempt {record.attempt}: {status}")
        if not record.result.passed:
            typer.echo(record.result.stderr)

    typer.echo("\nFiles written:")
    for file_spec in result.final_files:
        typer.echo(f"  {workdir / file_spec.path}")

    if result.passed:
        typer.secho("\nAll tests passed.", fg=typer.colors.GREEN)
    else:
        typer.secho("\nTests still failing after self-heal attempts.", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@sdlc_app.command("docs")
def sdlc_docs(
    workdir: Path = typer.Option(Path("./vishwakarma-output"), "--workdir", help="Project directory."),
) -> None:
    """Phase 5: generate Mermaid UML diagrams + an SRS traceability matrix."""
    configure_logging()
    try:
        router, client = _build_pipeline()
    except ConfigError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    srs = _read_required_artifact(srs_path_for(workdir), "SRS.md")
    hld = _read_required_artifact(hld_path_for(workdir), "HLD.md")

    file_list = list_source_files(workdir)
    if not file_list:
        typer.secho(
            f"No generated code found in {workdir} -- run `sdlc implement` first.", fg=typer.colors.RED
        )
        raise typer.Exit(code=1)

    diagrams = generate_docs(srs, hld, workdir, router, client, on_event=_echo_event)
    diagram_types = ["class", "component", "sequence", "usecase"]
    typer.echo(f"\n{len(diagrams)}/{len(diagram_types)} diagrams generated:")
    for diagram_type in diagram_types:
        status = "OK" if diagram_type in diagrams else "FAILED (see warning above)"
        typer.echo(f"  {diagram_type}: {status} -- {diagram_path_for(workdir, diagram_type)}")

    try:
        generate_traceability(srs, file_list, workdir, router, client, on_event=_echo_event)
    except GenerationError as exc:
        typer.secho(f"\n{exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    typer.secho(f"\nTraceability matrix appended to {srs_path_for(workdir)}.", fg=typer.colors.GREEN)


@sdlc_app.command("api")
def sdlc_api(
    workdir: Path = typer.Option(Path("./vishwakarma-output"), "--workdir", help="Project directory."),
) -> None:
    """Phase 1.5: generate an OpenAPI contract from the HLD, if it describes an API, and cross-validate."""
    configure_logging()
    try:
        router, client = _build_pipeline()
    except ConfigError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    srs = _read_required_artifact(srs_path_for(workdir), "SRS.md")
    hld = _read_required_artifact(hld_path_for(workdir), "HLD.md")

    try:
        spec = generate_api_contract(srs, hld, workdir, router, client, on_event=_echo_event)
    except GenerationError as exc:
        typer.secho(f"\n{exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    if spec is None:
        typer.secho(
            "\nNo API surface detected in HLD.md -- skipping OpenAPI generation and joint validation.",
            fg=typer.colors.YELLOW,
        )
        return

    typer.echo(f"\n{spec}")
    typer.secho(f"\nWritten to {api_contract_path_for(workdir)}.", fg=typer.colors.GREEN)

    try:
        run_joint_validation(srs, hld, spec, workdir, router, client, on_event=_echo_event)
    except GenerationError as exc:
        typer.secho(f"\n{exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    typer.secho(f"\nJoint validation appended to {hld_path_for(workdir)}.", fg=typer.colors.GREEN)


@sdlc_app.command("git")
def sdlc_git(
    workdir: Path = typer.Option(Path("./vishwakarma-output"), "--workdir", help="Project directory."),
    message: str = typer.Option("", "--message", help="Commit message (default: 'Generated by Vishwakarma')."),
    pr: bool = typer.Option(False, "--pr", help="Also push a branch and open a GitHub PR (requires an existing GitHub remote)."),
    branch: str = typer.Option("", "--branch", help="Branch name to create/push (required with --pr)."),
    pr_title: str = typer.Option("", "--pr-title", help="PR title (required with --pr)."),
    pr_body: str = typer.Option("", "--pr-body", help="PR body."),
    base: str = typer.Option("main", "--base", help="Base branch to branch off of / open the PR against."),
) -> None:
    """Commit generated code, and optionally push a branch + open a GitHub PR."""
    configure_logging()
    workdir.mkdir(parents=True, exist_ok=True)

    try:
        ensure_git_repo(workdir, on_event=_echo_event)
    except GenerationError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    try:
        commit = commit_generated_code(workdir, message or "Generated by Vishwakarma", on_event=_echo_event)
    except GenerationError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    if commit is None:
        typer.echo("Nothing to commit.")
    else:
        typer.secho(f"Committed {commit.get('commit_hash', '?')}.", fg=typer.colors.GREEN)

    if not pr:
        return

    if not branch or not pr_title:
        typer.secho("--branch and --pr-title are required with --pr.", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    if not has_github_remote(workdir):
        typer.secho(
            "No GitHub remote configured for this workdir -- skipping PR; commit above still succeeded.",
            fg=typer.colors.YELLOW,
        )
        return

    try:
        pr_data = push_and_create_pr(workdir, branch, pr_title, pr_body, base, on_event=_echo_event)
    except GenerationError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    typer.secho(f"PR created: {pr_data.get('pr_url', '?')}", fg=typer.colors.GREEN)


@sdlc_app.command("figma")
def sdlc_figma(
    workdir: Path = typer.Option(Path("./vishwakarma-output"), "--workdir", help="Project directory."),
    file_key: str = typer.Option(..., "--file-key", help="Figma file key (from the file's URL)."),
    node_id: str = typer.Option("", "--node-id", help="Node ID to generate CSS for (requires --component-name)."),
    component_name: str = typer.Option("", "--component-name", help="CSS class name (requires --node-id)."),
) -> None:
    """Extract design tokens + an accessibility scan from an existing Figma file."""
    configure_logging()
    workdir.mkdir(parents=True, exist_ok=True)

    if not has_figma_token():
        typer.secho("FIGMA_ACCESS_TOKEN is not set -- cannot call the Figma MCP server.", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    if bool(node_id) != bool(component_name):
        typer.secho("--node-id and --component-name must be given together.", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    try:
        extract_design_tokens(file_key, workdir, on_event=_echo_event)
    except GenerationError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    typer.secho(f"Design tokens written to {design_tokens_path_for(workdir)}.", fg=typer.colors.GREEN)

    if node_id and component_name:
        try:
            generate_css_from_figma(file_key, node_id, component_name, workdir, on_event=_echo_event)
        except GenerationError as exc:
            typer.secho(str(exc), fg=typer.colors.RED)
            raise typer.Exit(code=1) from exc

        typer.secho(f"CSS written to {workdir / 'docs' / 'phase-3-design' / 'component.css'}.", fg=typer.colors.GREEN)


@sdlc_app.command("reconcile")
def sdlc_reconcile(
    workdir: Path = typer.Option(Path("./vishwakarma-output"), "--workdir", help="Project directory."),
) -> None:
    """Phase 4: cross-check SRS/HLD against extracted Figma design tokens, if any exist."""
    configure_logging()
    try:
        router, client = _build_pipeline()
    except ConfigError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    srs = _read_required_artifact(srs_path_for(workdir), "SRS.md")
    hld = _read_required_artifact(hld_path_for(workdir), "HLD.md")

    tokens_path = design_tokens_path_for(workdir)
    if not tokens_path.exists():
        typer.secho(
            f"No Figma design tokens found at {tokens_path} -- run `sdlc figma` first, "
            "or skip if this project has no UI.",
            fg=typer.colors.YELLOW,
        )
        return

    try:
        design_tokens = json.loads(tokens_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        typer.secho(
            f"design_tokens.json at {tokens_path} is not valid JSON -- regenerate it with sdlc figma.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1) from exc

    if _hld_describes_api_surface(hld) and JOINT_VALIDATION_HEADING not in hld:
        typer.secho(
            "Note: this HLD describes an API surface but has no Joint Validation section yet -- "
            "consider running `sdlc api` first.",
            fg=typer.colors.YELLOW,
        )

    try:
        run_full_stack_reconciliation(srs, hld, design_tokens, workdir, router, client, on_event=_echo_event)
    except GenerationError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    typer.secho(f"Full-Stack Reconciliation appended to {hld_path_for(workdir)}.", fg=typer.colors.GREEN)


@sdlc_app.command("jira")
def sdlc_jira(
    workdir: Path = typer.Option(Path("./vishwakarma-output"), "--workdir", help="Project directory."),
    project_key: str = typer.Option(..., "--project-key", help="Existing Jira project key."),
    sprint: bool = typer.Option(False, "--sprint", help="Also create a Sprint and move all created Stories into it."),
    sprint_name: str = typer.Option("", "--sprint-name", help="Sprint name (default: 'Sprint - <project_key>')."),
) -> None:
    """Phase 6: create a Jira Epic + one Story per FR-NNN from SRS.md, optionally starting a Sprint."""
    configure_logging()
    try:
        router, client = _build_pipeline()
    except ConfigError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    if not has_jira_credentials():
        typer.secho(
            "JIRA_URL / JIRA_USER / JIRA_API_TOKEN are not all set -- cannot call the Jira MCP server.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    srs = _read_required_artifact(srs_path_for(workdir), "SRS.md")

    try:
        state = create_sprint_plan(
            srs, workdir, project_key, router, client,
            create_sprint=sprint, sprint_name=sprint_name, on_event=_echo_event,
        )
    except GenerationError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    linked_count = sum(1 for s in state["stories"] if s["linked"])
    typer.secho(
        f"Epic {state['epic']['key']}: {len(state['stories'])} stories created, {linked_count} linked.",
        fg=typer.colors.GREEN,
    )
    if state["sprint"]:
        typer.secho(f"Sprint {state['sprint']['sprint_id']} ('{state['sprint']['name']}') populated.", fg=typer.colors.GREEN)
    typer.echo(f"Written to {jira_tickets_path_for(workdir)}.")


if __name__ == "__main__":
    app()
