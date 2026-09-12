"""Web (frontend + backend) language adapter: runs the generated suite with npm."""

from __future__ import annotations

from pathlib import Path

from vishwakarma.languages.base import LanguageAdapter


class WebAdapter(LanguageAdapter):
    """npm-based adapter for React/Angular frontend + Node/FastAPI backend tasks."""

    name = "web"

    def test_command(self, workdir: Path) -> list[str]:
        # executor.py already runs this with cwd=workdir, so no --prefix
        # needed -- passing workdir's own path again would make npm look
        # for a nested "<workdir>/<workdir>" package directory that doesn't exist.
        return ["npm", "test"]

    def default_file_extension(self) -> str:
        return ".js"
