"""Unit tests for Milestone 1.6's KG/decision-tree routing wrapper.

route_persona() is fail-open by design: any import failure, unresolved
status, or exception must return None rather than propagate, so the
orchestrator's plugins.match_skill()/get_agent() fallback is always safe.
"""

from __future__ import annotations

import sys
import types

import pytest

from vishwakarma.engine.kg_routing import KGRouteResult, route_persona

_MODULE_PATH = "langgraph_engine.routing.kg_router"


def _install_fake_kg_router(route_task_fn) -> None:
    package = types.ModuleType("langgraph_engine")
    routing_package = types.ModuleType("langgraph_engine.routing")
    kg_router_module = types.ModuleType(_MODULE_PATH)
    kg_router_module.route_task = route_task_fn
    sys.modules["langgraph_engine"] = package
    sys.modules["langgraph_engine.routing"] = routing_package
    sys.modules[_MODULE_PATH] = kg_router_module


@pytest.fixture(autouse=True)
def _clean_fake_modules():
    yield
    for name in ("langgraph_engine", "langgraph_engine.routing", _MODULE_PATH):
        sys.modules.pop(name, None)


def test_route_persona_returns_none_when_import_fails():
    for name in ("langgraph_engine", "langgraph_engine.routing", _MODULE_PATH):
        sys.modules.pop(name, None)
    sys.modules["langgraph_engine"] = None  # forces ImportError on import
    try:
        assert route_persona("build a React dashboard") is None
    finally:
        sys.modules.pop("langgraph_engine", None)


def test_route_persona_maps_resolved_dict_to_result():
    _install_fake_kg_router(
        lambda task: {
            "status": "resolved",
            "domain": "domain:frontend-engineering",
            "pattern_id": "pattern:1",
            "lead_agent": {"name": "app-squad-lead"},
            "skills": ["react-component"],
            "persona_markdown": "# App Squad Lead\n...",
            "trace": "D01->D14->pattern:1",
        }
    )

    result = route_persona("build a React dashboard")

    assert result == KGRouteResult(
        domain="domain:frontend-engineering",
        pattern_id="pattern:1",
        lead_agent_name="app-squad-lead",
        persona_markdown="# App Squad Lead\n...",
        skills=["react-component"],
        trace="D01->D14->pattern:1",
    )


def test_route_persona_returns_none_on_unresolved_status():
    _install_fake_kg_router(lambda task: {"status": "unresolved"})
    assert route_persona("something obscure") is None


def test_route_persona_returns_none_on_library_missing_status():
    _install_fake_kg_router(lambda task: {"status": "library_missing"})
    assert route_persona("anything") is None


def test_route_persona_returns_none_when_route_task_raises():
    def _boom(task):
        raise RuntimeError("resolver blew up")

    _install_fake_kg_router(_boom)
    assert route_persona("anything") is None


def test_route_persona_returns_none_when_persona_markdown_missing():
    _install_fake_kg_router(
        lambda task: {
            "status": "resolved",
            "domain": "domain:frontend-engineering",
            "pattern_id": "pattern:1",
            "lead_agent": {"name": "app-squad-lead"},
            "skills": [],
            "persona_markdown": "",
            "trace": "D01->D14->pattern:1",
        }
    )
    assert route_persona("build a React dashboard") is None
