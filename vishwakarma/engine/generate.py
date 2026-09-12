"""Generates code and its tests in a single call to the primary coder model.

Per the ai-engineer review, tests are requested in the SAME call as the code
(same model, same context) rather than a separate test-writing call to a
different model -- this preserves the coder's own reasoning about its
implementation choices and halves baseline RPM usage.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from vishwakarma.engine.calling import OnEvent, call_role, noop_event
from vishwakarma.llm_client import LLMClient
from vishwakarma.plugins import Skill, SubAgent
from vishwakarma.router import Router

MAX_CODER_TOKENS = 8000
"""Generous completion budget for the coder call. Groq's gpt-oss models spend
part of their budget on an internal reasoning/analysis pass before emitting
the structured JSON payload -- too low a cap truncates the JSON mid-string
(observed as "Unterminated string" JSONDecodeErrors) rather than failing
cleanly, so this is set well above what a typical few-file generation needs."""

RESPONSE_CONTRACT = (
    'Respond with ONLY a JSON object of the exact shape '
    '{"files": [{"path": "relative/file/path", "content": "full file content"}]} '
    "-- no prose, no markdown code fences, no explanation outside the JSON."
)


class GenerationError(Exception):
    """Raised when the model's response cannot be parsed into files."""


@dataclass(frozen=True)
class FileSpec:
    """One generated file: its relative path and full content."""

    path: str
    content: str


@dataclass(frozen=True)
class GeneratedArtifact:
    """The set of files produced by one coder call."""

    files: list[FileSpec]


def _build_system_prompt(language: str, skill: Skill | None, subagent: SubAgent | None) -> str:
    """Compose the coder's system prompt from the base contract + optional plugins."""
    parts = [
        "You are an expert software engineer generating production code and "
        "its own tests together in one response.",
        f"Target language/stack: {language}.",
        RESPONSE_CONTRACT,
    ]
    if skill is not None:
        parts.append(f"Stack-specific guidance ({skill.name}):\n{skill.prompt_addition}")
    if subagent is not None and subagent.role == "primary_coder":
        parts.append(f"Persona override ({subagent.name}):\n{subagent.system_prompt}")
    return "\n\n".join(parts)


def _extract_json(text: str) -> dict:
    """Parse the model's response into a dict, tolerating markdown code fences.

    Args:
        text: The raw model response content.

    Returns:
        The parsed JSON object.

    Raises:
        GenerationError: If the text is not valid JSON after fence-stripping.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:]
        stripped = stripped.strip()

    try:
        return json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise GenerationError(f"Model response was not valid JSON: {exc}") from exc


def _parse_files_json(raw: str) -> list[FileSpec]:
    """Parse a coder response's raw text into a validated list of FileSpecs.

    Extracted from request_files_from_coder so engine/parallel_generate.py
    can validate a subset-scoped coder response identically, without
    duplicating this logic.

    Raises:
        GenerationError: If the response cannot be parsed into a non-empty
            files list.
    """
    try:
        parsed = _extract_json(raw)
    except GenerationError as exc:
        raise GenerationError(
            f"{exc} (response was {len(raw)} chars -- if this looks truncated, "
            f"the task may need to be split into smaller pieces)"
        ) from exc
    files_raw = parsed.get("files")
    if not isinstance(files_raw, list) or not files_raw:
        raise GenerationError("Model response JSON did not contain a non-empty 'files' list")

    return [FileSpec(path=item["path"], content=item["content"]) for item in files_raw]


def request_files_from_coder(
    system_prompt: str,
    user_content: str,
    router: Router,
    client: LLMClient,
    priority: str = "interactive",
    purpose: str = "generate code + tests",
    on_event: OnEvent = noop_event,
) -> GeneratedArtifact:
    """Call the primary coder role and parse its JSON response into files.

    Shared by generate() (fresh generation) and engine/self_heal.py (fix
    requests), so both go through the same JSON contract and fallback logic.

    Args:
        system_prompt: The full system prompt for this call.
        user_content: The user-turn content (task, context, or fix request).
        router: Resolves the primary_coder role to a live candidate.
        client: The multi-provider LLM client to call through.
        priority: Rate-limiter priority tier for this call.
        purpose: Short human-readable reason, surfaced in progress events.
        on_event: Progress event sink (see engine/calling.py).

    Returns:
        The parsed GeneratedArtifact.

    Raises:
        GenerationError: If the response cannot be parsed into a non-empty
            files list.
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    raw = call_role(
        "primary_coder",
        purpose,
        messages,
        router,
        client,
        priority=priority,
        on_event=on_event,
        temperature=0.2,
        max_tokens=MAX_CODER_TOKENS,
    )

    files = _parse_files_json(raw)
    return GeneratedArtifact(files=files)


def generate(
    task: str,
    language: str,
    router: Router,
    client: LLMClient,
    context: str | None = None,
    skill: Skill | None = None,
    subagent: SubAgent | None = None,
    priority: str = "interactive",
    on_event: OnEvent = noop_event,
) -> GeneratedArtifact:
    """Generate code + tests for a task in one coder call.

    Args:
        task: The user's free-text task description.
        language: Target language/stack key (matches a registered adapter).
        router: Resolves model roles to live candidates.
        client: The multi-provider LLM client to call through.
        context: Optional lightweight file-based context from engine/rag.py.
        skill: Optional matched Skill to steer stack-specific idioms.
        subagent: Optional SubAgent persona override for the coder role.
        priority: Rate-limiter priority tier ("interactive" for a fresh request).
        on_event: Progress event sink (see engine/calling.py).

    Returns:
        The generated files (code + tests).
    """
    system_prompt = _build_system_prompt(language, skill, subagent)
    user_content = task
    if context:
        user_content += f"\n\nRelevant existing project context:\n{context}"
    return request_files_from_coder(
        system_prompt,
        user_content,
        router,
        client,
        priority=priority,
        purpose="generate code + tests",
        on_event=on_event,
    )
