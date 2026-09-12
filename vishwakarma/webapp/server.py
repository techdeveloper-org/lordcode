"""FastAPI app for Vishwakarma's local web UI.

Imports the same engine/ used by cli.py -- no separate internal API layer
between the CLI and the web app, since both run in the same local process
family for a single user.

POST /generate streams progress as Server-Sent Events (one event per model
call, fallback, and self-heal attempt) so the browser can show a live
activity log instead of a blank spinner, then a final event with the result.
"""

from __future__ import annotations

import json
import queue
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

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
from vishwakarma.engine.figma_design import design_tokens_path_for
from vishwakarma.engine.generate import GenerationError
from vishwakarma.engine.git_ops import (
    commit_generated_code,
    ensure_git_repo,
    has_github_remote,
    push_and_create_pr,
)
from vishwakarma.engine.jira_sprint import create_sprint_plan, has_jira_credentials, jira_tickets_path_for
from vishwakarma.engine.orchestrator import RunResult, run_task
from vishwakarma.engine.sdlc import generate_hld, generate_srs, hld_path_for, srs_path_for
from vishwakarma.llm_client import LLMClient
from vishwakarma.logging_config import configure_logging
from vishwakarma.plugins import load_all_agents, load_all_skills
from vishwakarma.router import Router
from vishwakarma.webapp import sessions

STATIC_DIR = Path(__file__).resolve().parent / "static"
DEFAULT_WORKDIR = Path("./vishwakarma-output")

configure_logging()
app = FastAPI(title="Vishwakarma")

_router: Router | None = None
_client: LLMClient | None = None


class GenerateRequest(BaseModel):
    """Request body for POST /generate."""

    task: str
    language: str | None = None
    workdir: str | None = None
    use_rag: bool = False
    project_dir: str | None = None
    skill_name: str | None = None
    agent_name: str | None = None
    max_heal_attempts: int = 3


def _get_pipeline() -> tuple[Router, LLMClient]:
    """Lazily construct (and cache) the router + multi-provider client for this process."""
    global _router, _client
    if _router is None or _client is None:
        config = load_config()
        _client = LLMClient(config.providers)
        _router = Router(config.models, _client)
        _router.validate_startup()
    return _router, _client


def _sse(event: dict) -> str:
    """Format a dict as one Server-Sent Event frame."""
    return f"data: {json.dumps(event)}\n\n"


def _stream_worker(fn, build_final_event) -> StreamingResponse:
    """Run `fn(on_event)` in a background thread, streaming its progress as SSE.

    Shared by /generate and the /sdlc/* endpoints so each one only supplies
    its own blocking work function and final-event shape -- the
    worker-thread/queue/SSE plumbing (and error surfacing) lives in one place.

    Args:
        fn: Called as `fn(on_event)` in a background thread; its return
            value is passed to `build_final_event`.
        build_final_event: Called with `fn`'s result to produce the dict
            yielded as the terminal `{"type": "final", ...}` SSE event.
    """
    event_queue: queue.Queue = queue.Queue()
    outcome: dict = {}

    def worker() -> None:
        try:
            outcome["result"] = fn(event_queue.put)
        except Exception as exc:  # noqa: BLE001 -- surfaced to the client as an error event, not swallowed
            outcome["error"] = str(exc)
        finally:
            event_queue.put({"type": "__done__"})

    threading.Thread(target=worker, daemon=True).start()

    def event_stream():
        while True:
            event = event_queue.get()
            if event["type"] == "__done__":
                break
            yield _sse(event)

        if "error" in outcome:
            yield _sse({"type": "error", "message": outcome["error"]})
            return

        yield _sse(build_final_event(outcome["result"]))

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _build_final_event(result: RunResult, workdir: Path, task: str) -> dict:
    """Persist a session and build the /generate|/sdlc/implement final SSE event."""
    files = {f.path: f.content for f in result.final_files}
    attempts = [
        {"attempt": a.attempt, "passed": a.result.passed, "stderr": a.result.stderr} for a in result.attempts
    ]
    session = sessions.save_session(
        task=task,
        engineered_prompt=result.engineered_prompt,
        language=result.language,
        complexity=result.complexity,
        plan=result.plan,
        skill_used=result.skill_used,
        agent_used=result.agent_used,
        passed=result.passed,
        files=files,
        attempts=attempts,
        workdir=str(workdir),
    )
    return {
        "type": "final",
        "session_id": session["id"],
        "workdir": str(workdir),
        "engineered_prompt": result.engineered_prompt,
        "language": result.language,
        "complexity": result.complexity,
        "plan": result.plan,
        "skill_used": result.skill_used,
        "agent_used": result.agent_used,
        "passed": result.passed,
        "files": files,
        "attempts": attempts,
    }


