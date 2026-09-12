"""Multi-model orchestration: context-engineer -> prompt-engineer -> detect
language -> classify -> (plan) -> generate -> execute -> self-heal.

Several distinct models collaborate on one task, each doing only the job it
is actually suited for (per the ai-engineer review):
  - reasoner FIRST engineers context (extracting explicit/implicit
    requirements and edge cases from the user's raw request), THEN engineers
    a final, well-structured prompt from that context -- mirroring
    claude-global-library's context-engineering-agent -> prompt-generation-expert
    sequence, scaled down to this tool's single-coder-call architecture (no
    multi-agent bundle, no user-consultation gate -- those fit an SDLC
    orchestration pipeline, not a personal code generation tool). The
    engineered prompt, not the user's raw text, is what every step below
    actually works from.
  - router_fast makes cheap, strict classification calls -- which language
    the task targets, and whether it's simple or complex -- never asked for
    nuanced judgment.
  - reasoner also sketches a short implementation plan ONLY for tasks
    classified complex, and separately diagnoses self-heal failures.
  - primary_coder writes the code and its own tests in one call, optionally
    steered by the plan and by a matched skill/subagent.
Every model call goes through engine/calling.py's call_role(), which also
falls across providers automatically and emits progress events consumed by
the CLI's live echo and the web UI's activity log.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from vishwakarma.engine import generate as generate_module
from vishwakarma.engine import parallel_generate
from vishwakarma.engine import rag
from vishwakarma.engine import self_heal as self_heal_module
from vishwakarma.engine.agent_runtime import AgentCoordinator, RemoteLLM
from vishwakarma.engine.calling import OnEvent, call_role, noop_event
from vishwakarma.engine.kg_routing import route_persona
from vishwakarma.engine.executor import ExecutionResult, run_tests, write_files
from vishwakarma.engine.generate import FileSpec, GeneratedArtifact, GenerationError
from vishwakarma.engine.reasoning_utils import strip_reasoning_trace
from vishwakarma.engine.self_heal import AttemptRecord, HealResult
from vishwakarma.languages import available_languages
from vishwakarma.llm_client import LLMClient
from vishwakarma.plugins import SubAgent, get_agent, load_all_agents, load_all_skills, match_skill
from vishwakarma.router import Router

DEFAULT_LANGUAGE = "python"

CONTEXT_ENGINEER_SYSTEM_PROMPT = (
    "You are a context engineering specialist. Given a user's raw coding "
    "request, extract a compact, structured context block that a prompt "
    "engineer will use next to write the final instruction for a coder "
    "model. Cover exactly these sections, each as a short bullet list:\n"
    "EXPLICIT REQUIREMENTS: what the user directly asked for.\n"
    "IMPLICIT REQUIREMENTS: reasonable expectations the user didn't state "
    "but clearly needs (e.g. error handling, obvious edge cases for the "
    "domain) -- mark each as [INFERRED].\n"
    "EDGE CASES: specific inputs/conditions the implementation must handle.\n"
    "AMBIGUITIES RESOLVED: any unstated choice you had to default (e.g. "
    "which library, which style) -- state the default picked and why in one "
    "clause each.\n"
    "Do not write any code. Do not restate the whole request verbatim -- "
    "extract and structure only. Keep the entire response under 200 words."
)

PROMPT_ENGINEER_SYSTEM_PROMPT = (
    "You are a prompt engineering specialist. You receive a user's original "
    "coding request plus a structured context block. Your ONLY job is to "
    "write the FINAL prompt that will be sent to a code-generation model -- "
    "you do not solve the task yourself. Structure the final prompt in this "
    "exact order: (1) a one-line persona/framing for the coder, (2) the core "
    "task restated clearly and completely, (3) explicit constraints and "
    "requirements from the context block, (4) the edge cases that must be "
    "handled, (5) the expected output format. Place the single most "
    "critical constraint at both the very start and the very end of the "
    "prompt (primacy and recency both matter for instruction-following). Be "
    "concrete and specific -- never vague filler like 'make it good'. "
    "Output ONLY the final prompt text itself, nothing else -- no preamble, "
    "no markdown fences, no meta-commentary about what you did."
)


def engineer_context(
    task: str, router: Router, client: LLMClient, on_event: OnEvent = noop_event, role: str = "reasoner"
) -> str:
    """Extract a structured context block from the user's raw request.

    Mirrors claude-global-library's context-engineering-agent role, scaled
    down to a single lightweight call appropriate for this tool's
    single-coder-call architecture (no Differential GSD, no multi-agent
    namespace isolation -- this tool has one context consumer, not a fleet
    of sub-agents needing isolated token budgets).

    Args:
        task: The user's free-text task description.
        router: Resolves model roles to live candidates.
        client: The multi-provider LLM client to call through.
        on_event: Progress event sink (see engine/calling.py).
        role: Model role to call through -- defaults to "reasoner" for the
            main pipeline's short task text. Callers feeding this a larger
            document (e.g. engine/sdlc.py's SRS/HLD-sized input) should pass
            "fallback_long_context" instead: reasoner's first candidate
            (qwen) hard-rejects requests whose expected output exceeds its
            ~1000-token cap, a risk that scales with input size.

    Returns:
        A compact, structured context block (explicit/implicit requirements,
        edge cases, resolved ambiguities), with any reasoning trace stripped.
    """
    messages = [
        {"role": "system", "content": CONTEXT_ENGINEER_SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]
    raw = call_role(
        role,
        "engineer context",
        messages,
        router,
        client,
        priority="interactive",
        on_event=on_event,
        light_reasoning=True,
        temperature=0.2,
        max_tokens=500,
    )
    return strip_reasoning_trace(raw)


def engineer_prompt(
    task: str,
    context_block: str,
    router: Router,
    client: LLMClient,
    on_event: OnEvent = noop_event,
    role: str = "reasoner",
) -> str:
    """Turn the raw task + engineered context into the final coder prompt.

    Mirrors claude-global-library's prompt-generation-expert role (manual
    prompt-engineering-core craft: persona -> constraints -> output format ->
    edge cases, primacy/recency placement) -- scaled down from its Batch
    Mode multi-agent bundle output to a single final prompt, since this tool
    has exactly one coder call to prepare a prompt for, not a fleet of
    agents needing a bundle with parallel/sequential execution metadata.

    Args:
        task: The user's original free-text task description.
        context_block: The structured context from engineer_context().
        router: Resolves model roles to live candidates.
        client: The multi-provider LLM client to call through.
        on_event: Progress event sink (see engine/calling.py).
        role: Model role to call through -- see engineer_context()'s `role`
            docstring for when to override the "reasoner" default.

    Returns:
        The final engineered prompt text, ready to hand to the coder role.
    """
    user_content = f"Original user request:\n{task}\n\nStructured context:\n{context_block}"
    messages = [
        {"role": "system", "content": PROMPT_ENGINEER_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    raw = call_role(
        role,
        "engineer final prompt",
        messages,
        router,
        client,
        priority="interactive",
        on_event=on_event,
        light_reasoning=True,
        temperature=0.3,
        max_tokens=600,
    )
    return strip_reasoning_trace(raw)


@dataclass(frozen=True)
class RunResult:
    """The full outcome of one orchestrated task run."""

    task: str
    engineered_prompt: str
    language: str
    complexity: str
    plan: str | None
    skill_used: str | None
    agent_used: str | None
    final_files: list[FileSpec]
    passed: bool
    attempts: list[AttemptRecord] = field(default_factory=list)


def detect_language(task: str, router: Router, client: LLMClient, on_event: OnEvent = noop_event) -> str:
    """Infer the target language/stack from the task text (no UI selector needed).

    If the task explicitly names a stack ("...in Java", "a React component"),
    the classifier picks that up directly from the wording. Falls back to
    DEFAULT_LANGUAGE if the model's answer doesn't match a registered adapter.

    Args:
        task: The user's free-text task description.
        router: Resolves model roles to live candidates.
        client: The multi-provider LLM client to call through.
        on_event: Progress event sink (see engine/calling.py).

    Returns:
        One of available_languages().
    """
    options = available_languages()
    messages = [
        {
            "role": "system",
            "content": (
                f"Identify which stack this coding task targets. Respond with "
                f"exactly one word from this list: {', '.join(options)}. "
                f"If genuinely unclear, respond with '{DEFAULT_LANGUAGE}'."
            ),
        },
        {"role": "user", "content": task},
    ]
    raw = call_role(
        "router_fast",
        "detect target language",
        messages,
        router,
        client,
        priority="interactive",
        on_event=on_event,
        temperature=0.0,
        max_tokens=60,
        reasoning_effort="low",
    )
    normalized = raw.strip().lower()
    for option in options:
        if option in normalized:
            return option
    return DEFAULT_LANGUAGE


def classify_complexity(task: str, router: Router, client: LLMClient, on_event: OnEvent = noop_event) -> str:
    """Ask the fast/cheap model a strict simple-vs-complex question.

    Args:
        task: The user's free-text task description.
        router: Resolves model roles to live candidates.
        client: The multi-provider LLM client to call through.
        on_event: Progress event sink (see engine/calling.py).

    Returns:
        Exactly "simple" or "complex".
    """
    messages = [
        {
            "role": "system",
            "content": (
                "Classify the coding task's complexity. Respond with exactly one "
                "word: simple or complex. simple = a single function, small script, "
                "or single component. complex = multiple files, non-trivial "
                "business logic, or explicit multi-step requirements."
            ),
        },
        {"role": "user", "content": task},
    ]
    raw = call_role(
        "router_fast",
        "classify task complexity",
        messages,
        router,
        client,
        priority="interactive",
        on_event=on_event,
        temperature=0.0,
        max_tokens=60,
        reasoning_effort="low",
    )
    return "complex" if "complex" in raw.strip().lower() else "simple"


SOLUTION_ARCHITECT_SYSTEM_PROMPT = (
    "You are a solution architect designing the implementation approach for "
    "ONE coding task before any code is written. Scale your response to "
    "what this specific task actually needs -- do NOT produce enterprise "
    "ceremony (no microservices topology, no capacity/QPS estimation, no "
    "compliance matrix) for a single-script or small-project task; reserve "
    "that depth only if the task's own scale genuinely calls for it. Cover "
    "exactly these sections:\n"
    "FILES: the files to create and each one's responsibility.\n"
    "KEY DESIGN DECISIONS: for each non-trivial choice (data structure, "
    "algorithm, library, pattern) state what you chose, why, and the main "
    "alternative you rejected -- one line each, ADR-style.\n"
    "EDGE CASES: specific inputs/conditions the implementation must handle.\n"
    "RISKS: anything that could make this fail or be wrong.\n"
    "Keep the entire response under 250 words. No code."
)

CONSENSUS_SYSTEM_PROMPT = (
    "You are an architecture validation gate reviewing a solution "
    "architect's blueprint against the original task, before code is "
    "written. Respond in EXACTLY this format:\n"
    "VERDICT: APPROVED or REJECTED\n"
    "REASON: one or two sentences.\n"
    "Reject ONLY for a genuine gap: a requirement from the task the "
    "blueprint doesn't address, an edge case the task clearly implies but "
    "the blueprint omits, or an internally contradictory design decision. "
    "Never reject for style preference or because a smaller/different "
    "approach was also possible."
)


def solution_architect_review(
    task: str,
    language: str,
    router: Router,
    client: LLMClient,
    context: str | None,
    on_event: OnEvent = noop_event,
    revision_feedback: str | None = None,
) -> str:
    """Ask the reasoner (in a solution-architect persona) for a blueprint.

    Scaled-down single-task version of claude-global-library's
    solution-architect agent -- same core discipline (files + responsibility,
    ADR-style decision rationale, edge cases, risks) without the enterprise
    HLD ceremony (capacity estimation, microservices topology, compliance
    matrices) that agent carries for full system-architecture work.

    Args:
        task: The user's free-text task description (the engineered prompt).
        language: Target language/stack key.
        router: Resolves model roles to live candidates.
        client: The multi-provider LLM client to call through.
        context: Optional lightweight file-based context from engine/rag.py.
        on_event: Progress event sink (see engine/calling.py).
        revision_feedback: If set, the consensus gate's rejection reason from
            a prior round -- the architect must address it this time.

    Returns:
        The blueprint text, with any reasoning trace stripped.
    """
    user_content = f"Task: {task}\nTarget stack: {language}."
    if context:
        user_content += f"\n\nRelevant existing project context:\n{context}"
    if revision_feedback:
        user_content += (
            f"\n\nYour previous blueprint was REJECTED by the review gate for this "
            f"reason -- address it directly in this revision:\n{revision_feedback}"
        )
    messages = [
        {"role": "system", "content": SOLUTION_ARCHITECT_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    # The initial proposal is a restructuring task (light_reasoning fits) --
    # the revision pass is closer to diagnose-and-fix (incorporate a
    # rejection reason correctly), so it gets full reasoning depth instead.
    # It fires at most once per complex task, so the extra cost is bounded.
    raw = call_role(
        "reasoner",
        "solution architect blueprint" if not revision_feedback else "revise blueprint after review",
        messages,
        router,
        client,
        priority="interactive",
        on_event=on_event,
        light_reasoning=not revision_feedback,
        temperature=0.2,
        max_tokens=700 if not revision_feedback else 900,
    )
    return strip_reasoning_trace(raw)


def consensus_review(
    task: str,
    blueprint: str,
    router: Router,
    client: LLMClient,
    on_event: OnEvent = noop_event,
    round_number: int = 1,
    extra_instruction: str | None = None,
    role: str = "reasoner",
) -> tuple[bool, str]:
    """Ask the reasoner (in a consensus-agent persona) to approve or reject a blueprint.

    Scaled-down single-task version of claude-global-library's consensus-agent
    -- same core discipline (binary verdict, reject only on a genuine gap,
    never on style preference) without its multi-agent-squad math (POMDP
    belief-state thresholds, token-budget formulas across agent handoffs),
    which has no meaning for a single blueprint reviewed before a single
    coder call.

    Args:
        task: The user's free-text task description (the engineered prompt).
        blueprint: The solution architect's proposed blueprint.
        router: Resolves model roles to live candidates.
        client: The multi-provider LLM client to call through.
        on_event: Progress event sink (see engine/calling.py).
        round_number: 1 for the initial review, 2 for the re-review of a
            revised blueprint -- surfaced in progress events/logs only, so
            the Activity tab can distinguish which round produced a verdict.
        extra_instruction: Optional additional check appended to the
            user-turn content, for callers reviewing a document type
            CONSENSUS_SYSTEM_PROMPT's fixed wording doesn't fully cover --
            e.g. engine/sdlc.py's SRS review asks this to also flag invented
            scope (a requirement with no basis in the raw input), a
            direction the base prompt's "does the blueprint address
            everything" wording doesn't check for. None preserves today's
            behavior exactly (the existing HLD review call site).
        role: Model role to call through -- see engineer_context()'s `role`
            docstring for when to override the "reasoner" default (e.g.
            engine/sdlc.py reviewing SRS/HLD-sized documents).

    Returns:
        (approved, reason) -- approved is True unless the verdict text
        contains "REJECTED"; reason is the full verdict text (reasoning
        trace stripped) for logging/display.
    """
    user_content = f"Task: {task}\n\nProposed blueprint:\n{blueprint}"
    if extra_instruction:
        user_content += f"\n\nAdditional check for this review: {extra_instruction}"
    messages = [
        {"role": "system", "content": CONSENSUS_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    raw = call_role(
        role,
        f"consensus review of blueprint (round {round_number})",
        messages,
        router,
        client,
        priority="interactive",
        on_event=on_event,
        light_reasoning=True,
        temperature=0.0,
        max_tokens=300,
    )
    text = strip_reasoning_trace(raw)
    approved = "REJECTED" not in text.upper()
    return approved, text


def _persona_solution_architect(
    remote_llm: RemoteLLM,
    task: str,
    language: str,
    context: str | None,
    revision_feedback: str | None,
) -> str:
    """Spawned-agent persona mirroring solution_architect_review()'s body.

    Used by run_task's complex-task branch so the propose step runs as a
    genuinely separate OS process (Milestone 1.5) instead of an in-process
    call_role invocation. Same prompt constant, same message shape --
    duplicated here (rather than sharing solution_architect_review directly)
    because RemoteLLM.call_role's signature intentionally has no
    router/client/on_event parameters (those only make sense in the
    coordinator process; see engine/agent_runtime.py).
    """
    user_content = f"Task: {task}\nTarget stack: {language}."
    if context:
        user_content += f"\n\nRelevant existing project context:\n{context}"
    if revision_feedback:
        user_content += (
            f"\n\nYour previous blueprint was REJECTED by the review gate for this "
            f"reason -- address it directly in this revision:\n{revision_feedback}"
        )
    messages = [
        {"role": "system", "content": SOLUTION_ARCHITECT_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    raw = remote_llm.call_role(
        "reasoner",
        "solution architect blueprint" if not revision_feedback else "revise blueprint after review",
        messages,
        light_reasoning=not revision_feedback,
        temperature=0.2,
        max_tokens=700 if not revision_feedback else 900,
    )
    return strip_reasoning_trace(raw)


def _persona_consensus_review(
    remote_llm: RemoteLLM,
    task: str,
    blueprint: str,
    round_number: int,
) -> tuple[bool, str]:
    """Spawned-agent persona mirroring consensus_review()'s body (main pipeline call site).

    No extra_instruction parameter -- the main pipeline's review call site
    never passes one (only engine/sdlc.py's SRS review does); this persona
    only needs to cover the behavior run_task actually exercises.
    """
    user_content = f"Task: {task}\n\nProposed blueprint:\n{blueprint}"
    messages = [
        {"role": "system", "content": CONSENSUS_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    raw = remote_llm.call_role(
        "reasoner",
        f"consensus review of blueprint (round {round_number})",
        messages,
        light_reasoning=True,
        temperature=0.0,
        max_tokens=300,
    )
    text = strip_reasoning_trace(raw)
    approved = "REJECTED" not in text.upper()
    return approved, text


def run_task(
    task: str,
    workdir: Path,
    router: Router,
    client: LLMClient,
    *,
    language: str | None = None,
    use_rag: bool = False,
    project_dir: Path | None = None,
    skill_name: str | None = None,
    agent_name: str | None = None,
    max_heal_attempts: int = 3,
    heal_timeout_seconds: int = 300,
    on_event: OnEvent = noop_event,
) -> RunResult:
    """Run the full orchestrated pipeline for one task.

    Args:
        task: The user's free-text task description.
        workdir: Directory to write generated files into and run tests from.
        router: Resolves model roles to live candidates.
        client: The multi-provider LLM client to call through.
        language: Force a target stack; if None, auto-detected from the task text.
        use_rag: Whether to build lightweight file-based context from project_dir.
        project_dir: Existing project root to search for RAG context.
        skill_name: Force a specific skill by name instead of auto-matching.
        agent_name: Force a specific subagent persona by name.
        max_heal_attempts: Maximum self-heal retries on test failure.
        heal_timeout_seconds: Maximum wall-clock time for the self-heal loop.
        on_event: Progress event sink (see engine/calling.py) -- called for
            every model call, fallback, and self-heal attempt.

    Returns:
        The full RunResult: original task text, the engineered prompt
        actually used downstream, detected language, classification, plan
        (if any), matched skill/agent, final files, pass/fail, and the full
        attempt history.
    """
    context_block = engineer_context(task, router, client, on_event=on_event)
    engineered_task = engineer_prompt(task, context_block, router, client, on_event=on_event)
    on_event({"type": "prompt_engineered", "prompt": engineered_task})

    resolved_language = language or detect_language(engineered_task, router, client, on_event=on_event)
    on_event({"type": "language_detected", "language": resolved_language})

    skills = load_all_skills()
    agents = load_all_agents()

    skill = None
    if skill_name is not None:
        skill = next((s for s in skills if s.name == skill_name), None)
    else:
        skill = match_skill(task, skills, resolved_language)

    subagent: SubAgent | None = get_agent(agent_name, agents) if agent_name else None
    if subagent is None and agent_name is None:
        # Milestone 1.6: prefer the real orchestration decision tree's
        # keyword-scored pattern match (claude-workflow-engine's KGRouter)
        # over silently leaving subagent unset -- fails open to today's
        # behavior (subagent stays None) whenever the sibling repo isn't
        # importable or no confident match was found. See engine/kg_routing.py.
        kg_route = route_persona(engineered_task)
        if kg_route is not None:
            subagent = SubAgent(
                name=kg_route.lead_agent_name,
                description=f"KG-routed lead agent for pattern {kg_route.pattern_id} ({kg_route.domain})",
                role="primary_coder",
                system_prompt=kg_route.persona_markdown,
            )
            on_event(
                {
                    "type": "kg_route_resolved",
                    "domain": kg_route.domain,
                    "pattern_id": kg_route.pattern_id,
                    "lead_agent": kg_route.lead_agent_name,
                    "trace": kg_route.trace,
                }
            )
        else:
            on_event({"type": "kg_route_unavailable", "reason": "no confident KG match or library not importable"})

    context = rag.build_context(engineered_task, project_dir) if use_rag else None

    complexity = classify_complexity(engineered_task, router, client, on_event=on_event)
    on_event({"type": "complexity_classified", "complexity": complexity})

    plan: str | None = None
    if complexity == "complex":
        # Milestone 1.5: propose/review run as genuinely separate OS
        # processes (real agent spawning), funneled through one
        # AgentCoordinator so the shared RateLimiter/Router stay honest --
        # see engine/agent_runtime.py. Bounded 2-round loop, event payloads,
        # and revision-feedback threading are unchanged from before.
        coordinator = AgentCoordinator(router, client, on_event=on_event)
        try:
            process, agent_id = coordinator.spawn_agent(
                _persona_solution_architect, (engineered_task, resolved_language, context, None)
            )
            process.join()
            blueprint = coordinator.await_result(agent_id)
            on_event({"type": "architecture_proposed", "blueprint": blueprint})

            process, agent_id = coordinator.spawn_agent(
                _persona_consensus_review, (engineered_task, blueprint, 1)
            )
            process.join()
            approved, verdict = coordinator.await_result(agent_id)
            on_event({"type": "consensus_verdict", "round": 1, "approved": approved, "reason": verdict})

            if not approved:
                process, agent_id = coordinator.spawn_agent(
                    _persona_solution_architect, (engineered_task, resolved_language, context, verdict)
                )
                process.join()
                blueprint = coordinator.await_result(agent_id)
                on_event({"type": "architecture_revised", "blueprint": blueprint})

                # Bounded re-review: at most one more round on the revision, then
                # proceed regardless (self-heal on the actual code is the final
                # backstop, not an unbounded architect<->consensus negotiation).
                process, agent_id = coordinator.spawn_agent(
                    _persona_consensus_review, (engineered_task, blueprint, 2)
                )
                process.join()
                approved, verdict = coordinator.await_result(agent_id)
                on_event({"type": "consensus_verdict", "round": 2, "approved": approved, "reason": verdict})
        finally:
            coordinator.stop()

        plan = blueprint
        context = f"{context}\n\nImplementation plan:\n{plan}" if context else f"Implementation plan:\n{plan}"

    if complexity == "complex":
        manifest = None
        groups = None
        try:
            manifest = parallel_generate.plan_file_manifest(
                engineered_task, resolved_language, context, router, client, on_event=on_event
            )
            groups = parallel_generate._partition_manifest(manifest)
        except GenerationError as exc:
            # A manifest-planning failure must not fail the whole task --
            # fall back to today's reliable single-call path.
            on_event({"type": "manifest_planning_failed", "reason": str(exc)})

        if manifest and len(manifest) > parallel_generate.PARALLEL_FILE_THRESHOLD and len(groups) > 1:
            artifact: GeneratedArtifact = parallel_generate.generate_parallel(
                engineered_task,
                resolved_language,
                manifest,
                groups,
                router,
                client,
                context=context,
                skill=skill,
                subagent=subagent,
                on_event=on_event,
            )
        else:
            artifact = generate_module.generate(
                engineered_task,
                resolved_language,
                router,
                client,
                context=context,
                skill=skill,
                subagent=subagent,
                priority="interactive",
                on_event=on_event,
            )
    else:
        artifact = generate_module.generate(
            engineered_task,
            resolved_language,
            router,
            client,
            context=context,
            skill=skill,
            subagent=subagent,
            priority="interactive",
            on_event=on_event,
        )
    write_files(workdir, artifact.files)
    result: ExecutionResult = run_tests(workdir, resolved_language)
    on_event({"type": "tests_run", "attempt": 0, "passed": result.passed})
    attempts = [AttemptRecord(attempt=0, files=artifact.files, result=result)]

    if result.passed:
        return RunResult(
            task=task,
            engineered_prompt=engineered_task,
            language=resolved_language,
            complexity=complexity,
            plan=plan,
            skill_used=skill.name if skill else None,
            agent_used=subagent.name if subagent else None,
            final_files=artifact.files,
            passed=True,
            attempts=attempts,
        )

    heal_result: HealResult = self_heal_module.heal(
        engineered_task,
        resolved_language,
        workdir,
        artifact.files,
        result,
        router,
        client,
        max_attempts=max_heal_attempts,
        timeout_seconds=heal_timeout_seconds,
        coder_subagent=subagent,
        reasoner_subagent=subagent if subagent and subagent.role == "reasoner" else None,
        on_event=on_event,
    )
    return RunResult(
        task=task,
        engineered_prompt=engineered_task,
        language=resolved_language,
        complexity=complexity,
        plan=plan,
        skill_used=skill.name if skill else None,
        agent_used=subagent.name if subagent else None,
        final_files=heal_result.final_files,
        passed=heal_result.passed,
        attempts=attempts + heal_result.attempts,
    )
