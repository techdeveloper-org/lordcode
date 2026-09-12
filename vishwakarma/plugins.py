"""Pluggable skills + subagents, in the same flat file convention as the
user's claude-global-library (skills/{name}/SKILL.md, agents/{name}/agent.md).

A skill is a prompt-injection template auto-matched to a task by keyword
overlap (or forced with --skill), used to steer engine/generate.py toward a
specific stack's idioms (e.g. "spring-boot-api", "react-component").

A subagent is a persona system prompt that replaces the default system
prompt for one model role (e.g. a stricter test-writing persona applied to
the primary_coder role, or a more skeptical reviewer persona applied to the
reasoner role during self-heal).

Adding a new skill or subagent never touches this file or any engine code --
drop a new `skills/{name}/SKILL.md` or `agents/{name}/agent.md` and it is
picked up automatically on the next run.

In addition to Vishwakarma's own skills/agents/, load_all_skills() and
load_all_agents() also scan the user's claude-global-library (371 skills,
195 agents, same file format) so every persona/skill already written there
is matchable here too. Library entries are large, enterprise-oriented
documents (M1-M6 math, GSD sections, etc.) that would blow the 40 RPM/token
budget if injected whole, so only a bounded excerpt is used as the prompt
addition -- never the full file.
"""

from __future__ import annotations

import logging
import os
import re
from functools import lru_cache
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = PROJECT_ROOT / "skills"
AGENTS_DIR = PROJECT_ROOT / "agents"

DEFAULT_LIBRARY_ROOT = PROJECT_ROOT.parent / "claude-global-library"
LIBRARY_SNIPPET_MAX_CHARS = 800
KEYWORDS_PATTERN = re.compile(r"Keywords:\s*(.+)", re.IGNORECASE)
FRONTMATTER_PATTERN = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)


class PluginError(Exception):
    """Raised when a skill or subagent file is malformed."""


@dataclass(frozen=True)
class Skill:
    """A prompt-injection template auto-matched to a task by keyword overlap."""

    name: str
    description: str
    keywords: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    prompt_addition: str = ""


@dataclass(frozen=True)
class SubAgent:
    """A persona system prompt that can replace the default prompt for one role."""

    name: str
    description: str
    role: str = "primary_coder"
    system_prompt: str = ""


def _parse_frontmatter(path: Path) -> tuple[dict, str]:
    """Split a `---` YAML-frontmatter Markdown file into (metadata, body).

    Args:
        path: Path to the .md file.

    Returns:
        A (frontmatter dict, body markdown string) tuple.

    Raises:
        PluginError: If the file has no valid `---` frontmatter block.
    """
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_PATTERN.match(text)
    if match is None:
        raise PluginError(f"{path} is missing a '---' YAML frontmatter block on its own lines")

    try:
        frontmatter = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise PluginError(f"{path} has malformed YAML frontmatter: {exc}") from exc

    if not isinstance(frontmatter, dict):
        raise PluginError(f"{path} frontmatter did not parse to a mapping")

    return frontmatter, match.group(2).strip()


def _as_list(value: object) -> list[str]:
    """Normalize a YAML value that may be a comma-string or a list into a list[str]."""
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return [str(item) for item in value]


def load_skills(skills_dir: Path | None = None) -> list[Skill]:
    """Discover every `skills/{name}/SKILL.md` and load it as a Skill.

    Args:
        skills_dir: Optional override, defaults to the repository's skills/.

    Returns:
        All discovered skills, in directory-name sorted order.
    """
    directory = skills_dir or SKILLS_DIR
    if not directory.exists():
        return []

    skills: list[Skill] = []
    skipped = 0
    for skill_dir in sorted(p for p in directory.iterdir() if p.is_dir()):
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue
        try:
            frontmatter, body = _parse_frontmatter(skill_file)
        except PluginError as exc:
            logger.debug("Skipping unparsable skill file %s: %s", skill_file, exc)
            skipped += 1
            continue
        skills.append(
            Skill(
                name=frontmatter.get("name", skill_dir.name),
                description=frontmatter.get("description", ""),
                keywords=_as_list(frontmatter.get("keywords")),
                languages=_as_list(frontmatter.get("languages")),
                prompt_addition=body,
            )
        )
    if skipped:
        logger.info("Skipped %d unparsable skill file(s) under %s (set logging to DEBUG for details)", skipped, directory)
    return skills


def load_agents(agents_dir: Path | None = None) -> list[SubAgent]:
    """Discover every `agents/{name}/agent.md` and load it as a SubAgent.

    Args:
        agents_dir: Optional override, defaults to the repository's agents/.

    Returns:
        All discovered subagents, in directory-name sorted order.
    """
    directory = agents_dir or AGENTS_DIR
    if not directory.exists():
        return []

    agents: list[SubAgent] = []
    skipped = 0
    for agent_dir in sorted(p for p in directory.iterdir() if p.is_dir()):
        agent_file = agent_dir / "agent.md"
        if not agent_file.exists():
            continue
        try:
            frontmatter, body = _parse_frontmatter(agent_file)
        except PluginError as exc:
            logger.debug("Skipping unparsable agent file %s: %s", agent_file, exc)
            skipped += 1
            continue
        agents.append(
            SubAgent(
                name=frontmatter.get("name", agent_dir.name),
                description=frontmatter.get("description", ""),
                role=frontmatter.get("role", "primary_coder"),
                system_prompt=body,
            )
        )
    if skipped:
        logger.info("Skipped %d unparsable agent file(s) under %s (set logging to DEBUG for details)", skipped, directory)
    return agents


