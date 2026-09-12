"""Self-heal loop: diagnose a failing test with the reasoner, then re-fix with the coder.

Per the ai-engineer review, the retry prompt carries the actual test file
content plus the accumulated history of prior failed attempts (capped at the
last 2), so the reasoner is explicitly told which fixes already failed --
this avoids the classic self-heal oscillation between the same wrong fixes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from vishwakarma.engine.calling import OnEvent, call_role, noop_event
from vishwakarma.engine.executor import ExecutionResult, run_tests, write_files
from vishwakarma.engine.generate import FileSpec, GenerationError, request_files_from_coder
from vishwakarma.engine.reasoning_utils import strip_reasoning_trace
from vishwakarma.llm_client import LLMClient
from vishwakarma.plugins import SubAgent
from vishwakarma.router import Router

HISTORY_LIMIT = 2

MAX_FILE_CHARS_IN_PROMPT = 2000
"""Per-file cap when rendering files into a diagnosis/fix prompt. Groq's free
tier enforces a per-minute INPUT token budget per model (as low as 7000-8000
TPM on some models here), separate from the per-request context window --
a multi-file generation (e.g. a full website) sent back in full blows that
budget in a single self-heal call, so each file is bounded before inclusion."""

MAX_TOTAL_FILES_CHARS_IN_PROMPT = 6000
"""Hard ceiling across ALL files combined, on top of the per-file cap, so a
project with many small files doesn't add up past the same TPM budget."""

MAX_TEST_OUTPUT_CHARS_IN_PROMPT = 3000
"""Cap on stderr+stdout included in a diagnosis prompt -- a failing build can
produce a very long stack trace/log that alone can exceed the TPM budget."""


def _truncate(text: str, limit: int) -> str:
    """Truncate text to at most `limit` characters, noting how much was cut."""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated, {len(text) - limit} more chars]"


@dataclass(frozen=True)
class AttemptRecord:
    """One self-heal attempt: the files it produced and the test outcome."""

    attempt: int
    files: list[FileSpec]
    result: ExecutionResult


@dataclass(frozen=True)
class HealResult:
    """The outcome of a full self-heal loop."""

    final_files: list[FileSpec]
    passed: bool
    attempts: list[AttemptRecord] = field(default_factory=list)


def _files_block(files: list[FileSpec]) -> str:
    """Render files as a single text block for prompt inclusion.

    Bounded per-file and in total (see MAX_FILE_CHARS_IN_PROMPT and
    MAX_TOTAL_FILES_CHARS_IN_PROMPT) so a larger generated project doesn't
    blow a rate-limited model's per-minute input token budget.
    """
    parts = []
    total = 0
    for f in files:
        remaining = MAX_TOTAL_FILES_CHARS_IN_PROMPT - total
        if remaining <= 0:
            parts.append(f"--- {f.path} --- [omitted: prompt size budget exhausted]")
            continue
        content = _truncate(f.content, min(MAX_FILE_CHARS_IN_PROMPT, remaining))
        block = f"--- {f.path} ---\n{content}"
        total += len(block)
        parts.append(block)
    return "\n\n".join(parts)


def _history_block(history: list[AttemptRecord]) -> str:
    """Render the last HISTORY_LIMIT failed attempts as prior-fixes-tried text."""
    if not history:
        return ""
    recent = history[-HISTORY_LIMIT:]
    entries = [
        f"Attempt {record.attempt} code:\n{_files_block(record.files)}\n"
        f"Attempt {record.attempt} error:\n"
        f"{_truncate(f'{record.result.stderr}\\n{record.result.stdout}', MAX_TEST_OUTPUT_CHARS_IN_PROMPT)}"
        for record in recent
    ]
    return "\n\nPrior failed attempts (do NOT repeat these fixes):\n" + "\n\n".join(entries)


