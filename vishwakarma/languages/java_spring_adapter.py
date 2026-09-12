"""Java/Spring Boot language adapter: runs the generated suite with Maven."""

from __future__ import annotations

from pathlib import Path

from vishwakarma.languages.base import LanguageAdapter


class JavaSpringAdapter(LanguageAdapter):
    """Maven-based adapter tuned toward Spring Boot style generation tasks."""

    name = "java"

    def test_command(self, workdir: Path) -> list[str]:
        # executor.py already runs this with cwd=workdir, so no -f needed --
        # passing workdir's own path again would make Maven look for a
        # nested "<workdir>/<workdir>" project directory that doesn't exist.
        return ["mvn", "-q", "test"]

    def default_file_extension(self) -> str:
        return ".java"
