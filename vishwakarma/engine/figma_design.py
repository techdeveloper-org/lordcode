"""Milestone 6: UI/UX via Figma, scoped to the local, read-only mcp-figma
server -- real file/wireframe creation was investigated and dropped (Figma's
remote MCP server gates its OAuth mcp:connect scope to an approved-partner
waitlist with no guaranteed timeline; see the project plan for the full
investigation). This module extracts design tokens and runs an accessibility
scan against a Figma file the user already has, given its file_key.

mcp-figma requires FIGMA_ACCESS_TOKEN in its own process environment. The
`mcp` SDK's stdio transport does NOT inherit the caller's full environment by
default -- it uses a small, fixed allowlist that excludes credential env
vars -- so every call here passes env={**os.environ} explicitly through
mcp_client's env parameter.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from vishwakarma.engine.calling import OnEvent, noop_event
from vishwakarma.engine.generate import GenerationError
from vishwakarma.mcp_client import MCP_SERVERS, call_mcp_tool

FIGMA_ACCESS_TOKEN_ENV_VAR = "FIGMA_ACCESS_TOKEN"


def _figma_env() -> dict[str, str]:
    """Pass the caller's full environment through, so FIGMA_ACCESS_TOKEN
    (which the mcp SDK's default stdio env allowlist would otherwise drop)
    reaches the spawned mcp-figma server process."""
    return {**os.environ}


def has_figma_token() -> bool:
    """Cheap, deterministic pre-flight check -- no MCP call needed."""
    return bool(os.environ.get(FIGMA_ACCESS_TOKEN_ENV_VAR))


def design_tokens_path_for(workdir: Path) -> Path:
    """Return the conventional design_tokens.json path for a workdir,
    matching claude-global-library's ORCHESTRATION_TEMPLATE.md Phase 3
    (UI/UX Design) folder name exactly, same as Milestone 1's
    docs/phase-N-name/ convention."""
    return workdir / "docs" / "phase-3-design" / "design_tokens.json"


def extract_design_tokens(file_key: str, workdir: Path, on_event: OnEvent = noop_event) -> dict:
    """Extract design tokens + run an accessibility scan for an existing
    Figma file, writing both to docs/phase-3-design/design_tokens.json.

    Args:
        file_key: The target Figma file's key (from its URL).
        workdir: Project directory; tokens are written under its docs/ tree.
        on_event: Progress event sink.

    Returns:
        The combined {"tokens": ..., "accessibility": ...} dict written.

    Raises:
        GenerationError: If token extraction itself fails -- this is the
            core deliverable and a real, actionable error (bad file_key,
            invalid token, unreachable API). The accessibility scan is a
            bonus check: its failure is logged, not raised.
    """
    env = _figma_env()
    figma_server = MCP_SERVERS["figma"]

    tokens_result = call_mcp_tool(figma_server, "figma_extract_design_tokens", {"file_key": file_key}, env=env)
    if not tokens_result.ok:
        raise GenerationError(f"figma_extract_design_tokens failed for {file_key}: {tokens_result.error}")

    accessibility_result = call_mcp_tool(
        figma_server, "figma_scan_color_accessibility", {"file_key": file_key}, env=env
    )
    if not accessibility_result.ok:
        on_event({"type": "figma_accessibility_scan_failed", "reason": accessibility_result.error})
        accessibility_data = None
    else:
        accessibility_data = accessibility_result.data

    combined = {"tokens": tokens_result.data, "accessibility": accessibility_data}

    tokens_path = design_tokens_path_for(workdir)
    tokens_path.parent.mkdir(parents=True, exist_ok=True)
    tokens_path.write_text(json.dumps(combined, indent=2), encoding="utf-8")

    on_event({"type": "figma_design_tokens_extracted", "file_key": file_key})
    return combined


def generate_css_from_figma(
    file_key: str,
    node_id: str,
    component_name: str,
    workdir: Path,
    on_event: OnEvent = noop_event,
) -> str:
    """Generate CSS for one Figma node, writing to docs/phase-3-design/component.css.

    Raises:
        GenerationError: If figma_generate_css_component fails.
    """
    env = _figma_env()
    result = call_mcp_tool(
        MCP_SERVERS["figma"],
        "figma_generate_css_component",
        {"file_key": file_key, "node_id": node_id, "component_name": component_name},
        env=env,
    )
    if not result.ok:
        raise GenerationError(f"figma_generate_css_component failed for {file_key}/{node_id}: {result.error}")

    css = result.data.get("css", "")
    css_path = workdir / "docs" / "phase-3-design" / "component.css"
    css_path.parent.mkdir(parents=True, exist_ok=True)
    css_path.write_text(css, encoding="utf-8")

    on_event({"type": "figma_css_generated", "component_name": component_name})
    return css
