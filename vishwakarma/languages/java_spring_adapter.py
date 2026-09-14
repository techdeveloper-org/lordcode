"""Java/Spring Boot language adapter: runs the generated suite with Maven."""

from __future__ import annotations

import re
from pathlib import Path

from vishwakarma.languages.base import LanguageAdapter

_SUREFIRE_SUMMARY = re.compile(r"Tests run:\s*(\d+)", re.IGNORECASE)
"""Surefire's per-module and final summary line.

Matches both the per-class lines and the "Results:" block, so the counts are
summed rather than taken from whichever happened to be last.
"""


class JavaSpringAdapter(LanguageAdapter):
    """Maven-based adapter tuned toward Spring Boot style generation tasks."""

    name = "java"

    def test_command(self, workdir: Path) -> list[str]:
        # executor.py already runs this with cwd=workdir, so no -f needed --
        # passing workdir's own path again would make Maven look for a
        # nested "<workdir>/<workdir>" project directory that doesn't exist.
        #
        # Deliberately NOT -q: quiet mode suppresses surefire's own
        # "Tests run: N, Failures: ..., Errors: ..., Skipped: ..." summary,
        # which is the only place Maven says how many tests actually ran. We
        # do not take BUILD SUCCESS as evidence that anything was verified
        # (#59), so the summary has to be visible to be read.
        return ["mvn", "test"]

    def default_file_extension(self) -> str:
        return ".java"

    def executed_test_count(self, stdout: str, stderr: str) -> int | None:
        """Read surefire's own count instead of trusting BUILD SUCCESS.

        Maven reports success over an empty test set ("No tests to run." then
        BUILD SUCCESS, exit 0), so the build result says nothing about whether
        anything was verified. The "Tests run: N" summary does.

        Takes the MAXIMUM across all matches rather than the sum: surefire
        prints a line per test class and then a combined "Results:" total, so
        summing would double-count. The largest figure is the total.

        Args:
            stdout: Maven's captured stdout.
            stderr: Maven's captured stderr.

        Returns:
            The number of tests surefire reports running, or None when no
            summary line is present at all -- which happens when compilation
            failed before any test ran, and is a different fault from zero.
        """
        counts = [int(match) for match in _SUREFIRE_SUMMARY.findall(f"{stdout}\n{stderr}")]
        return max(counts) if counts else None

    def test_file_patterns(self) -> tuple[str, ...]:
        """Maven's standard test layout plus surefire's default class-name patterns.

        `src/test/java` is where surefire looks; the `*Test`/`*Tests`/`Test*`
        globs also catch a generation that put a correctly-named test class in
        the wrong directory, which is worth reporting as a real test rather
        than as an absence.
        """
        return (
            "src/test/java/**/*.java",
            "**/*Test.java",
            "**/*Tests.java",
            "**/Test*.java",
        )
