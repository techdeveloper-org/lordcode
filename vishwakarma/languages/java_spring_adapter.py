"""Java/Spring Boot language adapter: runs the generated suite with Maven."""

from __future__ import annotations

import re
from pathlib import Path

from vishwakarma.languages.base import LanguageAdapter

_COMPILE_ERROR_SITE = re.compile(r"([\w$]+\.java):\[(\d+),\d+\]")
"""A javac error location: `OrderService.java:[47,32]`.

Captured as (file, line) so the same site reported twice -- Maven echoes every
compiler error in its own failure summary -- counts once.
"""

_SUREFIRE_FAILURES = re.compile(
    r"Tests run:\s*\d+,\s*Failures:\s*(\d+),\s*Errors:\s*(\d+)", re.IGNORECASE
)
"""Surefire's failure/error totals, used once the project actually compiles."""

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

    def failure_count(self, stdout: str, stderr: str) -> int | None:
        """Count distinct compiler error sites, then fall back to failing tests.

        Compilation is the gate: nothing runs until it passes, so while the
        build is broken the error count IS the progress signal. Counted as
        distinct `File.java:[line,col]` sites rather than raw lines, because
        Maven prints every error twice -- once from the compiler and once in
        its own failure summary -- and an un-deduplicated count would report 10
        where 5 sites exist, which is still monotonic but doubles every
        comparison.

        Once it compiles, surefire's `Failures` and `Errors` totals take over.

        Args:
            stdout: Maven's captured stdout.
            stderr: Maven's captured stderr.

        Returns:
            Distinct compile-error sites, else failing tests, else None.
        """
        combined = f"{stdout}\n{stderr}"
        sites = set(_COMPILE_ERROR_SITE.findall(combined))
        if sites:
            return len(sites)

        totals = _SUREFIRE_FAILURES.findall(combined)
        if totals:
            return max(int(failures) + int(errors) for failures, errors in totals)
        return None

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
