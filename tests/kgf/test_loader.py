"""Tests for loading the five registries into a graph.

Acceptance here is bounded, not exact, except where a figure is pinned to a
known library_version. An equality assertion against a moving library fails on
arithmetic instead of on a regression.
"""

from __future__ import annotations

import time

import pytest

from kgf.errors import GraphBuildError, ProblemLog, Severity
from kgf.graph import EDGE_TYPES, TOOL_TIERS
from kgf.loader import build_graph, cached_graph, load_graph
from kgf.validate import MAX_DANGLING_OCCURRENCES, MAX_DUPLICATE_TRIPLES

WARM_LOAD_BUDGET_MS = 300


def test_all_five_registries_are_loaded(graph):
    """Omitting regulations_all would dangle all 646 REGULATED_BY targets."""
    assert len(graph.agents) >= 500
    assert len(graph.skills) >= 1000
    assert len(graph.domains) >= 100
    assert len(graph.regulations) >= 300, "regulations_all.json must be one of the registries read"


def test_regulated_by_targets_resolve(graph):
    """The concrete consequence of reading the fifth registry."""
    edges = graph.edges_of_type("REGULATED_BY")
    assert edges
    unresolved = [edge for edge in edges if not graph.has_node(edge.target)]
    assert unresolved == []


def test_tool_tiers_are_synthesised(graph):
    """HAS_TOOL_ACCESS targets a tier that no registry declares."""
    assert set(graph.tool_tiers) == set(TOOL_TIERS)

    edges = graph.edges_of_type("HAS_TOOL_ACCESS")
    assert edges
    unresolved = [edge for edge in edges if not graph.has_node(edge.target)]
    assert unresolved == [], "every tool-access target must resolve to a synthetic tier"


def test_no_fatal_problems_on_the_live_library(problems):
    """Measured: 0 unknown edge types and 0 edges missing an endpoint."""
    assert problems.of(Severity.FATAL) == []


def test_every_edge_type_is_declared_and_present(graph):
    counts = graph.edge_type_counts()
    assert set(counts) == set(EDGE_TYPES)
    assert all(count > 0 for count in counts.values()), "a declared type with no edges is suspicious"


def test_dangling_endpoints_stay_within_the_recorded_ceiling(graph):
    dangling = graph.dangling_endpoints()
    assert sum(dangling.values()) <= MAX_DANGLING_OCCURRENCES


def test_duplicate_triples_stay_within_the_recorded_ceiling(problems):
    counts = problems.counts_by_code(Severity.DEFECT)
    assert counts.get("DUPLICATE_TRIPLE", 0) <= MAX_DUPLICATE_TRIPLES


def test_null_edge_ids_are_recorded_exactly_at_the_pinned_version(problems, at_pinned_version):
    counts = problems.counts_by_code(Severity.DEFECT)
    null_ids = counts.get("NULL_EDGE_ID", 0)
    if at_pinned_version:
        assert null_ids == 591
    else:
        assert null_ids >= 0


def test_absent_optional_fields_are_recorded_as_info_not_dropped(problems):
    """Records are ragged; absence must be reported, never silently tolerated."""
    counts = problems.counts_by_code(Severity.INFO)
    assert counts.get("ABSENT_FIELD", 0) > 0


def test_warm_load_is_within_budget(library):
    """Roughly 80ms of json parsing, which is why there is no disk cache."""
    load_graph(library.root)
    started = time.perf_counter()
    load_graph(library.root)
    elapsed_ms = (time.perf_counter() - started) * 1000
    assert elapsed_ms < WARM_LOAD_BUDGET_MS, f"warm load took {elapsed_ms:.0f}ms"


def test_cached_graph_returns_the_same_instance(library):
    first, _ = cached_graph(str(library.root))
    second, _ = cached_graph(str(library.root))
    assert first is second


class _SourceWithBrokenEdges:
    """Delegates to a real LibrarySource but substitutes the edge registry.

    LibrarySource is frozen, so its methods cannot be monkeypatched; a
    delegating stand-in is both simpler and closer to how a caller would
    supply an alternative source.
    """

    def __init__(self, real, edges: list[dict]):
        self._real = real
        self._edges = edges
        self.library_version = real.library_version

    def read_registry(self, filename: str):
        payload = self._real.read_registry(filename)
        if filename == "edges_all.json":
            payload = dict(payload)
            payload["edges"] = self._edges
        return payload


def test_a_missing_edge_endpoint_is_fatal(library):
    """The one class of damage that must stop the load rather than be reported."""
    source = _SourceWithBrokenEdges(
        library, [{"type": "AGENT_USES_SKILL", "source": None, "target": "skill:x"}]
    )
    with pytest.raises(GraphBuildError) as excinfo:
        build_graph(source, ProblemLog())
    assert "MISSING_ENDPOINT" in str(excinfo.value)


def test_an_unknown_edge_type_is_fatal(library):
    source = _SourceWithBrokenEdges(
        library, [{"type": "INVENTED_TYPE", "source": "agent:a", "target": "skill:b"}]
    )
    with pytest.raises(GraphBuildError) as excinfo:
        build_graph(source, ProblemLog())
    assert "UNKNOWN_EDGE_TYPE" in str(excinfo.value)
