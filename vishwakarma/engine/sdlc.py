"""Phase 0 (BA/PM -> SRS.md) and Phase 1 (Solution Architecture -> HLD.md) as
real, durable file artifacts with a file-edit-based STOP gate -- Milestone 1
of the full-SDLC roadmap. Both phases write to <workdir>/docs/... and reuse
the SRS.md convention already established at ~/.claude/rules/44-srs-lifecycle.md
rather than inventing a parallel PRD format.

Distilled from claude-global-library's business-analyst-agent +
product-manager-agent (combined into ONE persona -- this Groq account has
only 2 real model families behind any role, so two separate BA/PM calls
would both resolve to the same underlying model, producing the appearance
of independent review at 2x cost with no actual independence) and from
solution-architect (already partially adapted as
engine.orchestrator.SOLUTION_ARCHITECT_SYSTEM_PROMPT/solution_architect_review,
here extended from a compact inline blueprint into a full persisted
document).

Routing: both calls use the `fallback_long_context` role, not `reasoner` --
qwen/qwen3.6-27b (reasoner's first candidate) hard-rejects any single
request whose max_tokens exceeds ~1000, and a real SRS/HLD with multiple
FR/NFR/ADR entries routinely needs more than that. fallback_long_context
resolves to openai/gpt-oss-120b/-20b, which has no such ceiling.
"""

from __future__ import annotations

from pathlib import Path

from vishwakarma.engine.agent_runtime import AgentCoordinator, RemoteLLM
from vishwakarma.engine.calling import OnEvent, noop_event
from vishwakarma.engine.generate import GenerationError
from vishwakarma.engine.orchestrator import (
    CONSENSUS_SYSTEM_PROMPT,
    CONTEXT_ENGINEER_SYSTEM_PROMPT,
    PROMPT_ENGINEER_SYSTEM_PROMPT,
)
from vishwakarma.engine.reasoning_utils import strip_reasoning_trace
from vishwakarma.llm_client import LLMClient
from vishwakarma.router import Router

MAX_SDLC_TOKENS = 4000
"""These calls route to fallback_long_context (gpt-oss-120b/-20b), which has
no ~1000-token hard request cap the way qwen does, so this can be generous:
a real SRS/HLD with a full file list, several ADR-style decisions, and a
multi-step data flow section routinely needs 2000+ output tokens -- a
tighter budget was observed truncating the document mid-section before
reaching its required trailing sections (Edge Cases, Risks)."""

SRS_REQUIRED_HEADINGS = (
    "## 1. Purpose",
    "## 2. Scope",
    "## 3. Requirements",
    "## 4. Acceptance Criteria",
    "## 5. Out of Scope",
    "## 6. Change Log",
)

SRS_SYSTEM_PROMPT = (
    "You are producing a Software Requirements Specification for ONE "
    "personal coding task -- combining a business analyst's job (what must "
    "the system do, what's the acceptance bar) and a product manager's job "
    "(priority, scope boundary) into one document, scaled to the task's own "
    "size (do not invent enterprise market-sizing/TAM/competitive-landscape "
    "content this task doesn't call for). "
    "Produce EXACTLY these sections, in this order, using these EXACT "
    "heading strings:\n"
    "## 1. Purpose\n"
    "One paragraph: what this builds and for whom.\n"
    "## 2. Scope\n"
    "What is in scope; what is explicitly out.\n"
    "## 3. Requirements\n"
    "### 3.1 Functional Requirements\n"
    "Numbered FR-001, FR-002, ... entries, each with a one-line priority "
    "(High/Medium/Low).\n"
    "### 3.2 Non-Functional Requirements\n"
    "Numbered NFR-001, NFR-002, ... entries (performance, reliability, "
    "usability -- only what genuinely applies to this task's scale).\n"
    "## 4. Acceptance Criteria\n"
    "One AC per FR, referencing its FR number.\n"
    "## 5. Out of Scope\n"
    "Explicit list of excluded features, to prevent scope creep.\n"
    "## 6. Change Log\n"
    "A markdown table with columns Date | Version | Change | Status, "
    "seeded with exactly one row for this initial creation "
    "(version 1.0.0, status Done).\n"
    "Do not omit any section. Do not write code."
)

