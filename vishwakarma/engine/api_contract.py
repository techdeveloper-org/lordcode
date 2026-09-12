"""Milestone 5: OpenAPI 3.1 contract generation from the HLD + a joint
SRS/HLD/API consistency check, reusing sdlc.py's existing consensus-review
persona rather than inventing a parallel verdict-generation mechanism.

Not every Vishwakarma project has an HTTP API surface (most live examples
this session were plain CLI tools: contact book, palindrome checker,
stopwatch, todo list) -- forcing OpenAPI generation onto every project would
be exactly the kind of invented scope the SRS review (Milestone 1
Refinement) exists to catch on the SRS side. generate_api_contract() gates
on a cheap, deterministic keyword check against the HLD text rather than an
LLM classification call -- explicitly a semantic-classification heuristic
over free-form architect prose, NOT a structural-compliance check like
documentation.py's _has_mermaid_fence()/_missing_headings() (which verify a
model literally emitted a required marker); false positives/negatives are
possible and accepted given the human-reviewed STOP-gate backstop.

Explicitly out of scope, not silently dropped: claude-global-library's own
API_CONTRACT_PIPELINE.md calls for enforced FR-NNN -> operationId structural
traceability. This milestone's Joint Validation is a single advisory binary
verdict, not a structured traceability artifact -- the same "scale down
enterprise ceremony" precedent documentation.py already names explicitly
for its 9 deferred diagram types.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from vishwakarma.engine.agent_runtime import AgentCoordinator, RemoteLLM
from vishwakarma.engine.calling import OnEvent, noop_event
from vishwakarma.engine.generate import GenerationError
from vishwakarma.engine.reasoning_utils import strip_reasoning_trace
from vishwakarma.engine.sdlc import _persona_consensus_review, hld_path_for
from vishwakarma.llm_client import LLMClient
from vishwakarma.router import Router

JOINT_VALIDATION_HEADING = "## Joint Validation"
RECONCILIATION_HEADING = "## Full-Stack Reconciliation"

_RECONCILIATION_INSTRUCTION = (
    "Also flag any HLD component or SRS requirement that clearly implies a "
    "specific visual/UI treatment (e.g. a described dark theme, a specific "
    "typography scale, a stated brand color) that these extracted Figma "
    "design tokens contradict or fail to reflect, and any design token with "
    "no traceable basis in the HLD's design or the SRS's requirements."
)

_API_SURFACE_KEYWORDS = (
    "endpoint", "rest api", "http api", " route", "controller",
    "fastapi", "flask", "express", "webapp",
)

_API_CONTRACT_INSTRUCTION = (
    "Also flag any API path/operation with no traceable basis in the HLD's "
    "design or the SRS's functional requirements, and any HLD component or "
    "SRS requirement that clearly implies an API operation the spec omits."
)

_OPENAPI_SYSTEM_PROMPT = (
    "You are producing an OpenAPI 3.1 specification for ONE coding task, "
    "given its approved SRS and HLD. Derive paths, operations, and schemas "
    "from the HLD's file/endpoint design and the SRS's functional "
    "requirements -- do not invent endpoints with no basis in either "
    "document. Output ONLY a valid OpenAPI 3.1 YAML document: the top-level "
    "'openapi' field must be '3.1.0' (or another 3.1.x version), and a "
    "'paths' object is required. Output raw YAML text only -- no prose "
    "before or after it, no markdown code fence."
)


def _hld_describes_api_surface(hld: str) -> bool:
    """Cheap keyword heuristic for whether the HLD describes an HTTP API.

    A semantic-classification guess over free-form prose, not a structural
    check -- false positives/negatives are possible and accepted, same
    trade-off already made elsewhere in this pipeline for a personal,
    human-reviewed tool.
    """
    lowered = hld.lower()
    return any(keyword in lowered for keyword in _API_SURFACE_KEYWORDS)


def _persona_generate_openapi_spec(remote_llm: RemoteLLM, srs: str, hld: str) -> str:
    """Spawned-agent persona that generates the OpenAPI spec body."""
    messages = [
        {"role": "system", "content": _OPENAPI_SYSTEM_PROMPT},
        {"role": "user", "content": f"SRS:\n{srs}\n\nHLD:\n{hld}"},
    ]
    raw = remote_llm.call_role(
        "fallback_long_context", "generate OpenAPI contract (Phase 1.5)", messages,
        light_reasoning=True, temperature=0.2, max_tokens=2000,
    )
    return strip_reasoning_trace(raw)


def _strip_yaml_fence(text: str) -> str:
    """Strip a leading/trailing ```yaml ... ``` fence, if the model added one.

    The persona prompt says "no markdown code fence"; self-reported LLM
    compliance is not a control (same discipline as documentation.py's
    _has_mermaid_fence()), so a fenced-but-otherwise-valid response is
    tolerated rather than treated as fatally malformed.
    """
    match = re.match(r"^\s*```(?:yaml)?\s*\n(.*?)\n\s*```\s*$", text, re.DOTALL)
    return match.group(1) if match else text


def _is_valid_openapi_spec(text: str) -> tuple[bool, str]:
    """Validate (fence-stripped) text as a minimal OpenAPI 3.1 document.

    Returns (is_valid, fence_stripped_text) -- the stripped text is what
    callers should persist, regardless of validity, so a caller inspecting
    a failure sees the same text validation actually ran against.
    """
    stripped = _strip_yaml_fence(text)
    try:
        parsed = yaml.safe_load(stripped)
        # Require `paths` to be a genuinely non-empty mapping, not just a
        # present key -- YAML silently collapses duplicate top-level keys to
        # their LAST value, so a degenerate response that repeats
        # "paths: {}" after real content (observed live: a rate-limited
        # fallback model looping at the end of its output) would otherwise
        # parse as "technically has a paths key" while the real content is
        # discarded. Self-reported LLM compliance is not a control.
        valid = (
            isinstance(parsed, dict)
            and str(parsed.get("openapi", "")).startswith("3.1")
            and isinstance(parsed.get("paths"), dict)
            and len(parsed["paths"]) > 0
        )
    except yaml.YAMLError:
        valid = False
    return valid, stripped


def api_contract_path_for(workdir: Path) -> Path:
    """Return the conventional openapi.yaml path for a workdir.

    Matches claude-global-library's API_CONTRACT_PIPELINE.md convention
    exactly (docs/phase-1-api-contracts/), and Milestone 1's own
    docs/phase-N-name/ shape (srs_path_for/hld_path_for).
    """
    return workdir / "docs" / "phase-1-api-contracts" / "openapi.yaml"


def generate_api_contract(
    srs: str,
    hld: str,
    workdir: Path,
    router: Router,
    client: LLMClient,
    on_event: OnEvent = noop_event,
) -> str | None:
    """Generate an OpenAPI 3.1 contract from the HLD, if it describes an API.

    Args:
        srs: The approved SRS.md content.
        hld: The approved HLD.md content.
        workdir: Project directory; the spec is written under its docs/ tree.
        router: Resolves model roles to live candidates.
        client: The multi-provider LLM client to call through.
        on_event: Progress event sink (see engine/calling.py).

    Returns:
        The generated OpenAPI YAML text, or None if the HLD doesn't appear
        to describe an API surface (no model call is made in that case).

    Raises:
        GenerationError: If the model's response isn't a valid OpenAPI 3.1
            document even after fence-stripping.
    """
    if not _hld_describes_api_surface(hld):
        on_event({"type": "api_contract_skipped", "reason": "no API surface described in HLD"})
        return None

    coordinator = AgentCoordinator(router, client, on_event=on_event)
    try:
        process, agent_id = coordinator.spawn_agent(_persona_generate_openapi_spec, (srs, hld))
        process.join()
        raw = coordinator.await_result(agent_id)
    finally:
        coordinator.stop()

    valid, spec = _is_valid_openapi_spec(raw)
    if not valid:
        raise GenerationError("Generated API contract is not a valid OpenAPI 3.1 document")

    contract_path = api_contract_path_for(workdir)
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_text(spec, encoding="utf-8")
    on_event({"type": "api_contract_generated"})
    return spec


def run_joint_validation(
    srs: str,
    hld: str,
    api_spec: str,
    workdir: Path,
    router: Router,
    client: LLMClient,
    on_event: OnEvent = noop_event,
) -> str:
    """Cross-check SRS/HLD/API consistency, appending the verdict to HLD.md.

    Reuses sdlc.py's existing _persona_consensus_review (see module
    docstring) rather than a new persona -- SRS+HLD are concatenated as the
    "task" context, the API spec is the "blueprint" under review, with an
    extra_instruction covering the API-specific traceability direction
    CONSENSUS_SYSTEM_PROMPT's fixed wording doesn't already check.

    Args:
        srs: The approved SRS.md content.
        hld: The approved HLD.md content (without a Joint Validation section yet).
        api_spec: The generated OpenAPI contract text.
        workdir: Project directory; HLD.md is read from/written to its docs/ tree.
        router: Resolves model roles to live candidates.
        client: The multi-provider LLM client to call through.
        on_event: Progress event sink (see engine/calling.py).

    Returns:
        The full HLD.md content including the new trailing section.

    Raises:
        GenerationError: If HLD.md already has a Joint Validation section.
    """
    if JOINT_VALIDATION_HEADING in hld:
        raise GenerationError(
            "Joint Validation already present in HLD.md -- delete that section manually to regenerate it."
        )

    task = f"SRS:\n{srs}\n\nHLD:\n{hld}"
    coordinator = AgentCoordinator(router, client, on_event=on_event)
    try:
        process, agent_id = coordinator.spawn_agent(
            _persona_consensus_review, (task, api_spec, 1, _API_CONTRACT_INSTRUCTION)
        )
        process.join()
        approved, verdict = coordinator.await_result(agent_id)
    finally:
        coordinator.stop()

    on_event({"type": "joint_validation_verdict", "approved": approved, "reason": verdict})
    hld_with_validation = (
        f"{hld}\n\n{JOINT_VALIDATION_HEADING}\n\n"
        f"**Verdict:** {'APPROVED' if approved else 'REJECTED'}\n\n{verdict}\n"
    )

    hld_path_for(workdir).write_text(hld_with_validation, encoding="utf-8")
    return hld_with_validation


def run_full_stack_reconciliation(
    srs: str,
    hld: str,
    design_tokens: dict,
    workdir: Path,
    router: Router,
    client: LLMClient,
    on_event: OnEvent = noop_event,
) -> str:
    """Cross-check SRS/HLD against extracted Figma design tokens, appending
    the verdict to HLD.md as a third trailing section.

    Reuses sdlc.py's existing _persona_consensus_review, same shape as
    run_joint_validation but with the design tokens JSON as the blueprint
    instead of an API spec. Section ordering relative to '## Joint
    Validation' is best-effort, driven by which sdlc command the user runs
    last -- this guard only checks for its own heading.

    Args:
        srs: The approved SRS.md content.
        hld: The approved HLD.md content (current on-disk content, which may
            already include a Joint Validation section).
        design_tokens: The parsed docs/phase-3-design/design_tokens.json dict.
        workdir: Project directory; HLD.md is read from/written to its docs/ tree.
        router: Resolves model roles to live candidates.
        client: The multi-provider LLM client to call through.
        on_event: Progress event sink (see engine/calling.py).

    Returns:
        The full HLD.md content including the new trailing section.

    Raises:
        GenerationError: If HLD.md already has a Full-Stack Reconciliation section.
    """
    if RECONCILIATION_HEADING in hld:
        raise GenerationError(
            "Full-Stack Reconciliation already present in HLD.md -- delete that section manually to regenerate it."
        )

    task = f"SRS:\n{srs}\n\nHLD:\n{hld}"
    blueprint = json.dumps(design_tokens, indent=2)
    coordinator = AgentCoordinator(router, client, on_event=on_event)
    try:
        process, agent_id = coordinator.spawn_agent(
            _persona_consensus_review, (task, blueprint, 1, _RECONCILIATION_INSTRUCTION)
        )
        process.join()
        approved, verdict = coordinator.await_result(agent_id)
    finally:
        coordinator.stop()

    on_event({"type": "full_stack_reconciliation_verdict", "approved": approved, "reason": verdict})
    hld_with_reconciliation = (
        f"{hld}\n\n{RECONCILIATION_HEADING}\n\n"
        f"**Verdict:** {'APPROVED' if approved else 'REJECTED'}\n\n{verdict}\n"
    )

    hld_path_for(workdir).write_text(hld_with_reconciliation, encoding="utf-8")
    return hld_with_reconciliation
