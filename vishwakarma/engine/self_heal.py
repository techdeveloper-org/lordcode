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
from vishwakarma.languages import get_adapter
from vishwakarma.engine.generate import FileSpec, GenerationError, request_files_from_coder
from vishwakarma.engine.personas import persona_for_role
from vishwakarma.engine.reasoning_utils import strip_reasoning_trace
from vishwakarma.llm_client import LLMClient
from vishwakarma.engine.personas import SubAgent
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


def _paths_named_in(output: str, files: list[FileSpec]) -> set[str]:
    """Which generated files the failure output actually names.

    Compilers and test runners say where the problem is -- javac reports
    `.../GlobalExceptionHandler.java:[31,5] cannot find symbol`, pytest names
    the failing module -- and that is the only signal available for deciding
    which files matter when the whole project cannot fit in the prompt.

    Matched on basename, because the runner prints absolute OS paths while a
    FileSpec carries a repo-relative one, and the two never compare equal.

    Also matched on the basename with its extension removed, because compilers
    name TYPES rather than files for a whole class of error: javac reports
    `cannot find symbol: method getIdempotencyKey(), location: variable ex of
    type com.example.orders.exception.OrderAlreadyExistsException`, which never
    contains the string "OrderAlreadyExistsException.java". Matching filenames
    alone left exactly the file that had to change out of the prompt.

    Args:
        output: Combined stderr/stdout from the failed run.
        files: The generated files, to match names against.

    Returns:
        The subset of `files` paths named anywhere in the output.
    """
    named = set()
    for spec in files:
        basename = spec.path.rsplit("/", 1)[-1]
        stem = basename.rsplit(".", 1)[0]
        if basename in output or (len(stem) > 3 and stem in output):
            named.add(spec.path)
    return named


def _files_block(files: list[FileSpec], failure_output: str = "") -> str:
    """Render files as a single text block for prompt inclusion.

    Bounded per-file and in total (see MAX_FILE_CHARS_IN_PROMPT and
    MAX_TOTAL_FILES_CHARS_IN_PROMPT) so a larger generated project doesn't
    blow a rate-limited model's per-minute input token budget.

    Files the failure output NAMES come first. Without that ordering the budget
    was spent in whatever order the generator emitted -- effectively
    alphabetically -- and on a real multi-file project the broken file simply
    never reached the model. Measured on a 16-file Spring project: 10 files
    omitted, including BOTH files the compiler named, so the reasoner was asked
    to fix code it had never been shown and self-heal could not succeed at any
    attempt budget (#62).

    Args:
        files: The generated files.
        failure_output: Combined runner output, used to decide relevance. Empty
            preserves the original order, for callers with no failure to point at.

    Returns:
        The rendered block, most-relevant first.
    """
    named: set[str] = set()
    ordered = files
    if failure_output:
        named = _paths_named_in(failure_output, files)
        if named:
            ordered = [f for f in files if f.path in named] + [
                f for f in files if f.path not in named
            ]

    parts = []
    total = 0
    for f in ordered:
        remaining = MAX_TOTAL_FILES_CHARS_IN_PROMPT - total
        if remaining <= 0:
            parts.append(f"--- {f.path} --- [omitted: prompt size budget exhausted]")
            continue
        # A file the runner named is exempt from the per-file cap, because the
        # error is as likely to be at the bottom of it as the top. The observed
        # case reported errors at lines 31, 48 and 66 of a 5,068-char file,
        # while the 2,000-char cap showed only the first 41 lines -- the model
        # was handed the file and still could not see the defect.
        cap = remaining if f.path in named else min(MAX_FILE_CHARS_IN_PROMPT, remaining)
        content = _truncate(f.content, cap)
        block = f"--- {f.path} ---\n{content}"
        total += len(block)
        parts.append(block)
    return "\n\n".join(parts)