def _diagnose(
    task: str,
    files: list[FileSpec],
    result: ExecutionResult,
    history: list[AttemptRecord],
    router: Router,
    client: LLMClient,
    subagent: SubAgent | None,
    on_event: OnEvent,
) -> str:
    """Ask the reasoner model why the tests failed and what to change.

    Returns:
        The reasoner's final diagnosis/fix guidance, with any <think> trace
        stripped so only the answer is fed to the coder.
    """
    system_prompt = (
        subagent.system_prompt
        if subagent is not None and subagent.role == "reasoner"
        else "You are diagnosing why generated code failed its own tests. "
        "State the root cause, then the exact fix needed."
    )
    output_text = _truncate(f"{result.stderr}\n{result.stdout}", MAX_TEST_OUTPUT_CHARS_IN_PROMPT)
    user_content = (
        f"Task: {task}\n\nCurrent code and tests:\n{_files_block(files)}\n\n"
        f"Test failure output:\n{output_text}"
        f"{_history_block(history)}"
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    raw = call_role(
        "reasoner",
        "diagnose test failure",
        messages,
        router,
        client,
        priority="background",
        on_event=on_event,
        temperature=0.1,
        max_tokens=800,
    )
    return strip_reasoning_trace(raw)


def heal(
    task: str,
    language: str,
    workdir,
    files: list[FileSpec],
    result: ExecutionResult,
    router: Router,
    client: LLMClient,
    max_attempts: int,
    timeout_seconds: int,
    coder_subagent: SubAgent | None = None,
    reasoner_subagent: SubAgent | None = None,
    on_event: OnEvent = noop_event,
) -> HealResult:
    """Run the diagnose-then-fix loop until tests pass, or a bound is hit.

    Args:
        task: The original task description.
        language: Target language/stack key.
        workdir: Directory the generated files live in (mutated in place).
        files: The most recently generated files that failed their tests.
        result: The ExecutionResult of that failing run.
        router: Resolves model roles to live candidates.
        client: The multi-provider LLM client to call through.
        max_attempts: Maximum self-heal retries.
        timeout_seconds: Maximum wall-clock time for the whole loop.
        coder_subagent: Optional persona override for the coder role.
        reasoner_subagent: Optional persona override for the reasoner role.
        on_event: Progress event sink (see engine/calling.py).

    Returns:
        A HealResult with the final files, whether they now pass, and the
        full attempt history.
    """
    started_at = time.monotonic()
    history: list[AttemptRecord] = []
    current_files = files
    current_result = result

    for attempt in range(1, max_attempts + 1):
        if time.monotonic() - started_at > timeout_seconds:
            on_event({"type": "heal_timeout", "attempt": attempt})
            break

        history.append(AttemptRecord(attempt=attempt - 1, files=current_files, result=current_result))
        on_event({"type": "heal_attempt_start", "attempt": attempt})
        diagnosis = _diagnose(
            task, current_files, current_result, history, router, client, reasoner_subagent, on_event
        )

        system_prompt = (
            coder_subagent.system_prompt
            if coder_subagent is not None and coder_subagent.role == "primary_coder"
            else "You are fixing code that failed its own tests based on a diagnosis."
        )
        system_prompt += (
            f"\n\nTarget language/stack: {language}. "
            'Respond with ONLY a JSON object of the exact shape '
            '{"files": [{"path": "relative/file/path", "content": "full file content"}]} '
            "-- no prose, no markdown code fences."
        )
        user_content = (
            f"Task: {task}\n\nCurrent code and tests:\n{_files_block(current_files)}\n\n"
            f"Diagnosis and required fix:\n{diagnosis}"
        )

        try:
            artifact = request_files_from_coder(
                system_prompt,
                user_content,
                router,
                client,
                priority="background",
                purpose=f"apply self-heal fix (attempt {attempt})",
                on_event=on_event,
            )
        except GenerationError as exc:
            # A malformed fix response is a failed attempt, not a fatal
            # error -- treat it the same as a failing test result so the
            # bounded loop degrades gracefully instead of crashing the
            # whole run. current_files/current_result stay as the prior
            # attempt's, so the next diagnosis sees this as "still failing".
            on_event({"type": "heal_attempt_parse_failed", "attempt": attempt, "reason": str(exc)})
            current_result = ExecutionResult(
                passed=False, stdout="", stderr=f"Self-heal fix response could not be parsed: {exc}", returncode=1
            )
            continue

        write_files(workdir, artifact.files)
        current_result = run_tests(workdir, language)
        current_files = artifact.files
        on_event({"type": "heal_attempt_result", "attempt": attempt, "passed": current_result.passed})

        if current_result.passed:
            history.append(AttemptRecord(attempt=attempt, files=current_files, result=current_result))
            return HealResult(final_files=current_files, passed=True, attempts=history)

    history.append(AttemptRecord(attempt=len(history), files=current_files, result=current_result))
    return HealResult(final_files=current_files, passed=False, attempts=history)
