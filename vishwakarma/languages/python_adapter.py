"""Python language adapter: runs the generated suite with pytest."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from vishwakarma.languages.base import LanguageAdapter

_PYTEST_OUTCOME = re.compile(r"(\d+)\s+(passed|failed|error|errors|xpassed|xfailed)\b")
"""pytest's terminal summary counts, e.g. "3 passed, 1 failed in 0.12s"."""


class PythonAdapter(LanguageAdapter):
    """pytest-based adapter for Python code generation tasks."""

    name = "python"

    def test_command(self, workdir: Path) -> list[str]:
        # executor.py already runs this with cwd=workdir, so the target is
        # "." -- passing workdir's own path again would make pytest look
        # for a nested "<workdir>/<workdir>" directory that doesn't exist.
        return [sys.executable, "-m", "pytest", ".", "-q"]

    def default_file_extension(self) -> str:
        return ".py"

    def executed_test_count(self, stdout: str, stderr: str) -> int | None:
        """Sum pytest's own outcome counts rather than reading its exit status.

        pytest is the honest one of the three runners -- it exits 5 on an empty
        collection -- but the count is still the direct evidence, and reading
        it here keeps all three adapters answering the same question the same
        way.

        Args:
            stdout: pytest's captured stdout.
            stderr: pytest's captured stderr.

        Returns:
            Total tests with a reported outcome, or None when no summary line
            is present (an import error before collection, for instance).
        """
        matches = _PYTEST_OUTCOME.findall(f"{stdout}\n{stderr}")
        return sum(int(count) for count, _ in matches) if matches else None

    def test_file_patterns(self) -> tuple[str, ...]:
        """pytest's own default discovery patterns, so the check agrees with the runner."""
        return ("test_*.py", "*_test.py")

    def reports_no_tests_collected(self, returncode: int) -> bool:
        """pytest exits 5 (EXIT_NOTESTSCOLLECTED) rather than pretending to succeed.

        The one runner of the three that is honest here, which is why the
        Python path never exhibited #59 and the Java path did.
        """
        return returncode == 5
