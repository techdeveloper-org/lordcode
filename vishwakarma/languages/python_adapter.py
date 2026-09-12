"""Python language adapter: runs the generated suite with pytest."""

from __future__ import annotations

import sys
from pathlib import Path

from vishwakarma.languages.base import LanguageAdapter


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
