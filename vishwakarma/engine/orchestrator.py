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
from vishwakarma.engine import knowledge
from vishwakarma.engine.agent_runtime import AgentCoordinator, RemoteLLM
from vishwakarma.engine.calling import OnEvent, call_role, noop_event
from vishwakarma.engine.dag_executor import (
    SPAWN_KEY,
    UPSTREAM_KEY,
    CoordinatorExecutor,
    FailureClass,
    Outcome,
    NodeFailure,
    NodeSpec,
    Phase,
    Topology,
    run_dag,
)
from vishwakarma.engine.executor import ExecutionResult, run_tests, write_files
from vishwakarma.engine.generate import FileSpec, GeneratedArtifact, GenerationError
from vishwakarma.engine.personas import persona_for_role
from vishwakarma.engine.reasoning_utils import strip_reasoning_trace
from vishwakarma.engine.self_heal import AttemptRecord, HealResult
from vishwakarma.languages import available_languages
from vishwakarma.config import ConfigError
from vishwakarma.llm_client import LLMClient
from vishwakarma.engine.personas import SubAgent
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
    "handled, (5) the expected output format -- this section MUST explicitly "
    "state that the coder is to produce BOTH the implementation file(s) AND "
    "a test file covering them, as separate named files; never describe an "
    "output shape that mentions only the implementation. Place the single most "
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
        light_reasoning=True,
        temperature=0.0,
        max_tokens=60,
    )
    normalized = strip_reasoning_trace(raw).strip().lower()
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
        light_reasoning=True,
        temperature=0.0,
        max_tokens=60,
    )
    return "complex" if "complex" in strip_reasoning_trace(raw).strip().lower() else "simple"


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


PHASE_ARCHITECTURE = "phase:A"
PHASE_VALIDATION = "phase:2"
PHASE_IMPLEMENTATION = "phase:B"
PHASE_QA = "phase:D"

PHASE_GROUPS = {
    PHASE_ARCHITECTURE: "main-pipeline",
    PHASE_VALIDATION: "pre-processing",
    PHASE_IMPLEMENTATION: "main-pipeline",
    PHASE_QA: "main-pipeline",
}

PHASE_DEPENDENCIES = {
    PHASE_ARCHITECTURE: (),
    PHASE_VALIDATION: (PHASE_ARCHITECTURE,),
    PHASE_IMPLEMENTATION: (PHASE_VALIDATION,),
    PHASE_QA: (PHASE_IMPLEMENTATION,),
}
"""The four phases run_task implements, using the library's own phase ids.

A subgraph of kgf's authored 44-phase topology, not a parallel invention: the
ids, their groups and their order all come from there, and the topology test
proves each id still exists in the library's phases.json. The other 40 phases
have no implementation in this tool yet, so they are absent rather than
stubbed -- a stub that returns nothing would schedule and then silently
contribute nothing.
"""


@dataclass
class RunRuntime:
    """Parent-side handles for phases that cannot run in a child process.

    Never enters `NodeSpec.state` and is therefore never pickled. A Router
    holds an LLMClient which holds live provider sessions; shipping one into a
    spawned child would either fail to pickle or hand the child a duplicate
    rate limiter, which is the same defect M10 documents in llm_client's
    unlocked `_limiters` dict.
    """

    router: Router
    client: LLMClient
    workdir: Path
    subagent: SubAgent | None = None
    on_event: OnEvent = noop_event


def _node_architecture(remote_llm: RemoteLLM, spec) -> str:
    """phase:A -- propose an implementation blueprint in its own process."""
    state = spec.state
    return _persona_solution_architect(
        remote_llm,
        state["task"],
        state["language"],
        state.get("context"),
        None,
    )


def _node_validation(remote_llm: RemoteLLM, spec) -> dict:
    """phase:2 -- joint blueprint validation, with one bounded revision round.

    The revise-then-re-review round is held INSIDE this node rather than
    expressed as graph edges, for the reason traversal.md:312 gives about
    self-correction: a recovery loop belongs to the runtime, and as edges it
    would make the graph cyclic. Bounded at a single revision, exactly as the
    hardcoded path it replaces was, because self-heal on the real code is the
    final backstop rather than an unbounded architect-versus-reviewer
    negotiation.
    """
    state = spec.state
    blueprint = state.get(UPSTREAM_KEY, {}).get(PHASE_ARCHITECTURE, "")
    if not blueprint:
        raise NodeFailure(
            "validation has no blueprint to validate",
            failure_class=FailureClass.PERMANENT,
        )

    approved, verdict = _persona_consensus_review(remote_llm, state["task"], blueprint, 1)
    rounds = [{"round": 1, "approved": approved, "verdict": verdict}]

    if not approved:
        blueprint = _persona_solution_architect(
            remote_llm,
            state["task"],
            state["language"],
            state.get("context"),
            verdict,
        )
        approved, verdict = _persona_consensus_review(remote_llm, state["task"], blueprint, 2)
        rounds.append({"round": 2, "approved": approved, "verdict": verdict})

    return {"blueprint": blueprint, "approved": approved, "verdict": verdict, "rounds": rounds}