def _require_artifact(path: Path, label: str) -> str:
    """Read an SDLC artifact, raising a clear 400 if missing or blank."""
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        raise HTTPException(
            status_code=400, detail=f"{label} not found or empty at {path} -- run the earlier sdlc step first."
        )
    return path.read_text(encoding="utf-8")


@app.post("/generate")
def generate_endpoint(request: GenerateRequest) -> StreamingResponse:
    """Run generate -> test -> self-heal for one task, streaming progress as SSE."""
    try:
        router, client = _get_pipeline()
    except ConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    target_workdir = Path(request.workdir).expanduser() if request.workdir else DEFAULT_WORKDIR
    target_workdir.mkdir(parents=True, exist_ok=True)
    project_dir = Path(request.project_dir) if request.project_dir else None

    def run(on_event):
        return run_task(
            request.task,
            target_workdir,
            router,
            client,
            language=request.language,
            use_rag=request.use_rag,
            project_dir=project_dir,
            skill_name=request.skill_name,
            agent_name=request.agent_name,
            max_heal_attempts=request.max_heal_attempts,
            on_event=on_event,
        )

    return _stream_worker(run, lambda result: _build_final_event(result, target_workdir, request.task))


class SdlcDocsRequest(BaseModel):
    """Request body for POST /sdlc/docs."""

    workdir: str | None = None


class SdlcApiRequest(BaseModel):
    """Request body for POST /sdlc/api."""

    workdir: str | None = None


class SdlcGitRequest(BaseModel):
    """Request body for POST /sdlc/git."""

    workdir: str | None = None


class SdlcReconcileRequest(BaseModel):
    """Request body for POST /sdlc/reconcile."""

    workdir: str | None = None


class SdlcJiraRequest(BaseModel):
    """Request body for POST /sdlc/jira."""

    workdir: str | None = None
    project_key: str
    sprint: bool = False
    sprint_name: str | None = None
    message: str | None = None
    pr: bool = False
    branch: str | None = None
    pr_title: str | None = None
    pr_body: str | None = None
    base: str = "main"


class SdlcSrsRequest(BaseModel):
    """Request body for POST /sdlc/srs."""

    raw_requirements: str
    workdir: str | None = None


class SdlcHldRequest(BaseModel):
    """Request body for POST /sdlc/hld."""

    workdir: str | None = None
    task: str | None = None


@app.post("/sdlc/srs")
def sdlc_srs_endpoint(request: SdlcSrsRequest) -> StreamingResponse:
    """Phase 0: turn a raw idea into docs/phase-0-requirements/SRS.md."""
    try:
        router, client = _get_pipeline()
    except ConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    target_workdir = Path(request.workdir).expanduser() if request.workdir else DEFAULT_WORKDIR
    target_workdir.mkdir(parents=True, exist_ok=True)

    def run(on_event):
        return generate_srs(request.raw_requirements, target_workdir, router, client, on_event=on_event)

    return _stream_worker(
        run,
        lambda srs: {"type": "final", "srs_markdown": srs, "path": str(srs_path_for(target_workdir))},
    )


@app.post("/sdlc/hld")
def sdlc_hld_endpoint(request: SdlcHldRequest) -> StreamingResponse:
    """Phase 1: turn an approved SRS.md into docs/phase-1-architecture/HLD.md."""
    try:
        router, client = _get_pipeline()
    except ConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    target_workdir = Path(request.workdir).expanduser() if request.workdir else DEFAULT_WORKDIR
    srs_content = _require_artifact(srs_path_for(target_workdir), "SRS.md")

    def run(on_event):
        return generate_hld(
            srs_content, request.task or srs_content, target_workdir, router, client, on_event=on_event
        )

    return _stream_worker(
        run,
        lambda hld: {"type": "final", "hld_markdown": hld, "path": str(hld_path_for(target_workdir))},
    )


