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

    def test_file_patterns(self) -> tuple[str, ...]:
        """The conventions jest, vitest, mocha and node --test all discover by.

        Broad on purpose: `npm test` runs whatever the generated package.json
        puts in its "test" script, so the runner is not known ahead of time.
        Measured, the two plausible outcomes disagree -- npm's default
        "no test specified" stub exits 1, while `node --test` with no test
        files exits 0 -- so exit status cannot carry this for web at all and
        the file check is the only reliable signal.
        """
        return (
            "**/*.test.js",
            "**/*.test.ts",
            "**/*.test.jsx",
            "**/*.test.tsx",
            "**/*.spec.js",
            "**/*.spec.ts",
            "**/*.spec.jsx",
            "**/*.spec.tsx",
            "test/**/*.js",
            "tests/**/*.js",
            "__tests__/**/*.js",
            "__tests__/**/*.ts",
        )
