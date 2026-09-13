"""Three-tier problem taxonomy for reading a real knowledge graph.

A strict loader cannot load claude-global-library. Measured at
library_version 29.97.4: 591 edges carry a null id, 1051 duplicate
(source, target, type) triples exist, 6696 of 8555 non-null edge ids fail the
library's own EdgeID pattern, and 25 edge endpoints name nodes that do not
exist. None of that prevents building a correct adjacency structure, and the
library's own QA gate passes with all of it present -- so treating any of it
as a hard error would mean kgf could never read the live library at all.

Equally, silently dropping bad records is how 30 unparseable skill files went
unnoticed for months. So every problem is recorded and reported; only the
subset that genuinely prevents adjacency construction stops the load.

    FATAL   the graph cannot be built (unknown edge type, missing endpoint).
            Measured count on the live library: 0.
    DEFECT  real data damage that does not block reading. Reported with an
            exact count so drift is visible.
    INFO    an optional field is absent on a record. The registries are
            ragged -- 90 distinct agent keys of which 11 are universal, 116
            skill keys of which 7 are universal -- so absence is the norm,
            not an anomaly.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import Enum


class Severity(str, Enum):
    """How much a problem matters. Only FATAL stops the load."""

    FATAL = "FATAL"
    DEFECT = "DEFECT"
    INFO = "INFO"


@dataclass(frozen=True)
class Problem:
    """One recorded problem, always attributable to a specific record."""

    severity: Severity
    code: str
    detail: str
    source: str = ""

    def __str__(self) -> str:
        where = f" [{self.source}]" if self.source else ""
        return f"{self.severity.value} {self.code}{where}: {self.detail}"


class GraphBuildError(Exception):
    """Raised when FATAL problems make an adjacency structure impossible.

    Carries every FATAL found rather than only the first, because a caller
    fixing a malformed registry wants the whole list in one pass.
    """

    def __init__(self, problems: list[Problem]):
        self.problems = problems
        listed = "\n  ".join(str(problem) for problem in problems[:10])
        more = f"\n  ... and {len(problems) - 10} more" if len(problems) > 10 else ""
        super().__init__(f"cannot build the graph; {len(problems)} FATAL problem(s):\n  {listed}{more}")


class LibraryNotFoundError(Exception):
    """Raised when no claude-global-library can be located on disk."""


@dataclass
class ProblemLog:
    """Accumulates problems during a load, queryable by severity and code."""

    problems: list[Problem] = field(default_factory=list)

    def add(self, severity: Severity, code: str, detail: str, source: str = "") -> None:
        """Record one problem."""
        self.problems.append(Problem(severity=severity, code=code, detail=detail, source=source))

    def fatal(self, code: str, detail: str, source: str = "") -> None:
        """Record a problem that prevents building the graph."""
        self.add(Severity.FATAL, code, detail, source)

    def defect(self, code: str, detail: str, source: str = "") -> None:
        """Record real data damage that does not block reading."""
        self.add(Severity.DEFECT, code, detail, source)

    def info(self, code: str, detail: str, source: str = "") -> None:
        """Record an absent optional field or similar non-problem."""
        self.add(Severity.INFO, code, detail, source)

    def of(self, severity: Severity) -> list[Problem]:
        """Every problem at one severity, in the order recorded."""
        return [problem for problem in self.problems if problem.severity is severity]

    @property
    def fatals(self) -> list[Problem]:
        """Every FATAL problem recorded."""
        return self.of(Severity.FATAL)

    def counts_by_code(self, severity: Severity | None = None) -> dict[str, int]:
        """How many problems of each code, optionally filtered by severity."""
        selected = self.problems if severity is None else self.of(severity)
        return dict(Counter(problem.code for problem in selected))

    def raise_if_fatal(self) -> None:
        """Raise GraphBuildError if any FATAL problem was recorded."""
        fatals = self.fatals
        if fatals:
            raise GraphBuildError(fatals)

    def summary(self) -> str:
        """One line per severity with its per-code breakdown, for the CLI."""
        lines = []
        for severity in (Severity.FATAL, Severity.DEFECT, Severity.INFO):
            counts = self.counts_by_code(severity)
            total = sum(counts.values())
            if not total:
                continue
            breakdown = ", ".join(f"{code}={count}" for code, count in sorted(counts.items()))
            lines.append(f"{severity.value}: {total} ({breakdown})")
        return "\n".join(lines) if lines else "no problems recorded"
