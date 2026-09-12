"""Lightweight, off-by-default context selection over the user's existing project.

Per the ai-engineer review, a personal codebase is small enough that a
keyword/file-tree scan beats the complexity and RPM cost of an
embedding+vector-search pipeline. Revisit embeddings only if the project
genuinely grows past a few hundred files where keyword matching starts
missing semantically-related code.
"""

from __future__ import annotations

import re
from pathlib import Path

MAX_FILES_SCANNED = 500
MAX_MATCHED_FILES = 5
MAX_SNIPPET_CHARS = 1500
SKIP_DIR_NAMES = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
WORD_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


def _task_keywords(task: str) -> set[str]:
    """Extract lowercase identifier-like keywords from the task description."""
    return {word.lower() for word in WORD_PATTERN.findall(task)}


def _iter_source_files(project_dir: Path):
    """Yield source files under project_dir, skipping common noise directories."""
    count = 0
    for path in project_dir.rglob("*"):
        if count >= MAX_FILES_SCANNED:
            return
        if not path.is_file():
            continue
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        count += 1
        yield path


def build_context(task: str, project_dir: Path | None) -> str | None:
    """Select a handful of relevant existing files by simple keyword overlap.

    Args:
        task: The user's free-text task description.
        project_dir: Root directory of the existing project to search, or
            None if there is nothing to search (fresh task, no RAG).

    Returns:
        A text block of the best-matching files' contents (truncated), or
        None if project_dir is unset or no files matched.
    """
    if project_dir is None or not project_dir.exists():
        return None

    keywords = _task_keywords(task)
    if not keywords:
        return None

    scored: list[tuple[int, Path]] = []
    for path in _iter_source_files(project_dir):
        haystack = path.name.lower()
        try:
            haystack += " " + path.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            continue
        score = sum(1 for keyword in keywords if keyword in haystack)
        if score > 0:
            scored.append((score, path))

    if not scored:
        return None

    scored.sort(key=lambda pair: pair[0], reverse=True)
    top_files = scored[:MAX_MATCHED_FILES]

    blocks = []
    for _, path in top_files:
        content = path.read_text(encoding="utf-8", errors="ignore")[:MAX_SNIPPET_CHARS]
        blocks.append(f"--- {path.relative_to(project_dir)} ---\n{content}")
    return "\n\n".join(blocks)
