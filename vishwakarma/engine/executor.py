"""Writes generated files to disk and runs the target stack's test suite."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from vishwakarma.engine.generate import FileSpec
from vishwakarma.languages import get_adapter

TEST_TIMEOUT_SECONDS = 120


@dataclass(frozen=True)
class ExecutionResult:
    """The outcome of one test run: pass/fail plus captured output."""

    passed: bool
    stdout: str
    stderr: str
    returncode: int


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
    argv = adapter.test_command(workdir)

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
        )

    return ExecutionResult(
        passed=completed.returncode == 0,
        stdout=completed.stdout,
        stderr=completed.stderr,
        returncode=completed.returncode,
    )
