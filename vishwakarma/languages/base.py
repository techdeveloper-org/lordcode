"""Base contract every language adapter must implement."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class LanguageAdapter(ABC):
    """Knows how to run the generated test suite for one target stack."""

    name: str

    @abstractmethod
    def test_command(self, workdir: Path) -> list[str]:
        """Return the subprocess argv that runs this stack's test suite.

        Args:
            workdir: Directory containing the generated code + test files.

        Returns:
            The argv list to pass to subprocess.run.
        """
        raise NotImplementedError

    @abstractmethod
    def default_file_extension(self) -> str:
        """Return the default source file extension for this stack (e.g. '.py')."""
        raise NotImplementedError

    @abstractmethod
    def test_file_patterns(self) -> tuple[str, ...]:
        """Return globs, relative to the workdir, that identify this stack's test files.

        Used to answer a question the exit code cannot: did the generation
        actually produce tests? A runner that finds no tests to run generally
        reports success -- `mvn test` prints "No tests to run." and exits 0,
        and `node --test` exits 0 on an empty test set -- so a run that wrote
        no tests at all is otherwise indistinguishable from one whose tests
        all passed (#59).

        That distinction is the whole product contract: this tool writes code
        AND its own tests. A generation with no tests is a failed generation,
        not a passing one.

        Returns:
            Glob patterns matched against the workdir with Path.rglob/glob.
        """
        raise NotImplementedError

    def executed_test_count(self, stdout: str, stderr: str) -> int | None:
        """How many tests the runner reports actually EXECUTING, if it says so.

        Deliberately not the same question as "did the build succeed". Maven
        prints BUILD SUCCESS over an empty test set, so taking the runner's
        word for it is how a generation with no tests came back as "All tests
        passed" (#59). Where the runner prints a count, we read the count.

        Args:
            stdout: The test command's captured stdout.
            stderr: The test command's captured stderr.

        Returns:
            The number of tests executed, or None when this runner's output
            does not carry a count this adapter can parse. None means "cannot
            tell", never "zero" -- a caller must not treat the two alike.
        """
        return None

    def reports_no_tests_collected(self, returncode: int) -> bool:
        """Whether this runner's exit code specifically means "no tests were collected".

        A second, independent signal to the file-presence check, for runners
        that are honest about an empty test set. Defaults to False because most
        are not: only override where the runner documents a distinct code.

        Args:
            returncode: The test command's exit status.

        Returns:
            True if the runner is reporting an empty test set rather than
            success or a test failure.
        """
        return False