def _node_implementation(runtime: RunRuntime, spec) -> dict:
    """phase:B -- generate the files, in parallel when the manifest earns it.

    Runs in the parent because it spawns agents of its own through
    parallel_generate; a spawned implementation node would be nesting spawn
    inside spawn, forking the coordinator and its dispatcher thread with it.
    """
    state = spec.state
    validation = state.get(UPSTREAM_KEY, {}).get(PHASE_VALIDATION) or {}
    plan = validation.get("blueprint") or None

    context = state.get("context")
    if plan:
        context = f"{context}\n\nImplementation plan:\n{plan}" if context else f"Implementation plan:\n{plan}"

    artifact = None
    if state.get("parallel_allowed"):
        manifest = None
        groups = None
        try:
            manifest = parallel_generate.plan_file_manifest(
                state["task"], state["language"], context, runtime.router, runtime.client,
                on_event=runtime.on_event,
            )
            groups = parallel_generate._partition_manifest(manifest)
        except GenerationError as exc:
            runtime.on_event({"type": "manifest_planning_failed", "reason": str(exc)})

        if manifest and len(manifest) > parallel_generate.PARALLEL_FILE_THRESHOLD and len(groups) > 1:
            artifact = parallel_generate.generate_parallel(
                state["task"],
                state["language"],
                manifest,
                groups,
                runtime.router,
                runtime.client,
                context=context,
                subagent=runtime.subagent,
                on_event=runtime.on_event,
            )

    if artifact is None:
        artifact = generate_module.generate(
            state["task"],
            state["language"],
            runtime.router,
            runtime.client,
            context=context,
            subagent=runtime.subagent,
            priority="interactive",
            on_event=runtime.on_event,
        )

    return {"artifact": artifact, "context": context, "plan": plan}


def _node_qa(runtime: RunRuntime, spec) -> dict:
    """phase:D -- write the generated files out and run the tests.

    In the parent because it touches the workdir and the language adapters,
    neither of which is worth shipping through a pickle.
    """
    implementation = spec.state.get(UPSTREAM_KEY, {}).get(PHASE_IMPLEMENTATION) or {}
    artifact = implementation.get("artifact")
    if artifact is None:
        raise NodeFailure(
            "qa has no artifact to test",
            failure_class=FailureClass.PERMANENT,
        )
    write_files(runtime.workdir, artifact.files)
    result = run_tests(runtime.workdir, spec.state["language"])
    runtime.on_event({"type": "tests_run", "attempt": 0, "passed": result.passed})
    return {"result": result, "artifact": artifact}


PHASE_FUNCTIONS = {
    PHASE_ARCHITECTURE: _node_architecture,
    PHASE_VALIDATION: _node_validation,
    PHASE_IMPLEMENTATION: _node_implementation,
    PHASE_QA: _node_qa,
}

IN_PARENT_PHASES = frozenset({PHASE_IMPLEMENTATION, PHASE_QA})


def _tpm_budget(router: Router, client: LLMClient) -> int:
    """The token-per-minute ceiling the coder role will be admitted under.

    Read from the provider backing primary_coder's currently active candidate,
    because that is the bucket a generate call competes for. The providers live
    on the CLIENT rather than on the Router: Config holds both, but ModelConfig
    carries only roles and limits, so asking the router for them silently
    yields nothing.

    Zero when the provider declares no tpm_budget, which disables the cap
    rather than inventing one -- a local runtime has no meaningful
    tokens-per-minute limit and pacing it for an imagined ceiling would be
    worse than not pacing it at all.
    """
    providers = getattr(client, "_providers", None)
    if not providers:
        return 0
    try:
        candidate = router.resolve("primary_coder")
    except ConfigError:
        return 0
    provider = providers.get(candidate.provider)
    return (provider.tpm_budget or 0) if provider is not None else 0


def _phase_failure(report) -> str:
    """Explain why a phase run produced no artifact, naming every phase.

    Written out in full because the first version of this message reported
    only the QA and implementation phases' own `error`, and a phase that was
    SKIPPED carries no error at all -- so a failure two levels upstream
    surfaced as "did not complete:" with nothing after the colon.
    """
    parts: list[str] = []
    for label, result in report.results.items():
        if result.outcome is Outcome.COMPLETED:
            continue
        if result.outcome is Outcome.SKIPPED:
            parts.append(f"{label} skipped because {result.skipped_because} did not complete")
        else:
            reason = result.error or "no reason recorded"
            parts.append(f"{label} failed ({result.failure_class or 'unclassified'}): {reason}")
    return "; ".join(parts) if parts else "no phase produced an artifact"