HLD_REQUIRED_HEADINGS = (
    "## System Overview",
    "## Files & Responsibilities",
    "## Key Design Decisions",
    "## Data Flow",
    "## Edge Cases",
    "## Risks",
)

HLD_SYSTEM_PROMPT = (
    "You are a solution architect producing a High-Level Design document "
    "for ONE coding task, given its approved SRS. Scale your response to "
    "what this task actually needs -- do NOT produce enterprise ceremony "
    "(no microservices topology, no capacity/QPS estimation, no compliance "
    "matrix) unless the task's own scale genuinely calls for it. Produce "
    "EXACTLY these sections, in this order, using these EXACT heading "
    "strings:\n"
    "## System Overview\n"
    "Two or three sentences: what this system is and how its pieces fit "
    "together.\n"
    "## Files & Responsibilities\n"
    "The files to create and each one's responsibility.\n"
    "## Key Design Decisions\n"
    "For each non-trivial choice (data structure, algorithm, library, "
    "pattern), ADR-style: what was chosen, why, and the main alternative "
    "rejected -- one entry per decision.\n"
    "## Data Flow\n"
    "How data moves through the system for its main use case(s).\n"
    "## Edge Cases\n"
    "Specific inputs/conditions the implementation must handle, tied back "
    "to the SRS's FR/NFR numbers where relevant.\n"
    "## Risks\n"
    "Anything that could make this fail or be wrong.\n"
    "Do not omit any section. Do not write code."
)


SRS_INVENTED_SCOPE_INSTRUCTION = (
    "Also flag any FR/NFR/AC in the SRS with no basis in the raw requirements "
    "below -- invented/hallucinated scope."
)


def _persona_engineer_context(remote_llm: RemoteLLM, raw_text: str) -> str:
    """Spawned-agent persona mirroring engine.orchestrator.engineer_context()'s body."""
    messages = [
        {"role": "system", "content": CONTEXT_ENGINEER_SYSTEM_PROMPT},
        {"role": "user", "content": raw_text},
    ]
    raw = remote_llm.call_role(
        "fallback_long_context", "engineer context (SDLC)", messages,
        light_reasoning=True, temperature=0.2, max_tokens=500,
    )
    return strip_reasoning_trace(raw)


