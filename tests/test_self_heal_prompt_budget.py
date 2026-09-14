"""Self-heal must be shown the file it is being asked to fix (#62).

The loop could not repair a Java project across any number of attempts, and the
reason was not the model. The diagnosis prompt spends a fixed character budget
on files in the order they were generated -- effectively alphabetically -- so on
a 16-file Spring project 10 files were omitted, including BOTH files the
compiler named. The reasoner was asked to fix code it had never seen.

Two further defects in the same path, each sufficient on its own:

- `current_files` was REPLACED by the coder's reply, so the model's view of its
  own project shrank every attempt while the runner kept compiling all of it
  from disk;
- the history block repeated the whole file listing per attempt, which put the
  prompt at ~7,900 tokens against Groq's 7,000 ITPM ceiling for the reasoner --
  five 413s, an exhausted candidate chain, and a dead run.
"""

from __future__ import annotations

from vishwakarma.engine.executor import ExecutionResult
from vishwakarma.engine.generate import FileSpec
from vishwakarma.engine.self_heal import (
    HISTORY_LIMIT,
    MAX_TOTAL_FILES_CHARS_IN_PROMPT,
    AttemptRecord,
    _files_block,
    _history_block,
    _paths_named_in,
)

JAVAC_ERROR = (
    "[ERROR] /tmp/p/src/main/java/com/example/orders/exception/GlobalExceptionHandler.java:"
    "[66,38] cannot find symbol\n"
    "[ERROR]   symbol:   method getIdempotencyKey()\n"
    "[ERROR]   location: variable ex of type "
    "com.example.orders.exception.OrderAlreadyExistsException\n"
)


def _project() -> list[FileSpec]:
    """A project shaped like the one that exposed this: filler sorts first."""
    filler = [
        FileSpec(path=f"src/main/java/com/example/orders/aaa/Filler{i}.java", content="x" * 1200)
        for i in range(6)
    ]
    broken = FileSpec(
        path="src/main/java/com/example/orders/exception/GlobalExceptionHandler.java",
        content="// handler\n" * 400,
    )
    referenced = FileSpec(
        path="src/main/java/com/example/orders/exception/OrderAlreadyExistsException.java",
        content="// exception\n" * 10,
    )
    return filler + [broken, referenced]


def _rendered(block: str, path: str) -> str:
    marker = f"--- {path} ---"
    return block.split(marker, 1)[1] if marker in block else ""


def _is_omitted(block: str, path: str) -> bool:
    return _rendered(block, path).lstrip().startswith("[omitted")


class TestTheBrokenFileReachesThePrompt:
    """The defect, stated directly."""

    def test_a_file_named_by_the_compiler_is_not_omitted(self):
        """Without prioritisation the budget was spent before reaching it."""
        files = _project()
        handler = "src/main/java/com/example/orders/exception/GlobalExceptionHandler.java"

        assert _is_omitted(_files_block(files), handler), (
            "precondition: in generation order this file falls outside the budget -- "
            "if this ever stops being true the fixture no longer reproduces #62"
        )
        assert not _is_omitted(_files_block(files, JAVAC_ERROR), handler)

    def test_a_type_named_by_the_compiler_is_matched_without_its_filename(self):
        """javac names the TYPE, never "OrderAlreadyExistsException.java".

        Matching filenames alone left exactly the class that had to change out
        of the prompt, which is why the first draft of this fix still failed.
        """
        files = _project()
        exception = "src/main/java/com/example/orders/exception/OrderAlreadyExistsException.java"

        assert "OrderAlreadyExistsException.java" not in JAVAC_ERROR, (
            "the compiler names the type, not the file -- that is the whole point"
        )
        assert exception in _paths_named_in(JAVAC_ERROR, files)
        assert not _is_omitted(_files_block(files, JAVAC_ERROR), exception)

    def test_a_named_file_is_not_truncated_before_the_error_line(self):
        """The error was at line 66 of a file whose first 41 lines were shown.

        Handing the model the top of a file and asking about its bottom is the
        same failure as omitting it, and harder to notice.
        """
        files = _project()
        handler = "src/main/java/com/example/orders/exception/GlobalExceptionHandler.java"
        visible = _rendered(_files_block(files, JAVAC_ERROR), handler)

        assert visible.count("\n") > 66, "the line the compiler pointed at must be visible"

    def test_unnamed_files_still_share_what_is_left(self):
        """Prioritising must not become "show only the broken file"."""
        block = _files_block(_project(), JAVAC_ERROR)

        assert "Filler0.java" in block


class TestTheHistoryBlockDoesNotRepeatTheProject:
    """What blew the input ceiling once the broken file was finally included."""

    def test_history_carries_the_error_not_another_copy_of_the_source(self):
        files = _project()
        record = AttemptRecord(
            attempt=1,
            files=files,
            result=ExecutionResult(
                passed=False, stdout="", stderr=JAVAC_ERROR, returncode=1
            ),
        )

        block = _history_block([record] * HISTORY_LIMIT)

        assert "getIdempotencyKey" in block, "the failure itself must survive"
        assert "GlobalExceptionHandler.java" in block, "which files were rewritten must survive"
        assert "// handler" not in block, (
            "file CONTENTS must not be repeated per attempt -- that is what put the "
            "prompt over Groq's 7000 ITPM ceiling and 413'd the reasoner"
        )

    def test_the_whole_prompt_stays_under_the_reasoner_input_ceiling(self):
        """A bound on the thing that actually broke, not a proxy for it.

        ~4 chars per token, against the measured 7000 ITPM limit for
        qwen/qwen3.6-27b. The observed failure was 7127 requested.
        """
        files = _project()
        result = ExecutionResult(passed=False, stdout="", stderr=JAVAC_ERROR, returncode=1)
        history = [AttemptRecord(attempt=i, files=files, result=result) for i in range(HISTORY_LIMIT)]

        chars = len(_files_block(files, JAVAC_ERROR)) + len(_history_block(history)) + len(JAVAC_ERROR)

        assert chars // 4 < 7000, f"diagnosis prompt is ~{chars // 4} tokens, ceiling is 7000"


class TestTheBudgetItselfStillHolds:
    """The fix must not have simply removed the bound it was working within."""

    def test_unnamed_files_remain_capped(self):
        files = _project()
        block = _files_block(files, JAVAC_ERROR)
        filler = _rendered(block, "src/main/java/com/example/orders/aaa/Filler5.java")

        assert _is_omitted(block, "src/main/java/com/example/orders/aaa/Filler5.java") or len(
            filler
        ) <= MAX_TOTAL_FILES_CHARS_IN_PROMPT

    def test_no_failure_output_preserves_the_original_order(self):
        """Callers with nothing to point at must behave exactly as before."""
        files = _project()

        assert _files_block(files) == _files_block(files, "")