@app.post("/sdlc/implement")
def sdlc_implement_endpoint(request: GenerateRequest) -> StreamingResponse:
    """Phase 2+: implement the task using the approved SRS.md + HLD.md as context."""
    try:
        router, client = _get_pipeline()
    except ConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    target_workdir = Path(request.workdir).expanduser() if request.workdir else DEFAULT_WORKDIR
    srs_content = _require_artifact(srs_path_for(target_workdir), "SRS.md")
    hld_content = _require_artifact(hld_path_for(target_workdir), "HLD.md")
    project_dir = Path(request.project_dir) if request.project_dir else None

    # See cli.py's sdlc_implement for why this prepends rather than needing
    # a separate "external context" parameter on run_task().
    task_with_sdlc_context = (
        f"{request.task}\n\nApproved SRS (authoritative requirements):\n{srs_content}\n\n"
        f"Approved HLD (authoritative design):\n{hld_content}"
    )

    def run(on_event):
        return run_task(
            task_with_sdlc_context,
            target_workdir,
            router,
            client,
            language=request.language,
            use_rag=request.use_rag,
            project_dir=project_dir,
            skill_name=request.skill_name,
            agent_name=request.agent_name,
            max_heal_attempts=request.max_heal_attempts,
            on_event=on_event,
        )

    return _stream_worker(run, lambda result: _build_final_event(result, target_workdir, request.task))


@app.post("/sdlc/docs")
def sdlc_docs_endpoint(request: SdlcDocsRequest) -> StreamingResponse:
    """Phase 5: generate Mermaid UML diagrams + an SRS traceability matrix."""
    try:
        router, client = _get_pipeline()
    except ConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    target_workdir = Path(request.workdir).expanduser() if request.workdir else DEFAULT_WORKDIR
    srs_content = _require_artifact(srs_path_for(target_workdir), "SRS.md")
    hld_content = _require_artifact(hld_path_for(target_workdir), "HLD.md")

    file_list = list_source_files(target_workdir)
    if not file_list:
        raise HTTPException(
            status_code=400,
            detail=f"No generated code found in {target_workdir} -- run `sdlc implement` first.",
        )

    def run(on_event):
        diagrams = generate_docs(srs_content, hld_content, target_workdir, router, client, on_event=on_event)
        try:
            generate_traceability(srs_content, file_list, target_workdir, router, client, on_event=on_event)
        except GenerationError as exc:
            raise RuntimeError(str(exc)) from exc
        return diagrams

    def build_final_event(diagrams: dict[str, str]) -> dict:
        diagram_types = ["class", "component", "sequence", "usecase"]
        return {
            "type": "final",
            "diagrams": diagrams,
            "diagram_paths": {t: str(diagram_path_for(target_workdir, t)) for t in diagrams},
            "succeeded": len(diagrams),
            "total": len(diagram_types),
            "srs_path": str(srs_path_for(target_workdir)),
        }

    return _stream_worker(run, build_final_event)


@app.post("/sdlc/api")
def sdlc_api_endpoint(request: SdlcApiRequest) -> StreamingResponse:
    """Phase 1.5: generate an OpenAPI contract from the HLD, if applicable, and cross-validate."""
    try:
        router, client = _get_pipeline()
    except ConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    target_workdir = Path(request.workdir).expanduser() if request.workdir else DEFAULT_WORKDIR
    srs_content = _require_artifact(srs_path_for(target_workdir), "SRS.md")
    hld_content = _require_artifact(hld_path_for(target_workdir), "HLD.md")

    def run(on_event):
        spec = generate_api_contract(srs_content, hld_content, target_workdir, router, client, on_event=on_event)
        if spec is None:
            return None
        try:
            run_joint_validation(srs_content, hld_content, spec, target_workdir, router, client, on_event=on_event)
        except GenerationError as exc:
            raise RuntimeError(str(exc)) from exc
        return spec

    def build_final_event(spec: str | None) -> dict:
        if spec is None:
            return {"type": "final", "skipped": True, "reason": "no API surface described in HLD"}
        return {
            "type": "final",
            "skipped": False,
            "openapi_yaml": spec,
            "openapi_path": str(api_contract_path_for(target_workdir)),
            "hld_path": str(hld_path_for(target_workdir)),
        }

    return _stream_worker(run, build_final_event)


@app.post("/sdlc/git")
def sdlc_git_endpoint(request: SdlcGitRequest) -> StreamingResponse:
    """Commit generated code, and optionally push a branch + open a GitHub PR."""
    target_workdir = Path(request.workdir).expanduser() if request.workdir else DEFAULT_WORKDIR
    target_workdir.mkdir(parents=True, exist_ok=True)

    if request.pr and (not request.branch or not request.pr_title):
        raise HTTPException(status_code=400, detail="branch and pr_title are required when pr is true.")

    def run(on_event):
        initialized = ensure_git_repo(target_workdir, on_event=on_event)
        commit = commit_generated_code(
            target_workdir, request.message or "Generated by Vishwakarma", on_event=on_event
        )

        if not request.pr:
            return {"initialized": initialized, "commit": commit, "pr_skipped_reason": None, "pr": None}

        if not has_github_remote(target_workdir):
            return {
                "initialized": initialized,
                "commit": commit,
                "pr_skipped_reason": "No GitHub remote configured for this workdir",
                "pr": None,
            }

        pr_data = push_and_create_pr(
            target_workdir, request.branch, request.pr_title, request.pr_body or "", request.base, on_event=on_event
        )
        return {"initialized": initialized, "commit": commit, "pr_skipped_reason": None, "pr": pr_data}

    def build_final_event(outcome: dict) -> dict:
        return {"type": "final", **outcome}

    return _stream_worker(run, build_final_event)