def _persona_engineer_prompt(remote_llm: RemoteLLM, raw_text: str, context_block: str) -> str:
    """Spawned-agent persona mirroring engine.orchestrator.engineer_prompt()'s body."""
    user_content = f"Original user request:\n{raw_text}\n\nStructured context:\n{context_block}"
    messages = [
        {"role": "system", "content": PROMPT_ENGINEER_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    raw = remote_llm.call_role(
        "fallback_long_context", "engineer final prompt (SDLC)", messages,
        light_reasoning=True, temperature=0.3, max_tokens=600,
    )
    return strip_reasoning_trace(raw)


def _persona_generate_srs(remote_llm: RemoteLLM, engineered_requirements: str) -> str:
    """Spawned-agent persona that generates the SRS body itself."""
    messages = [
        {"role": "system", "content": SRS_SYSTEM_PROMPT},
        {"role": "user", "content": engineered_requirements},
    ]
    raw = remote_llm.call_role(
        "fallback_long_context", "generate SRS (Phase 0)", messages,
        light_reasoning=True, temperature=0.2, max_tokens=MAX_SDLC_TOKENS,
    )
    return strip_reasoning_trace(raw)


def _persona_generate_hld(remote_llm: RemoteLLM, engineered_input: str) -> str:
    """Spawned-agent persona that generates the HLD body itself."""
    messages = [
        {"role": "system", "content": HLD_SYSTEM_PROMPT},
        {"role": "user", "content": engineered_input},
    ]
    raw = remote_llm.call_role(
        "fallback_long_context", "generate HLD (Phase 1)", messages,
        light_reasoning=True, temperature=0.2, max_tokens=MAX_SDLC_TOKENS,
    )
    return strip_reasoning_trace(raw)


def _persona_consensus_review(
    remote_llm: RemoteLLM,
    task: str,
    blueprint: str,
    round_number: int,
    extra_instruction: str | None,
) -> tuple[bool, str]:
    """Spawned-agent persona mirroring engine.orchestrator.consensus_review()'s
    body, routed through fallback_long_context (SRS/HLD-sized content)."""
    user_content = f"Task: {task}\n\nProposed blueprint:\n{blueprint}"
    if extra_instruction:
        user_content += f"\n\nAdditional check for this review: {extra_instruction}"
    messages = [
        {"role": "system", "content": CONSENSUS_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    raw = remote_llm.call_role(
        "fallback_long_context",
        f"consensus review of blueprint (round {round_number})",
        messages,
        light_reasoning=True,
        temperature=0.0,
        max_tokens=300,
    )
    text = strip_reasoning_trace(raw)
    approved = "REJECTED" not in text.upper()
    return approved, text


def _missing_headings(text: str, required: tuple[str, ...]) -> list[str]:
    """Return the subset of required headings not found verbatim in text."""
    return [heading for heading in required if heading not in text]


def _refuse_if_exists(path: Path, label: str) -> None:
    """Raise if an SDLC artifact already exists, per its append-only convention."""
    if path.exists():
        raise GenerationError(
            f"{label} already exists at {path} -- edit it directly, or delete it to regenerate."
        )


def srs_path_for(workdir: Path) -> Path:
    """Return the conventional SRS.md path for a workdir."""
    return workdir / "docs" / "phase-0-requirements" / "SRS.md"


def hld_path_for(workdir: Path) -> Path:
    """Return the conventional HLD.md path for a workdir."""
    return workdir / "docs" / "phase-1-architecture" / "HLD.md"


def generate_srs(
    raw_requirements: str,
    workdir: Path,
    router: Router,
    client: LLMClient,
    on_event: OnEvent = noop_event,
) -> str:
    """Produce docs/phase-0-requirements/SRS.md from a raw idea.

    Args:
        raw_requirements: The user's free-text idea/requirements.
        workdir: Project directory; SRS.md is written under its docs/ tree.
        router: Resolves model roles to live candidates.
        client: The multi-provider LLM client to call through.
        on_event: Progress event sink (see engine/calling.py).

    Returns:
        The SRS markdown content that was written, including a trailing
        "## Requirements Review" section (an advisory consensus-gate verdict
        checking for dropped or invented requirements against the raw input).

    Raises:
        GenerationError: If SRS.md already exists, or the model's response
            is missing a required section.
    """
    srs_path = srs_path_for(workdir)
    _refuse_if_exists(srs_path, "SRS.md")

    # Milestone 1.5: each stage runs as a genuinely separate OS process
    # (real agent spawning), funneled through one AgentCoordinator so the
    # shared RateLimiter/Router stay honest -- see engine/agent_runtime.py.
    coordinator = AgentCoordinator(router, client, on_event=on_event)
    try:
        process, agent_id = coordinator.spawn_agent(_persona_engineer_context, (raw_requirements,))
        process.join()
        context_block = coordinator.await_result(agent_id)
        on_event({"type": "srs_context_engineered", "context": context_block})

        process, agent_id = coordinator.spawn_agent(
            _persona_engineer_prompt, (raw_requirements, context_block)
        )
        process.join()
        engineered_requirements = coordinator.await_result(agent_id)
        on_event({"type": "srs_prompt_engineered", "prompt": engineered_requirements})

        process, agent_id = coordinator.spawn_agent(_persona_generate_srs, (engineered_requirements,))
        process.join()
        srs = coordinator.await_result(agent_id)

        missing = _missing_headings(srs, SRS_REQUIRED_HEADINGS)
        if missing:
            raise GenerationError(f"Generated SRS is missing required section(s): {', '.join(missing)}")

        process, agent_id = coordinator.spawn_agent(
            _persona_consensus_review,
            (raw_requirements, srs, 1, SRS_INVENTED_SCOPE_INSTRUCTION),
        )
        process.join()
        approved, verdict = coordinator.await_result(agent_id)
    finally:
        coordinator.stop()

    on_event({"type": "srs_review", "approved": approved, "reason": verdict})
    srs_with_review = (
        f"{srs}\n\n## Requirements Review\n\n"
        f"**Verdict:** {'APPROVED' if approved else 'REJECTED'}\n\n{verdict}\n"
    )

    srs_path.parent.mkdir(parents=True, exist_ok=True)
    srs_path.write_text(srs_with_review, encoding="utf-8")
    return srs_with_review


def generate_hld(
    srs: str,
    task_context: str,
    workdir: Path,
    router: Router,
    client: LLMClient,
    on_event: OnEvent = noop_event,
) -> str:
    """Produce docs/phase-1-architecture/HLD.md from an approved SRS.

    Includes a trailing "## Architect Self-Review" section (an advisory
    consensus-gate verdict on the blueprint, reusing
    engine.orchestrator.consensus_review) so the human's file-edit review is
    actually informed by it, rather than computing a check nobody sees.

    Args:
        srs: The (possibly user-edited) SRS.md content.
        task_context: Short description of the concrete task/stack.
        workdir: Project directory; HLD.md is written under its docs/ tree.
        router: Resolves model roles to live candidates.
        client: The multi-provider LLM client to call through.
        on_event: Progress event sink (see engine/calling.py).

    Returns:
        The HLD markdown content (including the self-review section) that
        was written.

    Raises:
        GenerationError: If HLD.md already exists, or the model's response
            is missing a required section.
    """
    hld_path = hld_path_for(workdir)
    _refuse_if_exists(hld_path, "HLD.md")

    raw_input = f"Task: {task_context}\n\nApproved SRS:\n{srs}"

    # Milestone 1.5: each stage runs as a genuinely separate OS process
    # (real agent spawning), funneled through one AgentCoordinator so the
    # shared RateLimiter/Router stay honest -- see engine/agent_runtime.py.
    coordinator = AgentCoordinator(router, client, on_event=on_event)
    try:
        process, agent_id = coordinator.spawn_agent(_persona_engineer_context, (raw_input,))
        process.join()
        context_block = coordinator.await_result(agent_id)
        on_event({"type": "hld_context_engineered", "context": context_block})

        process, agent_id = coordinator.spawn_agent(_persona_engineer_prompt, (raw_input, context_block))
        process.join()
        engineered_input = coordinator.await_result(agent_id)
        on_event({"type": "hld_prompt_engineered", "prompt": engineered_input})

        process, agent_id = coordinator.spawn_agent(_persona_generate_hld, (engineered_input,))
        process.join()
        hld = coordinator.await_result(agent_id)

        missing = _missing_headings(hld, HLD_REQUIRED_HEADINGS)
        if missing:
            raise GenerationError(f"Generated HLD is missing required section(s): {', '.join(missing)}")

        process, agent_id = coordinator.spawn_agent(
            _persona_consensus_review, (task_context, hld, 1, None)
        )
        process.join()
        approved, verdict = coordinator.await_result(agent_id)
    finally:
        coordinator.stop()

    on_event({"type": "hld_review", "approved": approved, "reason": verdict})
    hld_with_review = (
        f"{hld}\n\n## Architect Self-Review\n\n"
        f"**Verdict:** {'APPROVED' if approved else 'REJECTED'}\n\n{verdict}\n"
    )

    hld_path.parent.mkdir(parents=True, exist_ok=True)
    hld_path.write_text(hld_with_review, encoding="utf-8")
    return hld_with_review
