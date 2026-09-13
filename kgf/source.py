"""Locating claude-global-library and reading bytes off it.

This is the only module in kgf that resolves a filesystem path or decides an
encoding, so there is exactly one place to look when either is wrong.

Encoding is explicit in both directions, and the two halves differ:

  JSON registries are read as utf-8. Relying on the platform default fails
  outright here -- json.load(open('skills_all.json')) raises
  UnicodeDecodeError at byte 0x81 under the Windows codepage.

  Markdown is read as utf-8-SIG. 13 of the library's 1562 markdown files begin
  with a UTF-8 BOM, which a plain utf-8 read leaves in place as \\ufeff before
  the opening `---`, so a frontmatter parser anchored at the start of the file
  sees no frontmatter and drops the file. Those 13 were previously counted as
  structurally broken; utf-8-sig recovers every one and breaks nothing (0
  regressions over all 1562 files). The genuinely malformed remainder is 18
  files, all YAML quoting faults.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kgf.errors import LibraryNotFoundError

ENV_LIBRARY_PATH = "KGF_LIBRARY_PATH"
SIBLING_DIR_NAME = "claude-global-library"

MASTER_RELPATH = Path("knowledge-graph") / "_master"
TREE_RELPATH = Path("knowledge-graph") / "_orchestration-decision-tree"

REGISTRY_FILES = (
    "agents_all.json",
    "skills_all.json",
    "domains_all.json",
    "edges_all.json",
    "regulations_all.json",
)
"""The five registries M1 reads.

regulations_all.json is the one most easily forgotten, and omitting it is not
a small loss: all 646 REGULATED_BY targets dangle without it, which makes any
regulation traversal silently empty.

Deliberately absent: super_graph.json, verified multiset-identical to
edges_all.json on both (source, target, type) and edge id while dropping 82
attributes, so it is a lossy projection rather than a second source; and
indices/*.json, all six of which are derivable from the registries and are
split-brain on id convention (agent_math_routing.json keys
`agent:2d_game_ai_engineer`, agent_to_kg.json keys `2d-game-ai-engineer`),
so reading them would mean supporting a seventh convention for data already
held.
"""


@dataclass(frozen=True)
class LibrarySource:
    """A located claude-global-library, with its version and file mtimes."""

    root: Path
    library_version: str

    @property
    def master_dir(self) -> Path:
        """Directory holding the five master registries."""
        return self.root / MASTER_RELPATH

    @property
    def tree_dir(self) -> Path:
        """Directory holding the orchestration decision tree."""
        return self.root / TREE_RELPATH

    @property
    def skills_dir(self) -> Path:
        """Directory of skills/{name}/SKILL.md documents."""
        return self.root / "skills"

    @property
    def agents_dir(self) -> Path:
        """Directory of agents/{name}/agent.md documents."""
        return self.root / "agents"

    def registry_path(self, filename: str) -> Path:
        """Absolute path to one master registry file."""
        return self.master_dir / filename

    def read_json(self, path: Path) -> Any:
        """Parse one JSON file as utf-8.

        Raises:
            LibraryNotFoundError: If the file is missing, naming the path and
                the override environment variable, so a misconfigured library
                location reports itself instead of surfacing as an empty graph.
        """
        if not path.exists():
            raise LibraryNotFoundError(
                f"expected {path} under the library at {self.root}. "
                f"Set {ENV_LIBRARY_PATH} to override the library location."
            )
        return json.loads(path.read_text(encoding="utf-8"))

    def read_registry(self, filename: str) -> Any:
        """Parse one of the five master registries by filename."""
        return self.read_json(self.registry_path(filename))

    def read_markdown(self, path: Path) -> str:
        """Read one markdown document as utf-8-sig, stripping any BOM.

        See the module docstring: 13 library files are BOM'd, and a plain
        utf-8 read makes them look like they have no frontmatter at all.
        """
        return path.read_text(encoding="utf-8-sig")

    def fingerprint(self) -> tuple[str, tuple[tuple[str, str], ...]]:
        """Identify this library's exact content state.

        Returns:
            The library_version paired with each registry's (name, sha256).

        Version alone is not a content key. library_version moves per release,
        but an unreleased local edit does not move it -- and kg_version cannot
        help at all: it is `1.0.0` in every registry and is the SCHEMA version
        (derived from schema.json's own `version`, with a migration ledger at
        _master/migrations/), correctly frozen because the schema has not
        changed.

        Content hashes, not mtimes. This returned mtime_ns until the run
        manifest needed it, and mtime is wrong for that: a fresh `git clone`
        gives every file a new mtime, so a manifest keyed on mtime would report
        drift on byte-identical content and a replay could never succeed on
        another machine. The library's own `_discovery/index/manifest.json`
        already establishes sha256-per-source as the convention here.

        Costs one full read of the five registries, so call it when writing or
        replaying a manifest -- not per selection.
        """
        stamps = []
        for filename in REGISTRY_FILES:
            path = self.registry_path(filename)
            digest = ""
            if path.exists():
                hasher = hashlib.sha256()
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1 << 20), b""):
                        hasher.update(chunk)
                digest = hasher.hexdigest()
            stamps.append((filename, digest))
        return self.library_version, tuple(stamps)


def default_library_root() -> Path:
    """Where the library is expected without an explicit override.

    Resolved relative to THIS file rather than the current working directory,
    so behaviour does not depend on where a command was invoked from.
    """
    return Path(__file__).resolve().parents[2] / SIBLING_DIR_NAME


def locate_library(root: Path | str | None = None) -> LibrarySource:
    """Find the library and read its version.

    Args:
        root: Explicit library root. Falls back to KGF_LIBRARY_PATH, then to
            the sibling directory beside this repository.

    Returns:
        A LibrarySource for the located library.

    Raises:
        LibraryNotFoundError: If no directory is found, or one is found but
            holds no _master registries -- the second case catches a path
            pointing at the wrong directory, which otherwise looks like a
            library with nothing in it.
    """
    if root is not None:
        candidate = Path(root)
    else:
        override = os.environ.get(ENV_LIBRARY_PATH)
        candidate = Path(override) if override else default_library_root()

    candidate = candidate.expanduser()
    if not candidate.is_dir():
        raise LibraryNotFoundError(
            f"no claude-global-library at {candidate}. "
            f"Set {ENV_LIBRARY_PATH} to its location."
        )

    master = candidate / MASTER_RELPATH
    if not master.is_dir():
        raise LibraryNotFoundError(
            f"{candidate} exists but has no {MASTER_RELPATH} directory, so it is not a "
            f"claude-global-library checkout. Set {ENV_LIBRARY_PATH} to the right location."
        )

    return LibrarySource(root=candidate, library_version=_read_version(candidate))


def _read_version(root: Path) -> str:
    """Read the library's VERSION file, falling back to a registry's own field."""
    version_file = root / "VERSION"
    if version_file.exists():
        text = version_file.read_text(encoding="utf-8").strip()
        if text:
            return text

    registry = root / MASTER_RELPATH / "agents_all.json"
    if registry.exists():
        payload = json.loads(registry.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            declared = payload.get("library_version")
            if declared:
                return str(declared)
    return "unknown"
