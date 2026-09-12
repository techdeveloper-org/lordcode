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
