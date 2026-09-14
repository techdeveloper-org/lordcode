"""Writes generated files to disk and runs the target stack's test suite."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from vishwakarma.engine.generate import FileSpec
from vishwakarma.languages import get_adapter

TEST_TIMEOUT_SECONDS = 120


@dataclass(frozen=True)
class ExecutionResult:
    """The outcome of one test run: pass/fail plus captured output.

    `runner_missing` separates an environment fault from a test failure.
    Without it the two are indistinguishable, and self-heal spent three
    diagnose-and-regenerate attempts -- real model calls, minutes of pacing
    each at this repo's ~6000 TPM -- trying to fix code for a runner that was
    never on PATH (issue #17).
    """

    passed: bool
    stdout: str
    stderr: str
    returncode: int
    runner_missing: bool = False


def resolve_runner(program: str) -> str | None:
    """Resolve a test runner's name to an executable path, or None if absent.

    `shutil.which` is what makes a Windows runner work at all. Maven and npm
    ship their entry points as `mvn.cmd` and `npm.cmd`, and CreateProcess will
    not start a batch file from a bare name, so `subprocess.run(["mvn", ...])`
    with shell=False raises WinError 2 even when Maven is installed and on
    PATH -- measured here with Maven 3.9.9 present, where `["mvn", "-v"]`
    raised and `["mvn.cmd", "-v"]` returned 0 (issue #17). `which` consults
    PATHEXT and returns the real name.

    shell=True would also "work" and is not used: it would reintroduce the
    injection surface that passing argv exists to avoid, for every language
    adapter at once.

    An absolute path is returned unchanged when it exists, which keeps the
    Python adapter's `sys.executable` untouched.
    """
    candidate = Path(program)
    if candidate.is_absolute():
        return program if candidate.is_file() else None
    return shutil.which(program)


def write_files(workdir: Path, files: list[FileSpec]) -> None:
    """Write every generated file to workdir, creating parent directories.

    Args:
        workdir: The directory to write generated files into.
        files: The files to write.
    """
    for file_spec in files:
        target = workdir / file_spec.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(file_spec.content, encoding="utf-8")


def _has_test_files(workdir: Path, adapter) -> bool:
    """Whether the generation produced anything the runner would recognise as a test.

    Asked before the runner is invoked, because the runner cannot answer it: a
    test command that finds nothing to run mostly reports success. `mvn test`
    prints "No tests to run." and exits 0, `node --test` exits 0 on an empty
    set, and only pytest is honest (exit 5). So a run that wrote no tests
    looked identical to one whose tests all passed, and "All tests passed" was
    printed over seven source files and zero test files (#59).

    Args:
        workdir: Directory the generated files were written to.
        adapter: The language adapter, for its test_file_patterns().

    Returns:
        True if at least one file matches one of the adapter's patterns.
    """
    for pattern in adapter.test_file_patterns():
        if any(path.is_file() for path in workdir.glob(pattern)):
            return True
    return False


def run_tests(workdir: Path, language: str) -> ExecutionResult:
    """Run the language adapter's test command against the written files.

    Args:
        workdir: Directory containing the generated code + test files.
        language: Registered language adapter name.

    Returns:
        The ExecutionResult, including any timeout or missing-runner error
        surfaced as a failed run rather than an unhandled exception.
    """
    adapter = get_adapter(language)
    argv = list(adapter.test_command(workdir))

    # Runner resolution comes first deliberately. A missing toolchain is an
    # environmental fault that no regeneration can fix, so it outranks "the
    # model wrote no tests", which is a generation fault the heal loop can act
    # on. Reporting the wrong one sends the caller looking in the wrong place.
    resolved = resolve_runner(argv[0])
    if resolved is None:
        return ExecutionResult(
            passed=False,
            stdout="",
            stderr=(
                f"Test runner {argv[0]!r} for '{language}' was not found on PATH. "
                "Install it, or add it to PATH, and run again -- no amount of code "
                "regeneration can fix this."
            ),
            returncode=-1,
            runner_missing=True,
        )
    argv[0] = resolved

    if not _has_test_files(workdir, adapter):
        return ExecutionResult(
            passed=False,
            stdout="",
            stderr=(
                f"No test files were generated for '{language}'. Expected at least one "
                f"file matching {', '.join(adapter.test_file_patterns())}. Write the tests "
                "alongside the implementation and try again."
            ),
            returncode=-1,
        )

    try:
        completed = subprocess.run(
            argv,
            cwd=workdir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TEST_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        return ExecutionResult(
            passed=False,
            stdout=exc.stdout or "",
            stderr=f"Test run exceeded {TEST_TIMEOUT_SECONDS}s timeout",
            returncode=-1,
        )
    except FileNotFoundError as exc:
        return ExecutionResult(
            passed=False,
            stdout="",
            stderr=f"Test runner not found for '{language}': {exc}",
            returncode=-1,
            runner_missing=True,
        )

    if adapter.reports_no_tests_collected(completed.returncode):
        return ExecutionResult(
            passed=False,
            stdout=completed.stdout,
            stderr=(
                f"The '{language}' runner collected no tests, so nothing was verified. "
                f"{completed.stderr}"
            ).strip(),
            returncode=completed.returncode,
        )

    # Do not take the runner's word for it. A green build is the runner's
    # answer to "did anything fail", not to "did anything run", and Maven
    # reports BUILD SUCCESS over an empty test set. Where the runner prints a
    # count, that count decides (#59). None means the output carried no count
    # to read, which is NOT the same as zero and must not be treated as one.
    executed = adapter.executed_test_count(completed.stdout, completed.stderr)
    if completed.returncode == 0 and executed == 0:
        return ExecutionResult(
            passed=False,
            stdout=completed.stdout,
            stderr=(
                f"The '{language}' runner exited successfully but reported running 0 tests, "
                "so nothing was actually verified. Write tests that execute against the "
                "generated code."
            ),
            returncode=completed.returncode,
        )

    return ExecutionResult(
        passed=completed.returncode == 0,
        stdout=completed.stdout,
        stderr=completed.stderr,
        returncode=completed.returncode,
    )