def _history_block(history: list[AttemptRecord]) -> str:
    """Render the last HISTORY_LIMIT failed attempts as prior-fixes-tried text.

    Carries what each attempt CHANGED and what still broke -- not another copy
    of the source. The current code is already in the prompt once; repeating
    every file for every historical attempt was the single largest consumer of
    the input budget, at HISTORY_LIMIT x the whole file block. Measured on a
    16-file Spring project that put the diagnosis prompt at ~7,900 tokens
    against Groq's 7,000 ITPM ceiling for `qwen/qwen3.6-27b`, so the reasoner
    413'd five times, exhausted its candidate chain, and the run died with
    ConfigError -- while the fix it needed was three lines (#62).

    What the loop actually needs from history is "which fixes have already been
    tried and failed", which is the file list plus the error, at a fraction of
    the cost.
    """
    if not history:
        return ""
    recent = history[-HISTORY_LIMIT:]
    per_attempt_output = max(MAX_TEST_OUTPUT_CHARS_IN_PROMPT // (len(recent) or 1), 600)
    entries = [
        f"Attempt {record.attempt} rewrote: "
        f"{', '.join(spec.path for spec in record.files) or '(nothing)'}\n"
        f"Attempt {record.attempt} still failed with:\n"
        f"{_truncate(f'{record.result.stderr}\\n{record.result.stdout}'.strip(), per_attempt_output)}"
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
    reasoner_persona = persona_for_role(subagent, "reasoner", on_event)
    system_prompt = (
        reasoner_persona.system_prompt
        if reasoner_persona is not None
        else "You are diagnosing why generated code failed its own tests. "
        "State the root cause, then the exact fix needed."
    )
    raw_output = f"{result.stderr}\n{result.stdout}"
    output_text = _truncate(raw_output, MAX_TEST_OUTPUT_CHARS_IN_PROMPT)
    user_content = (
        f"Task: {task}\n\nCurrent code and tests:\n{_files_block(files, raw_output)}\n\n"
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

    adapter = get_adapter(language)
    best_files = files
    best_count = adapter.failure_count(result.stdout, result.stderr)

    if result.runner_missing:
        on_event(
            {
                "type": "heal_refused",
                "reason": "the test runner is missing, which no code change can fix",
                "detail": result.stderr,
            }
        )
        return HealResult(
            final_files=files,
            passed=False,
            attempts=[AttemptRecord(attempt=0, files=files, result=result)],
        )

    for attempt in range(1, max_attempts + 1):
        if time.monotonic() - started_at > timeout_seconds:
            on_event({"type": "heal_timeout", "attempt": attempt})
            break

        history.append(AttemptRecord(attempt=attempt - 1, files=current_files, result=current_result))
        on_event({"type": "heal_attempt_start", "attempt": attempt})
        diagnosis = _diagnose(
            task, current_files, current_result, history, router, client, reasoner_subagent, on_event
        )

        coder_persona = persona_for_role(coder_subagent, "primary_coder", on_event)
        system_prompt = (
            coder_persona.system_prompt
            if coder_persona is not None
            else "You are fixing code that failed its own tests based on a diagnosis."
        )
        system_prompt += (
            f"\n\nTarget language/stack: {language}. "
            'Respond with ONLY a JSON object of the exact shape '
            '{"files": [{"path": "relative/file/path", "content": "full file content"}]} '
            "-- no prose, no markdown code fences."
        )
        # The same relevance ordering as the diagnosis, and it matters more
        # here: this call must REWRITE the broken file, so omitting it means
        # the fix cannot be applied however good the diagnosis was (#62).
        user_content = (
            f"Task: {task}\n\nCurrent code and tests:\n"
            f"{_files_block(current_files, f'{current_result.stderr}\n{current_result.stdout}')}\n\n"
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
        # MERGE, never replace. A fix response carries only the files the coder
        # chose to rewrite, but write_files leaves the rest on disk and the
        # runner still compiles all of them. Assigning artifact.files directly
        # shrank the model's view of its own project on every attempt -- three
        # files back meant the next prompt showed three files out of sixteen --
        # while the compiler kept reporting errors in the ones that had
        # silently dropped out of sight (#62).
        merged = {spec.path: spec for spec in current_files}
        merged.update({spec.path: spec for spec in artifact.files})
        current_files = list(merged.values())
        on_event({"type": "heal_attempt_result", "attempt": attempt, "passed": current_result.passed})

        if current_result.passed:
            history.append(AttemptRecord(attempt=attempt, files=current_files, result=current_result))
            return HealResult(final_files=current_files, passed=True, attempts=history)

        # Keep the best state reached, not the last one produced. Each fix is
        # locally reasonable and the sequence need not be: an attempt can repair
        # one file while breaking another it changed two attempts ago, and
        # without this the loop carries that worse state forward and diagnoses
        # from it. Measured across attempts on a Spring project, errors went
        # 3 -> 1 -> 5 and the run ended worse than a state it had already
        # reached (#64).
        attempt_count = adapter.failure_count(current_result.stdout, current_result.stderr)
        if attempt_count is None or best_count is None:
            best_files, best_count = current_files, attempt_count
        elif attempt_count <= best_count:
            best_files, best_count = current_files, attempt_count
        else:
            on_event(
                {
                    "type": "heal_attempt_regressed",
                    "attempt": attempt,
                    "failures": attempt_count,
                    "best": best_count,
                }
            )
            # Put the better code back on disk as well as in the prompt. The
            # runner reads the workdir, so leaving the regression written would
            # make the next attempt diagnose the state we just rejected.
            write_files(workdir, best_files)
            current_files = best_files
            current_result = run_tests(workdir, language)

    # Hand back the best state reached rather than the last one attempted. The
    # two agree whenever a regression was rolled back, but saying so explicitly
    # keeps that true if the rollback conditions above are ever changed.
    if best_files is not current_files:
        write_files(workdir, best_files)
        current_files = best_files
        current_result = run_tests(workdir, language)

    history.append(AttemptRecord(attempt=len(history), files=current_files, result=current_result))
    return HealResult(final_files=current_files, passed=current_result.passed, attempts=history)
