"""Milestone 4: Sprint Planning via real Jira tickets, scoped well below
claude-global-library's own SPRINT_PLANNING_PIPELINE.md (no PERT/BCa/AHP/
WSJF/capacity-planning machinery) -- the real, concrete deliverable is one
Epic representing the SRS as a whole, one Story per FR-NNN linked to that
Epic, and optionally one Sprint with all created Stories moved into it.

mcp-jira-api requires JIRA_URL/JIRA_USER/JIRA_API_TOKEN in its own process
environment (same env-passthrough gotcha already found and fixed for
mcp-figma). It also hardcodes the classic/company-managed Jira Cloud
convention for Epic Link/Epic Name custom fields -- team-managed ("next-gen")
projects, which is Jira Cloud's current default for new sites, are not
supported by the underlying server; this can only be confirmed once real
credentials and a real project exist.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from vishwakarma.engine.agent_runtime import AgentCoordinator, RemoteLLM
from vishwakarma.engine.api_contract import _strip_yaml_fence
from vishwakarma.engine.calling import OnEvent, noop_event
from vishwakarma.engine.generate import GenerationError
from vishwakarma.engine.reasoning_utils import strip_reasoning_trace
from vishwakarma.llm_client import LLMClient
from vishwakarma.mcp_client import MCP_SERVERS, call_mcp_tool
from vishwakarma.router import Router

_FR_EXTRACTION_SYSTEM_PROMPT = (
    "You are extracting a machine-readable list of functional requirements "
    "from a Software Requirements Specification. Output ONLY a JSON array, "
    "one object per FR-NNN entry in the SRS's Functional Requirements "
    "section: [{\"id\": \"FR-001\", \"summary\": \"...\"}, ...]. The "
    "'summary' must be a concise, one-line restatement of that requirement, "
    "suitable as a Jira Story title. Output raw JSON only -- no prose "
    "before or after it, no markdown code fence."
)


def _persona_extract_functional_requirements(remote_llm: RemoteLLM, srs: str) -> str:
    """Spawned-agent persona that extracts FR-NNN entries as structured JSON."""
    messages = [
        {"role": "system", "content": _FR_EXTRACTION_SYSTEM_PROMPT},
        {"role": "user", "content": f"SRS:\n{srs}"},
    ]
    raw = remote_llm.call_role(
        "fallback_long_context", "extract functional requirements (Phase 6)", messages,
        light_reasoning=True, temperature=0.0, max_tokens=1200,
    )
    return strip_reasoning_trace(raw)


def _parse_functional_requirements(raw: str) -> list[dict]:
    """Validate and parse the extraction persona's JSON output.

    Reuses api_contract._strip_yaml_fence directly, unmodified -- its regex
    already tolerates a bare fence with no language tag.

    Raises:
        GenerationError: If the result isn't a non-empty list of dicts each
            with string "id"/"summary" keys.
    """
    stripped = _strip_yaml_fence(raw)
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        parsed = None

    valid = (
        isinstance(parsed, list)
        and len(parsed) > 0
        and all(
            isinstance(item, dict) and isinstance(item.get("id"), str) and isinstance(item.get("summary"), str)
            for item in parsed
        )
    )
    if not valid:
        raise GenerationError("Functional requirement extraction did not produce a valid JSON list")
    return parsed


def has_jira_credentials() -> bool:
    """Cheap, deterministic pre-flight check -- no MCP call needed."""
    return bool(os.environ.get("JIRA_URL") and os.environ.get("JIRA_USER") and os.environ.get("JIRA_API_TOKEN"))


def _jira_env() -> dict[str, str]:
    """Pass the caller's full environment through, so JIRA_URL/JIRA_USER/
    JIRA_API_TOKEN (which the mcp SDK's default stdio env allowlist would
    otherwise drop) reach the spawned mcp-jira-api server process."""
    return {**os.environ}


def jira_tickets_path_for(workdir: Path) -> Path:
    """Return the conventional jira_tickets.json path for a workdir,
    matching claude-global-library's own docs/phase-6-sprint-planning/
    convention exactly."""
    return workdir / "docs" / "phase-6-sprint-planning" / "jira_tickets.json"


def _write_tickets_state(workdir: Path, state: dict) -> None:
    path = jira_tickets_path_for(workdir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def create_sprint_plan(
    srs: str,
    workdir: Path,
    project_key: str,
    router: Router,
    client: LLMClient,
    create_sprint: bool = False,
    sprint_name: str = "",
    on_event: OnEvent = noop_event,
) -> dict:
    """Create a Jira Epic + one Story per FR-NNN (linked to the Epic), and
    optionally a Sprint with all created Stories moved into it.

    Writes docs/phase-6-sprint-planning/jira_tickets.json incrementally, so
    a mid-batch failure still leaves a locally readable manifest of
    everything actually created.

    Raises:
        GenerationError: If FR extraction fails, or if epic/story/sprint
            creation fails -- these are real, user-initiated, opt-in
            actions that must surface, not fail open. A story-creation
            failure stops further creation (mirroring git_ops.push_branch's
            stop-on-first-failure, leave-visible-state discipline); a
            single story's epic-link failure is non-fatal.
    """
    env = _jira_env()
    jira_server = MCP_SERVERS["jira"]

    coordinator = AgentCoordinator(router, client, on_event=on_event)
    try:
        process, agent_id = coordinator.spawn_agent(_persona_extract_functional_requirements, (srs,))
        process.join()
        raw = coordinator.await_result(agent_id)
    finally:
        coordinator.stop()

    functional_requirements = _parse_functional_requirements(raw)

    epic_result = call_mcp_tool(
        jira_server,
        "jira_create_epic",
        {
            "project_key": project_key,
            "name": f"{project_key} feature",
            "summary": srs.strip().splitlines()[0] if srs.strip() else project_key,
            "idempotency_key": f"{project_key}:epic",
        },
        env=env,
    )
    if not epic_result.ok:
        raise GenerationError(f"jira_create_epic failed for {project_key}: {epic_result.error}")

    epic_key = epic_result.data["epic_key"]
    state = {"epic": {"key": epic_key, "url": epic_result.data.get("epic_url")}, "stories": [], "sprint": None}
    _write_tickets_state(workdir, state)
    on_event({"type": "jira_epic_created", "epic_key": epic_key})

    created_issue_keys: list[str] = []
    for fr in functional_requirements:
        issue_result = call_mcp_tool(
            jira_server,
            "jira_create_issue",
            {
                "project_key": project_key,
                "summary": fr["summary"],
                "issue_type": "Story",
                "idempotency_key": f"{project_key}:{fr['id']}",
            },
            env=env,
        )
        if not issue_result.ok:
            raise GenerationError(
                f"jira_create_issue failed for {fr['id']}: {issue_result.error} "
                f"-- {len(created_issue_keys)} stories already created and recorded in "
                f"{jira_tickets_path_for(workdir)}"
            )

        issue_key = issue_result.data["issue_key"]
        created_issue_keys.append(issue_key)
        on_event({"type": "jira_story_created", "fr_id": fr["id"], "issue_key": issue_key})

        link_result = call_mcp_tool(
            jira_server, "jira_link_to_epic", {"issue_key": issue_key, "epic_key": epic_key}, env=env
        )
        linked = link_result.ok
        if not linked:
            on_event({"type": "jira_epic_link_failed", "issue_key": issue_key, "reason": link_result.error})

        state["stories"].append({"fr_id": fr["id"], "issue_key": issue_key, "linked": linked})
        _write_tickets_state(workdir, state)

    if create_sprint:
        boards_result = call_mcp_tool(
            jira_server, "jira_get_boards", {"project_key": project_key, "board_type": "scrum"}, env=env
        )
        if not boards_result.ok or not boards_result.data.get("boards"):
            raise GenerationError(f"No Scrum board found for project {project_key}")

        board_id = boards_result.data["boards"][0]["board_id"]
        resolved_sprint_name = sprint_name or f"Sprint - {project_key}"

        sprint_result = call_mcp_tool(
            jira_server,
            "jira_create_sprint",
            {
                "board_id": board_id,
                "name": resolved_sprint_name,
                "idempotency_key": f"{project_key}:sprint:{sprint_name or 'default'}",
            },
            env=env,
        )
        if not sprint_result.ok:
            raise GenerationError(f"jira_create_sprint failed for board {board_id}: {sprint_result.error}")

        sprint_id = sprint_result.data["sprint_id"]
        on_event({"type": "jira_sprint_created", "sprint_id": sprint_id, "name": resolved_sprint_name})

        move_result = call_mcp_tool(
            jira_server,
            "jira_move_issues_to_sprint",
            {"sprint_id": sprint_id, "issue_keys": ",".join(created_issue_keys)},
            env=env,
        )
        if not move_result.ok:
            raise GenerationError(
                f"sprint {sprint_id} created but jira_move_issues_to_sprint failed: {move_result.error}"
            )

        on_event({"type": "jira_issues_moved_to_sprint", "sprint_id": sprint_id, "issue_keys": created_issue_keys})
        state["sprint"] = {"sprint_id": sprint_id, "name": resolved_sprint_name}
        _write_tickets_state(workdir, state)

    return state