def match_skill(task: str, skills: list[Skill], language: str | None = None) -> Skill | None:
    """Pick the best skill for a task by keyword overlap, honoring a language filter.

    Args:
        task: The user's free-text task description.
        skills: Loaded skills to match against.
        language: If set, skills that declare a `languages` list must include it.

    Returns:
        The highest-scoring skill with at least one keyword hit, or None.
    """
    task_lower = task.lower()
    best: Skill | None = None
    best_score = 0
    for skill in skills:
        if skill.languages and language and language not in skill.languages:
            continue
        score = sum(1 for keyword in skill.keywords if keyword.lower() in task_lower)
        if score > best_score:
            best_score = score
            best = skill
    return best


def get_agent(name: str, agents: list[SubAgent]) -> SubAgent | None:
    """Look up a loaded subagent by name."""
    for agent in agents:
        if agent.name == name:
            return agent
    return None


def library_root() -> Path | None:
    """Resolve the claude-global-library path, if it exists.

    Checks the VISHWAKARMA_LIBRARY_PATH environment variable first, then
    falls back to the sibling `claude-global-library` directory next to
    this project.

    Returns:
        The library root path if it exists on disk, else None.
    """
    override = os.environ.get("VISHWAKARMA_LIBRARY_PATH")
    candidate = Path(override) if override else DEFAULT_LIBRARY_ROOT
    return candidate if candidate.exists() else None


def _extract_keywords(description: str) -> list[str]:
    """Pull the comma-separated terms out of a library description's
    "Keywords: ..." tail (the library's mandated 3-part description format).
    """
    match = KEYWORDS_PATTERN.search(description)
    if not match:
        return []
    return [term.strip().rstrip(".\"'") for term in match.group(1).split(",") if term.strip()]


def _bounded_excerpt(body: str, max_chars: int = LIBRARY_SNIPPET_MAX_CHARS) -> str:
    """Truncate a large library document body to a safe prompt-injection size."""
    stripped = body.strip()
    if len(stripped) <= max_chars:
        return stripped
    return stripped[:max_chars].rsplit("\n", 1)[0] + "\n... (truncated)"


def load_library_skills(root: Path | None = None) -> list[Skill]:
    """Load every skills/{name}/SKILL.md from the claude-global-library.

    Args:
        root: Optional override library path; defaults to library_root().

    Returns:
        All library skills, with keywords parsed from their description and
        prompt_addition truncated to LIBRARY_SNIPPET_MAX_CHARS.
    """
    base = root or library_root()
    if base is None:
        return []
    return load_skills(base / "skills")


def load_library_agents(root: Path | None = None) -> list[SubAgent]:
    """Load every agents/{name}/agent.md from the claude-global-library.

    Args:
        root: Optional override library path; defaults to library_root().

    Returns:
        All library agents, defaulted to the primary_coder role (they carry
        no `role` field of their own) with system_prompt truncated to
        LIBRARY_SNIPPET_MAX_CHARS.
    """
    base = root or library_root()
    if base is None:
        return []
    return load_agents(base / "agents")


@lru_cache(maxsize=1)
def load_all_skills() -> list[Skill]:
    """Load Vishwakarma's own skills plus every matchable library skill.

    Library skills' keywords are parsed from their "Keywords: ..." description
    tail (they have no dedicated `keywords` frontmatter field) and their body
    is truncated to a short excerpt before being usable as a prompt addition.

    Cached for the life of the process -- the library scan alone takes tens
    of seconds (hundreds of files), which is fine to pay once per CLI
    invocation but not once per request in the long-running webapp server.
    """
    own = load_skills()
    library: list[Skill] = []
    for skill in load_library_skills():
        library.append(
            Skill(
                name=skill.name,
                description=skill.description,
                keywords=skill.keywords or _extract_keywords(skill.description),
                languages=skill.languages,
                prompt_addition=_bounded_excerpt(skill.prompt_addition),
            )
        )
    return own + library


@lru_cache(maxsize=1)
def load_all_agents() -> list[SubAgent]:
    """Load Vishwakarma's own subagents plus every matchable library agent.

    Cached for the life of the process, same rationale as load_all_skills().
    """
    own = load_agents()
    library = [
        SubAgent(
            name=agent.name,
            description=agent.description,
            role=agent.role,
            system_prompt=_bounded_excerpt(agent.system_prompt),
        )
        for agent in load_library_agents()
    ]
    return own + library
