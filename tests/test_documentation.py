"""Unit tests for Milestone 2's Mermaid documentation + SRS traceability.

Diagrams are generated as 4 genuinely parallel spawned OS processes, so
their model calls can reach the dispatcher in any order -- the FakeClient
here matches responses by a distinctive keyword in the system prompt
rather than by call order, to stay correct regardless of scheduling.
"""

from __future__ import annotations

import pytest

from vishwakarma.config import ModelConfig, RoleCandidate
from vishwakarma.engine import documentation as docs
from vishwakarma.engine.generate import GenerationError
from vishwakarma.engine.sdlc import srs_path_for
from vishwakarma.mcp_client import MCPToolResult
from vishwakarma.router import Router

VALID_SRS = """## 1. Purpose
Builds a thing.

## 3. Requirements
### 3.1 Functional Requirements
FR-001: Do the thing.
"""

VALID_MERMAID = "```mermaid\ngraph TD\n  A --> B\n```"
MALFORMED_MERMAID = "Sure, here is a diagram: A leads to B."

_KEYWORDS = {
    "class": "styled as a UML class diagram",
    "component": "components and how they connect",
    "sequence": "sequenceDiagram for the system's main use case",
    "usecase": "use-case diagram",
}
_TRACEABILITY_KEYWORD = "traceability matrix"


class FakeClient:
    """Returns a response keyed by a distinctive keyword found in the system
    prompt, since parallel-spawned agents' calls can arrive in any order.
    """

    def __init__(self, response_by_keyword: dict[str, object]):
        self.response_by_keyword = response_by_keyword
        self.call_log: list[str] = []

    def chat_completion(
        self, provider: str, model: str, messages: list[dict], priority: str = "interactive", **kwargs
    ) -> str:
        self.call_log.append(f"{provider}/{model}")
        system_content = messages[0]["content"]
        for keyword, response in self.response_by_keyword.items():
            if keyword in system_content:
                if isinstance(response, Exception):
                    raise response
                return response
        raise AssertionError(f"No fake response configured for system prompt: {system_content[:120]!r}")


def _models() -> ModelConfig:
    return ModelConfig(
        roles={"fallback_long_context": [RoleCandidate(provider="groq", model="long-context")]},
        max_heal_attempts=3,
        heal_timeout_seconds=300,
    )


@pytest.fixture(autouse=True)
def _no_real_mcp_server(monkeypatch, tmp_path):
    """Force the "MCP unavailable" fallback path deterministically.

    This dev machine genuinely has mcp-uml-diagram checked out as a real
    sibling -- without this, generate_docs() would spawn the real server
    process against these tests' tmp_path (finding no .py files, returning
    a degenerate-but-technically-valid "No classes found" diagram) instead
    of exercising the LLM fallback these Milestone 2 tests were written to
    test, silently changing what they assert on. Tests that specifically
    want to exercise the AST path override this within their own body.
    """
    monkeypatch.setitem(docs.MCP_SERVERS, "uml-diagram", tmp_path / "unused_nonexistent_server.py")


def _all_valid_client() -> FakeClient:
    return FakeClient(
        {
            _KEYWORDS["class"]: VALID_MERMAID,
            _KEYWORDS["component"]: VALID_MERMAID,
            _KEYWORDS["sequence"]: VALID_MERMAID,
            _KEYWORDS["usecase"]: VALID_MERMAID,
        }
    )


def test_generate_docs_writes_all_four_diagrams_with_frontmatter(tmp_path):
    client = _all_valid_client()
    router = Router(_models(), client)

    result = docs.generate_docs("srs text", "hld text", tmp_path, router, client)

    assert set(result.keys()) == {"class", "component", "sequence", "usecase"}
    for diagram_type in result:
        written = docs.diagram_path_for(tmp_path, diagram_type).read_text(encoding="utf-8")
        assert written.startswith(docs.DIAGRAM_FRONTMATTER)
        assert "```mermaid" in written