@app.post("/sdlc/reconcile")
def sdlc_reconcile_endpoint(request: SdlcReconcileRequest) -> StreamingResponse:
    """Phase 4: cross-check SRS/HLD against extracted Figma design tokens, if any exist."""
    try:
        router, client = _get_pipeline()
    except ConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    target_workdir = Path(request.workdir).expanduser() if request.workdir else DEFAULT_WORKDIR
    # Fresh reads per-request, same as every other /sdlc/* endpoint -- picks
    # up any Joint Validation section a separate prior /sdlc/api request
    # already appended to this same file.
    srs_content = _require_artifact(srs_path_for(target_workdir), "SRS.md")
    hld_content = _require_artifact(hld_path_for(target_workdir), "HLD.md")

    tokens_path = design_tokens_path_for(target_workdir)
    if not tokens_path.exists():
        def build_skip_event(_result: None) -> dict:
            return {"type": "final", "skipped": True, "reason": f"No Figma design tokens found at {tokens_path}"}

        return _stream_worker(lambda on_event: None, build_skip_event)

    try:
        design_tokens = json.loads(tokens_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=400, detail=f"design_tokens.json at {tokens_path} is not valid JSON."
        ) from exc

    advisory = None
    if _hld_describes_api_surface(hld_content) and JOINT_VALIDATION_HEADING not in hld_content:
        advisory = "This HLD describes an API surface but has no Joint Validation section yet."

    def run(on_event):
        return run_full_stack_reconciliation(
            srs_content, hld_content, design_tokens, target_workdir, router, client, on_event=on_event
        )

    def build_final_event(hld_with_reconciliation: str) -> dict:
        return {
            "type": "final",
            "skipped": False,
            "hld_markdown": hld_with_reconciliation,
            "hld_path": str(hld_path_for(target_workdir)),
            "advisory": advisory,
        }

    return _stream_worker(run, build_final_event)


@app.post("/sdlc/jira")
def sdlc_jira_endpoint(request: SdlcJiraRequest) -> StreamingResponse:
    """Phase 6: create a Jira Epic + one Story per FR-NNN from SRS.md, optionally starting a Sprint."""
    try:
        router, client = _get_pipeline()
    except ConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not has_jira_credentials():
        raise HTTPException(
            status_code=400, detail="JIRA_URL / JIRA_USER / JIRA_API_TOKEN are not all set."
        )

    target_workdir = Path(request.workdir).expanduser() if request.workdir else DEFAULT_WORKDIR
    srs_content = _require_artifact(srs_path_for(target_workdir), "SRS.md")

    def run(on_event):
        return create_sprint_plan(
            srs_content, target_workdir, request.project_key, router, client,
            create_sprint=request.sprint, sprint_name=request.sprint_name or "", on_event=on_event,
        )

    def build_final_event(state: dict) -> dict:
        return {"type": "final", **state, "jira_tickets_path": str(jira_tickets_path_for(target_workdir))}

    return _stream_worker(run, build_final_event)


@app.get("/sessions")
def list_sessions_endpoint() -> list[dict]:
    """Return lightweight summaries of every past chat/generation, newest first."""
    return sessions.list_sessions()


@app.get("/sessions/{session_id}")
def get_session_endpoint(session_id: str) -> dict:
    """Return one full stored session (files, attempts, plan) by id."""
    session = sessions.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@app.delete("/sessions/{session_id}")
def delete_session_endpoint(session_id: str) -> dict:
    """Delete one stored session by id."""
    if not sessions.delete_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"deleted": session_id}


@app.get("/skills")
def list_skills() -> list[dict[str, str]]:
    """Return every matchable skill's name + description, for the UI's search box."""
    return [{"name": s.name, "description": s.description} for s in load_all_skills()]


@app.get("/agents")
def list_agents() -> list[dict[str, str]]:
    """Return every available subagent persona's name + role, for the UI's search box."""
    return [{"name": a.name, "role": a.role, "description": a.description} for a in load_all_agents()]


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
