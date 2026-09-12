"""Unit tests for the Figma milestone's figma_design.py.

Mocks figma_design.call_mcp_tool (monkeypatched at the module namespace,
same pattern as test_git_ops.py's git_ops.call_mcp_tool patching) so no real
mcp-figma server process is ever spawned.
"""

from __future__ import annotations

import json

import pytest

from vishwakarma.engine import figma_design
from vishwakarma.engine.generate import GenerationError
from vishwakarma.mcp_client import MCPToolResult


def test_has_figma_token_true_when_set(monkeypatch):
    monkeypatch.setenv("FIGMA_ACCESS_TOKEN", "figd_abc123")
    assert figma_design.has_figma_token() is True


def test_has_figma_token_false_when_unset(monkeypatch):
    monkeypatch.delenv("FIGMA_ACCESS_TOKEN", raising=False)
    assert figma_design.has_figma_token() is False


def test_extract_design_tokens_writes_combined_json(tmp_path, monkeypatch):
    responses = [
        MCPToolResult(ok=True, data={"colors": ["#fff"]}),
        MCPToolResult(ok=True, data={"violations": []}),
    ]
    monkeypatch.setattr(figma_design, "call_mcp_tool", lambda *a, **k: responses.pop(0))
    events = []

    result = figma_design.extract_design_tokens("FILEKEY", tmp_path, on_event=events.append)

    assert result == {"tokens": {"colors": ["#fff"]}, "accessibility": {"violations": []}}
    written = json.loads(figma_design.design_tokens_path_for(tmp_path).read_text(encoding="utf-8"))
    assert written == result
    assert {"type": "figma_design_tokens_extracted", "file_key": "FILEKEY"} in events


def test_extract_design_tokens_raises_on_token_extraction_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(
        figma_design, "call_mcp_tool", lambda *a, **k: MCPToolResult(ok=False, error="invalid token")
    )

    with pytest.raises(GenerationError, match="invalid token"):
        figma_design.extract_design_tokens("FILEKEY", tmp_path)

    assert not figma_design.design_tokens_path_for(tmp_path).exists()


def test_extract_design_tokens_does_not_raise_on_accessibility_failure(tmp_path, monkeypatch):
    responses = [
        MCPToolResult(ok=True, data={"colors": ["#fff"]}),
        MCPToolResult(ok=False, error="scan unavailable"),
    ]
    monkeypatch.setattr(figma_design, "call_mcp_tool", lambda *a, **k: responses.pop(0))
    events = []

    result = figma_design.extract_design_tokens("FILEKEY", tmp_path, on_event=events.append)

    assert result == {"tokens": {"colors": ["#fff"]}, "accessibility": None}
    assert {"type": "figma_accessibility_scan_failed", "reason": "scan unavailable"} in events


def test_extract_design_tokens_passes_full_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("FIGMA_ACCESS_TOKEN", "figd_abc123")
    captured_envs = []

    def fake_call_mcp_tool(server_script, tool_name, arguments, env=None):
        captured_envs.append(env)
        return MCPToolResult(ok=True, data={})

    monkeypatch.setattr(figma_design, "call_mcp_tool", fake_call_mcp_tool)

    figma_design.extract_design_tokens("FILEKEY", tmp_path)

    assert len(captured_envs) == 2
    for env in captured_envs:
        assert env is not None
        assert env.get("FIGMA_ACCESS_TOKEN") == "figd_abc123"


def test_generate_css_from_figma_writes_css(tmp_path, monkeypatch):
    monkeypatch.setattr(
        figma_design, "call_mcp_tool", lambda *a, **k: MCPToolResult(ok=True, data={"css": ".btn { color: red; }"})
    )
    events = []

    result = figma_design.generate_css_from_figma("FILEKEY", "1:2", "Button", tmp_path, on_event=events.append)

    assert result == ".btn { color: red; }"
    css_path = tmp_path / "docs" / "phase-3-design" / "component.css"
    assert css_path.read_text(encoding="utf-8") == ".btn { color: red; }"
    assert {"type": "figma_css_generated", "component_name": "Button"} in events


def test_generate_css_from_figma_raises_on_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(figma_design, "call_mcp_tool", lambda *a, **k: MCPToolResult(ok=False, error="bad node"))

    with pytest.raises(GenerationError, match="bad node"):
        figma_design.generate_css_from_figma("FILEKEY", "1:2", "Button", tmp_path)