def test_generate_docs_isolates_single_diagram_failure(tmp_path):
    client = FakeClient(
        {
            _KEYWORDS["class"]: VALID_MERMAID,
            _KEYWORDS["component"]: VALID_MERMAID,
            _KEYWORDS["sequence"]: MALFORMED_MERMAID,  # no mermaid fence -- must be isolated, not fatal
            _KEYWORDS["usecase"]: VALID_MERMAID,
        }
    )
    router = Router(_models(), client)
    failures = []

    def on_event(event):
        if event["type"] == "diagram_generation_failed":
            failures.append(event)

    result = docs.generate_docs("srs text", "hld text", tmp_path, router, client, on_event=on_event)

    assert set(result.keys()) == {"class", "component", "usecase"}
    assert len(failures) == 1
    assert failures[0]["diagram_type"] == "sequence"
    assert not docs.diagram_path_for(tmp_path, "sequence").exists()
    for diagram_type in ("class", "component", "usecase"):
        assert docs.diagram_path_for(tmp_path, diagram_type).exists()


def test_generate_docs_isolates_dispatcher_side_error(tmp_path):
    client = FakeClient(
        {
            _KEYWORDS["class"]: RuntimeError("transient provider failure"),
            _KEYWORDS["component"]: VALID_MERMAID,
            _KEYWORDS["sequence"]: VALID_MERMAID,
            _KEYWORDS["usecase"]: VALID_MERMAID,
        }
    )
    router = Router(_models(), client)

    result = docs.generate_docs("srs text", "hld text", tmp_path, router, client)

    assert set(result.keys()) == {"component", "sequence", "usecase"}
    assert not docs.diagram_path_for(tmp_path, "class").exists()


def test_generate_traceability_appends_table_to_srs(tmp_path):
    srs_path = srs_path_for(tmp_path)
    srs_path.parent.mkdir(parents=True)
    srs_path.write_text(VALID_SRS, encoding="utf-8")

    client = FakeClient({_TRACEABILITY_KEYWORD: "| FR-001 | main.py |"})
    router = Router(_models(), client)

    result = docs.generate_traceability(VALID_SRS, ["main.py"], tmp_path, router, client)

    assert docs.TRACEABILITY_HEADING in result
    assert "FR-001" in result
    on_disk = srs_path.read_text(encoding="utf-8")
    assert on_disk == result


def test_generate_traceability_refuses_when_already_present(tmp_path):
    srs_with_matrix = VALID_SRS + f"\n\n{docs.TRACEABILITY_HEADING}\n\n| FR-001 | main.py |\n"
    client = FakeClient({_TRACEABILITY_KEYWORD: "should not be called"})
    router = Router(_models(), client)

    with pytest.raises(GenerationError, match="already present"):
        docs.generate_traceability(srs_with_matrix, ["main.py"], tmp_path, router, client)

    assert client.call_log == []


