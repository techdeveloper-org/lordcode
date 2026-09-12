"""Unit tests for Milestone 3's fail-open MCP client wrapper.

Mocks the `mcp` SDK's stdio_client/ClientSession at the vishwakarma.mcp_client
import site -- no real server process is ever spawned by these tests.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from vishwakarma import mcp_client


class _FakeCallToolResult:
    def __init__(self, structured_content=None, is_error=False):
        self.structuredContent = structured_content
        self.content = []
        self.isError = is_error


class _FakeSessionCM:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc_info):
        return False


class _FakeStdioCM:
    def __init__(self, raise_on_enter: Exception | None = None):
        self._raise_on_enter = raise_on_enter

    async def __aenter__(self):
        if self._raise_on_enter:
            raise self._raise_on_enter
        return (MagicMock(), MagicMock())

    async def __aexit__(self, *exc_info):
        return False


def _make_fake_session(tool_results):
    session = MagicMock()

    async def _initialize():
        return None

    async def _call_tool(name, arguments):
        return tool_results.pop(0)

    session.initialize = _initialize
    session.call_tool = _call_tool
    return session


def test_call_mcp_tools_opens_exactly_one_session_for_a_batch(tmp_path):
    server_script = tmp_path / "server.py"
    server_script.write_text("# fake", encoding="utf-8")

    session = _make_fake_session(
        [
            _FakeCallToolResult(structured_content={"a": 1}),
            _FakeCallToolResult(structured_content={"b": 2}),
        ]
    )

    with patch.object(mcp_client, "stdio_client") as stdio_mock, \
         patch.object(mcp_client, "ClientSession") as session_ctor:
        stdio_mock.return_value = _FakeStdioCM()
        session_ctor.return_value = _FakeSessionCM(session)

        results = mcp_client.call_mcp_tools(server_script, [("tool_a", {}), ("tool_b", {})])

    assert stdio_mock.call_count == 1
    assert session_ctor.call_count == 1
    assert [r.ok for r in results] == [True, True]
    assert results[0].data == {"a": 1}
    assert results[1].data == {"b": 2}


def test_call_mcp_tools_isolates_individual_call_failure(tmp_path):
    server_script = tmp_path / "server.py"
    server_script.write_text("# fake", encoding="utf-8")

    session = _make_fake_session(
        [
            _FakeCallToolResult(structured_content={"ok": True}, is_error=False),
            _FakeCallToolResult(structured_content={"error": "boom"}, is_error=True),
        ]
    )

    with patch.object(mcp_client, "stdio_client") as stdio_mock, \
         patch.object(mcp_client, "ClientSession") as session_ctor:
        stdio_mock.return_value = _FakeStdioCM()
        session_ctor.return_value = _FakeSessionCM(session)

        results = mcp_client.call_mcp_tools(server_script, [("tool_a", {}), ("tool_b", {})])

    assert results[0].ok is True
    assert results[1].ok is False
    assert "boom" in results[1].error


def test_call_mcp_tools_fails_open_when_server_script_missing(tmp_path):
    missing = tmp_path / "does_not_exist.py"

    results = mcp_client.call_mcp_tools(missing, [("tool_a", {}), ("tool_b", {})])

    assert [r.ok for r in results] == [False, False]
    assert "not found" in results[0].error


def test_call_mcp_tools_fails_open_on_subprocess_start_failure(tmp_path):
    server_script = tmp_path / "server.py"
    server_script.write_text("# fake", encoding="utf-8")

    with patch.object(mcp_client, "stdio_client") as stdio_mock:
        stdio_mock.return_value = _FakeStdioCM(raise_on_enter=RuntimeError("subprocess failed to start"))

        results = mcp_client.call_mcp_tools(server_script, [("tool_a", {}), ("tool_b", {})])

    assert [r.ok for r in results] == [False, False]


def test_call_mcp_tool_wrapper_returns_single_result(tmp_path):
    server_script = tmp_path / "server.py"
    server_script.write_text("# fake", encoding="utf-8")

    session = _make_fake_session([_FakeCallToolResult(structured_content={"x": 1})])

    with patch.object(mcp_client, "stdio_client") as stdio_mock, \
         patch.object(mcp_client, "ClientSession") as session_ctor:
        stdio_mock.return_value = _FakeStdioCM()
        session_ctor.return_value = _FakeSessionCM(session)

        result = mcp_client.call_mcp_tool(server_script, "tool_a", {})

    assert result.ok is True
    assert result.data == {"x": 1}


def test_mcp_servers_resolves_to_correct_sibling_paths():
    # tests/ -> vishwakarma repo root -> workspace root -- same workspace
    # root mcp_client.py's own parents[2] must resolve to.
    workspace_root = Path(__file__).resolve().parents[2]

    assert mcp_client.MCP_SERVERS["uml-diagram"] == workspace_root / "mcp-uml-diagram" / "server.py"
    assert mcp_client.MCP_SERVERS["drawio-diagram"] == workspace_root / "mcp-drawio-diagram" / "server.py"
