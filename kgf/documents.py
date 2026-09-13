"""Read the markdown documents behind the registries.

M1 reads the generated registries; this reads the source documents. Both are
needed, because the registry build is lossy in a way that matters to ranking:

  147 of 528 agent records and 134 of 1034 skill records carry NO description
  in _master. Their markdown frontmatter carries one for ALL 281 of them --
  500 to 700 characters each. So the text was not missing, it was dropped, and
  a ranker built only on registry prose is blind to 281 entries for no reason.

Backfilling costs about 200ms for all 281, which is why this is a plain lazy
read rather than anything cleverer.

M2 needs only the frontmatter. Section-level parsing -- pulling
`## Coding Guidelines` out of a 37KB SKILL.md -- is M3's job and extends this
module rather than replacing it.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import yaml

from kgf.source import LibrarySource

logger = logging.getLogger(__name__)

FRONTMATTER_PATTERN = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)

KEYWORDS_PATTERN = re.compile(r"Keywords:\s*(.+)", re.IGNORECASE)


@dataclass(frozen=True)
class Document:
    """One parsed markdown document: its frontmatter and its body."""

    path: Path
    frontmatter: Mapping[str, Any] = field(default_factory=dict)
    body: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        """Whether the document parsed."""
        return not self.error

    @property
    def description(self) -> str:
        """The frontmatter description, or "" if absent or unparsed."""
        value = self.frontmatter.get("description")
        return value.strip() if isinstance(value, str) else ""

    @property
    def keywords(self) -> tuple[str, ...]:
        """Terms from the description's mandated `Keywords: ...` tail.

        Present on only 220 of 1034 skill descriptions, so this supplements
        the prose rather than replacing it -- a ranker keyed on Keywords alone
        would see a fifth of the corpus.
        """
        match = KEYWORDS_PATTERN.search(self.description)
        if not match:
            return ()
        terms = [term.strip().rstrip(".\"'") for term in match.group(1).split(",")]
        return tuple(term for term in terms if term)

    def declared_tools(self) -> tuple[str, ...]:
        """Tools named in frontmatter, tolerating both shapes.

        `tools:` on agents is a YAML list; `allowed-tools:` on skills is often
        a comma-separated string (74 of 569). Both appear, so both parse.
        """
        for key in ("tools", "allowed-tools", "allowed_tools"):
            value = self.frontmatter.get(key)
            if isinstance(value, str):
                parts = [part.strip() for part in value.split(",")]
                return tuple(part for part in parts if part)
            if isinstance(value, (list, tuple)):
                return tuple(str(item).strip() for item in value if str(item).strip())
        return ()


def parse_document(source: LibrarySource, path: Path) -> Document:
    """Parse one markdown document, returning a Document even on failure.

    A parse failure is reported in Document.error rather than raised: 18 of the
    library's 1562 documents are genuinely malformed, and one of them appearing
    in a closure must degrade that entry rather than abort the run.
    """
    if not path.exists():
        return Document(path=path, error="missing")

    try:
        text = source.read_markdown(path)
    except OSError as exc:
        return Document(path=path, error=f"unreadable: {exc}")

    match = FRONTMATTER_PATTERN.match(text)
    if match is None:
        return Document(path=path, error="no-frontmatter-block")

    try:
        frontmatter = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        return Document(path=path, error=f"yaml: {str(exc).splitlines()[0]}")

    if not isinstance(frontmatter, dict):
        return Document(path=path, error="frontmatter-not-a-mapping")

    return Document(path=path, frontmatter=frontmatter, body=match.group(2))


def skill_document(source: LibrarySource, skill_name: str) -> Document:
    """Parse one skill's SKILL.md by its directory name."""
    return parse_document(source, source.skills_dir / skill_name / "SKILL.md")


def agent_document(source: LibrarySource, agent_name: str) -> Document:
    """Parse one agent's agent.md by its directory name."""
    return parse_document(source, source.agents_dir / agent_name / "agent.md")


@lru_cache(maxsize=1)
def _backfill_cache(root: str) -> dict[str, str]:
    """Descriptions recovered from markdown for records whose registry lost them.

    Keyed by directory name, covering skills and agents together -- the two
    namespaces do not collide in practice and the callers ask by name.
    """
    from kgf.loader import load_graph

    source = LibrarySource(root=Path(root), library_version="")
    graph, _log = load_graph(root)

    recovered: dict[str, str] = {}
    for record, reader in (
        *((skill, skill_document) for skill in graph.skills.values() if not skill.description),
        *((agent, agent_document) for agent in graph.agents.values() if not agent.description),
    ):
        document = reader(source, record.name)
        if document.ok and document.description:
            recovered[record.name] = document.description

    if recovered:
        logger.info(
            "recovered %d description(s) from markdown that the registries do not carry",
            len(recovered),
        )
    return recovered


def backfilled_descriptions(source: LibrarySource) -> dict[str, str]:
    """Every description recoverable from markdown but absent from the registries.

    Returns:
        A mapping of record directory name to description text. Expected to
        hold 281 entries at library_version 29.97.4 (134 skills + 147 agents).
    """
    return _backfill_cache(str(source.root))
