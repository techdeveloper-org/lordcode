"""Milestone 1.6: route a task's lead persona via the real KG/decision-tree,
instead of Vishwakarma's own ad-hoc keyword matcher (plugins.match_skill()).

claude-global-library's actual per-task routing path is
knowledge-graph/_orchestration-decision-tree/ -- a literal decision tree
(decision_nodes.json/decision_branches.json) whose D14 outcome resolves to
one of 105 patterns.json entries, each a {lead_domain, lead_agent, lead_math}
role->agent lookup. The sibling repo claude-workflow-engine already
implements a tested, non-LLM traversal of this exact data at
langgraph_engine.routing.kg_router.route_task() -- keyword-scoring the task
against patterns.json, resolving the winning pattern's lead_agent to that
domain's real agent.md persona text via a 3-tier ResourceResolver (local
sibling / GitHub fallback / hard fail). Reusing it here, rather than
extending Vishwakarma's own simpler matcher, follows this project's
established "rely on claude-global-library, don't reimplement it" precedent.

Deliberately excludes the tree's D01-D13 human pre-flight nodes: as
kg_lookup.py's own docstring documents, there is no human available to
answer them in this single-task, non-interactive routing use case, so
traversal enters directly at D14 -- Vishwakarma inherits that same scoping.

This module is fail-open by design: any import failure (the sibling
claude-workflow-engine repo not being on sys.path), an "unresolved"/
"library_missing" status, or any other exception during the call all
resolve to route_persona() returning None, so callers can fall back to
today's plugins.match_skill()/get_agent() path with zero behavior change
when the sibling repo isn't present.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SIBLING_ENGINE_DIR_NAME = "claude-workflow-engine"


@dataclass(frozen=True)
class KGRouteResult:
    """One resolved routing decision from the real orchestration decision tree."""

    domain: str
    pattern_id: str
    lead_agent_name: str
    persona_markdown: str
    skills: list[Any]
    trace: str


def _ensure_workflow_engine_on_path() -> None:
    """Add the sibling claude-workflow-engine repo to sys.path if present.

    Mirrors resolver.py's own sibling-detection convention (relative to this
    file's location, not the caller's cwd) -- vishwakarma/vishwakarma/engine/
    is 3 parents below the workspace root that both repos live under.
    """
    workspace_root = Path(__file__).resolve().parents[3]
    engine_root = workspace_root / _SIBLING_ENGINE_DIR_NAME
    if engine_root.is_dir() and str(engine_root) not in sys.path:
        sys.path.insert(0, str(engine_root))


def route_persona(task: str) -> KGRouteResult | None:
    """Resolve task's lead persona via claude-workflow-engine's KGRouter.

    Args:
        task: The engineered task description to route.

    Returns:
        A KGRouteResult if the sibling claude-workflow-engine repo is
        importable and the decision tree resolved a confident match;
        otherwise None (caller should fall back to its own matching).
    """
    _ensure_workflow_engine_on_path()
    try:
        from langgraph_engine.routing.kg_router import route_task
    except ImportError:
        return None

    try:
        result = route_task(task)
    except Exception:  # noqa: BLE001 -- any routing failure must fail open, not crash the pipeline
        return None

    if not isinstance(result, dict) or result.get("status") != "resolved":
        return None

    lead_agent = result.get("lead_agent") or {}
    lead_agent_name = lead_agent.get("name") if isinstance(lead_agent, dict) else lead_agent
    if not lead_agent_name or not result.get("persona_markdown"):
        return None

    return KGRouteResult(
        domain=str(result.get("domain", "")),
        pattern_id=str(result.get("pattern_id", "")),
        lead_agent_name=str(lead_agent_name),
        persona_markdown=str(result["persona_markdown"]),
        skills=list(result.get("skills") or []),
        trace=str(result.get("trace", "")),
    )