def test_list_source_files_excludes_tooling_dirs(tmp_path):
    (tmp_path / "docs" / "phase-0-requirements").mkdir(parents=True)
    (tmp_path / "docs" / "phase-0-requirements" / "SRS.md").write_text("x", encoding="utf-8")
    (tmp_path / "uml").mkdir()
    (tmp_path / "uml" / "class_diagram.md").write_text("x", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_main.py").write_text("x", encoding="utf-8")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "main.cpython-313.pyc").write_text("x", encoding="utf-8")
    (tmp_path / "main.py").write_text("print('hi')", encoding="utf-8")

    files = docs.list_source_files(tmp_path)

    assert files == ["main.py"]


def _ast_tool_name(diagram_type: str) -> str:
    return f"generate_{diagram_type}_diagram"


def test_generate_docs_prefers_ast_over_llm_when_mcp_available(tmp_path, monkeypatch):
    fake_server = tmp_path / "fake_uml_server.py"
    fake_server.write_text("# fake", encoding="utf-8")
    monkeypatch.setitem(docs.MCP_SERVERS, "uml-diagram", fake_server)

    ast_files = {}
    for diagram_type in docs.AST_DIAGRAM_TYPES:
        p = tmp_path / f"{diagram_type}_ast_source.md"
        p.write_text(f"```mermaid\ngraph TD\n  {diagram_type} --> X\n```", encoding="utf-8")
        ast_files[diagram_type] = p

    def fake_call_mcp_tools(server_script, calls):
        results = []
        for tool_name, _args in calls:
            diagram_type = tool_name[len("generate_"):-len("_diagram")]
            results.append(MCPToolResult(ok=True, data={"output_file": str(ast_files[diagram_type])}))
        return results

    monkeypatch.setattr(docs, "call_mcp_tools", fake_call_mcp_tools)

    client = FakeClient({_KEYWORDS["usecase"]: VALID_MERMAID})
    router = Router(_models(), client)
    sources = []

    def on_event(event):
        if event["type"] == "diagram_source":
            sources.append(event)

    result = docs.generate_docs("srs text", "hld text", tmp_path, router, client, on_event=on_event)

    assert set(result.keys()) == {"class", "component", "sequence", "usecase"}
    # Only usecase (no AST equivalent) went through the LLM -- class/component/sequence resolved via AST.
    assert client.call_log == ["groq/long-context"]
    assert {e["diagram_type"]: e["source"] for e in sources} == {
        "class": "ast",
        "component": "ast",
        "sequence": "ast",
        "usecase": "llm",
    }


def test_generate_docs_falls_back_to_llm_for_types_where_ast_call_fails(tmp_path, monkeypatch):
    fake_server = tmp_path / "fake_uml_server.py"
    fake_server.write_text("# fake", encoding="utf-8")
    monkeypatch.setitem(docs.MCP_SERVERS, "uml-diagram", fake_server)

    component_file = tmp_path / "component_ast_source.md"
    component_file.write_text(VALID_MERMAID, encoding="utf-8")

    def fake_call_mcp_tools(server_script, calls):
        results = []
        for tool_name, _args in calls:
            diagram_type = tool_name[len("generate_"):-len("_diagram")]
            if diagram_type == "component":
                results.append(MCPToolResult(ok=True, data={"output_file": str(component_file)}))
            else:
                results.append(MCPToolResult(ok=False, error="AST analysis failed"))
        return results

    monkeypatch.setattr(docs, "call_mcp_tools", fake_call_mcp_tools)

    client = FakeClient(
        {
            _KEYWORDS["class"]: VALID_MERMAID,
            _KEYWORDS["sequence"]: VALID_MERMAID,
            _KEYWORDS["usecase"]: VALID_MERMAID,
        }
    )
    router = Router(_models(), client)

    result = docs.generate_docs("srs text", "hld text", tmp_path, router, client)

    assert set(result.keys()) == {"class", "component", "sequence", "usecase"}
    # class + sequence fell through to the LLM (AST failed for them); usecase always LLM;
    # component resolved via AST, so exactly 3 LLM calls, not 4.
    assert len(client.call_log) == 3


def test_generate_docs_falls_back_to_llm_on_degraded_ast_output(tmp_path, monkeypatch):
    """A tool call that returns ok=True but non-mermaid content (e.g. the
    AST server's own sibling-resolution failed internally) must still fall
    through to the LLM path -- ok=True alone is not trusted, per the
    _has_mermaid_fence() content check (review Gap 6's mitigation)."""
    fake_server = tmp_path / "fake_uml_server.py"
    fake_server.write_text("# fake", encoding="utf-8")
    monkeypatch.setitem(docs.MCP_SERVERS, "uml-diagram", fake_server)

    degraded_file = tmp_path / "class_degraded.md"
    degraded_file.write_text("no mermaid content here", encoding="utf-8")

    def fake_call_mcp_tools(server_script, calls):
        results = []
        for tool_name, _args in calls:
            diagram_type = tool_name[len("generate_"):-len("_diagram")]
            if diagram_type == "class":
                results.append(MCPToolResult(ok=True, data={"output_file": str(degraded_file)}))
            else:
                results.append(MCPToolResult(ok=False, error="not attempted"))
        return results

    monkeypatch.setattr(docs, "call_mcp_tools", fake_call_mcp_tools)

    client = _all_valid_client()
    router = Router(_models(), client)

    result = docs.generate_docs("srs text", "hld text", tmp_path, router, client)

    assert set(result.keys()) == {"class", "component", "sequence", "usecase"}
    assert len(client.call_log) == 4  # degraded AST output rejected -- class also went through the LLM