def _phase_topology() -> Topology:
    """The four implemented phases as a Topology, so pruning splices properly.

    Built on kgf's own Topology rather than a local dict so that dropping a
    phase rewires its dependents onto its dependencies. Removing a node and
    leaving the dangling edge was measured to be wrong in M5: it floated
    phase:F.1 to level 0, scheduling a security audit before implementation.
    Here the same defect would let implementation start with no blueprint.
    """
    return Topology(
        phases={
            phase_id: Phase(
                id=phase_id,
                group=PHASE_GROUPS[phase_id],
                depends_on=frozenset(dependencies),
            )
            for phase_id, dependencies in PHASE_DEPENDENCIES.items()
        }
    )


def _phase_specs(
    pruned: tuple[str, ...],
    *,
    task: str,
    language: str,
    context: str | None,
    parallel_allowed: bool,
) -> list[NodeSpec]:
    """One NodeSpec per surviving phase, carrying only picklable state."""
    specs: list[NodeSpec] = []
    for phase_id in PHASE_DEPENDENCIES:
        if phase_id in pruned:
            continue
        state = {
            "task": task,
            "language": language,
            "context": context,
            "parallel_allowed": parallel_allowed,
            SPAWN_KEY: phase_id not in IN_PARENT_PHASES,
        }
        specs.append(NodeSpec(label=phase_id, node_type=phase_id, state=state))
    return specs


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
    intent: str = "implement",
    context_budget_tokens: int = 2000,
    library: Path | None = None,
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
        skill_name: Put one library skill at the front of the closure, so it
            is first to earn context budget. There is no auto-matching left to
            override: selection is the graph's job now.
        agent_name: Force a specific agent persona by name, skipping ranking.
            Its closure and context are still built, so forcing an agent does
            not mean forcing a truncated description.
        max_heal_attempts: Maximum self-heal retries on test failure.
        heal_timeout_seconds: Maximum wall-clock time for the self-heal loop.
        intent: What the assembled context is for -- implement, design or
            review. Decides which document sections earn their tokens.
        context_budget_tokens: Ceiling for the assembled knowledge context.
        library: claude-global-library root; None discovers the sibling
            directory.
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

    selection = knowledge.resolve(
        engineered_task,
        intent=intent,
        budget_tokens=context_budget_tokens,
        forced_agent=agent_name,
        forced_skill=skill_name,
        library=library,
        on_event=on_event,
    )

    subagent: SubAgent | None = None
    if selection.has_persona:
        subagent = SubAgent(
            name=selection.agent_name,
            description=f"kgf-selected lead agent for {selection.domain} (confidence {selection.confidence:.3f})",
            role=selection.role,
            system_prompt=selection.context_text,
        )

    context = rag.build_context(engineered_task, project_dir) if use_rag else None
    if subagent is None and selection.context_text and selection.selected:
        context = f"{context}\n\n{selection.context_text}" if context else selection.context_text

    complexity = classify_complexity(engineered_task, router, client, on_event=on_event)
    on_event({"type": "complexity_classified", "complexity": complexity})

    pruned = () if complexity == "complex" else (PHASE_ARCHITECTURE, PHASE_VALIDATION)
    topology = _phase_topology()
    specs = _phase_specs(
        pruned,
        task=engineered_task,
        language=resolved_language,
        context=context,
        parallel_allowed=complexity == "complex",
    )

    runtime = RunRuntime(
        router=router,
        client=client,
        workdir=workdir,
        subagent=subagent,
        on_event=on_event,
    )

    coordinator = AgentCoordinator(router, client, on_event=on_event)
    try:
        executor = CoordinatorExecutor(coordinator, PHASE_FUNCTIONS, runtime, on_event=on_event)
        report = run_dag(
            specs,
            topology.effective_edges(pruned),
            executor,
            tpm_budget=_tpm_budget(router, client),
            on_event=on_event,
        )
    finally:
        coordinator.stop()

    on_event(
        {
            "type": "phases_completed",
            "levels": report.levels,
            "completed": list(report.completed),
            "failed": list(report.failed),
            "skipped": list(report.skipped),
        }
    )

    validation = report.values().get(PHASE_VALIDATION) or {}
    plan = validation.get("blueprint")
    for entry in validation.get("rounds", ()):
        on_event({"type": "consensus_verdict", **entry})

    qa = report.values().get(PHASE_QA)
    if qa is None:
        raise GenerationError(f"implementation phases did not complete: {_phase_failure(report)}")

    artifact = qa["artifact"]
    result: ExecutionResult = qa["result"]
    attempts = [AttemptRecord(attempt=0, files=artifact.files, result=result)]

    if result.passed:
        return RunResult(
            task=task,
            engineered_prompt=engineered_task,
            language=resolved_language,
            complexity=complexity,
            plan=plan,
            skill_used=skill_name,
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
        reasoner_subagent=persona_for_role(subagent, "reasoner", on_event),
        on_event=on_event,
    )
    return RunResult(
        task=task,
        engineered_prompt=engineered_task,
        language=resolved_language,
        complexity=complexity,
        plan=plan,
        skill_used=skill_name,
        agent_used=subagent.name if subagent else None,
        final_files=heal_result.final_files,
        passed=heal_result.passed,
        attempts=attempts + heal_result.attempts,
    )
