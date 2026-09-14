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
"""A PORTABILITY FLOOR, not a regression guard -- and the distinction is load-bearing.

Measured on the development machine, a warm load's floor is ~73ms, so this looks
like 4x headroom. It is not: across ten 5-sample windows the *minimum* was itself
inflated to 128ms by ordinary background load, which puts real headroom at ~2.3x.
So this number exists to survive unknown client hardware -- a 2x slower machine
must not fail on delivery -- and nothing short of roughly a 2x regression will
trip it. A tighter budget would be a better regression guard and a worse
portability floor, and portability is what a handover needs.

It stands behind ADR-4: raw json.load is cheap enough that a disk cache would add
an invalidation failure class to solve a problem that does not exist.
"""

WARM_LOAD_SAMPLES = 5
"""How many samples the floor is taken over. Chosen from p**N, not by feel.

A single sample cannot distinguish "the load got slower" from "the machine was
busy for 400ms", which is why this test went red three times while passing in
isolation. Contention's additive component (preemption, page faults, GC pauses)
can only ever make a sample slower, so the MINIMUM of several estimates the
uncontended cost -- timeit's own rationale for min() over mean().

What N buys, stated rather than implied: min-of-N fails with p**N. At the benign
spike rate measured here (~1 in 9) N=5 leaves 1.6e-5. But the 508ms reading that
prompted this implies a machine ~6.7x oversubscribed, where p approaches 1 and no
practical N helps -- five samples at that speed span 2.5s, far longer than the
spike they would have to dodge. THIS REDUCES THE FLAKE; IT DOES NOT ELIMINATE IT.
If it fires again, the answer is a `-m perf` marker, not a larger N and not a
larger budget.

Not asserted on the maximum. `P(max > t)` grows with N, so a tail ceiling
reintroduces at the upper tail exactly the sensitivity min() is here to escape:
over the same ten windows, min swung 1.8x (72->128ms) while max swung 8.9x
(79->642ms). The cost is that a tail-only regression is invisible to this test,
which matters because a four-server MCP compose pays its slowest build rather
than its fastest -- that belongs in a benchmark outside the suite, not in a
tripwire that cries wolf.
"""


def test_the_pin_is_not_stale(graph, at_pinned_version, pinned_version):
    """A stale pin must fail HERE, loudly, rather than everywhere else silently.

    Every exact-count assertion in this suite is guarded by `at_pinned_version`
    and falls back to a bounded one when it is False. That is the right design
    for a library that moves -- but it means a stale pin does not turn the suite
    red. It turns the measured assertions off: `null_ids == 591` becomes
    `null_ids >= 0`, the tier clamp becomes a truthy-list check, and the four
    grant counts are skipped entirely, all while the suite reports green.

    So the pin itself needs one unguarded assertion. This is it. When it fails,
    the fix is to re-measure the figures against the new library and move the
    pin -- in that order -- not to widen anything.
    """
    assert at_pinned_version, (
        f"library is {graph.library_version}, suite is pinned to "
        f"{pinned_version}. While these differ, every exact-count "
        "assertion in tests/kgf silently degrades to a bounded one. Re-measure, "
        "then re-pin."
    )


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


def _summarise(samples: list[float]) -> tuple[float, str]:
    """Reduce timing samples to the floor, and to a message that names the cause.

    Pure and test-only by design: it owns no clock and never touches the library,
    so the estimator can be tested against a scripted list in microseconds rather
    than by running the thing it measures. Keeping it out of `kgf/loader.py` also
    keeps a test-harness concern out of the package a client installs.

    Returning the message alongside the value is the point. A failure reading
    `min=412ms samples=[412, 455, 430, 501, 447]` says the machine was loaded; one
    reading `min=310ms samples=[310, 315, 312, 318, 311]` says the load genuinely
    got slower. Those are different bugs with different fixes, and a message
    carrying only the minimum forces the next person to re-derive which one they
    are looking at -- which is how this test consumed three separate diagnoses.

    Args:
        samples: Elapsed times in milliseconds, one per measured run.

    Returns:
        The minimum sample, and a human-readable summary listing every sample.
    """
    floor = min(samples)
    listed = ", ".join(f"{sample:.0f}" for sample in samples)
    return floor, f"min={floor:.0f}ms samples=[{listed}]"


def test_the_sample_summary_reports_the_floor_and_every_sample():
    """The falsifiable half of the budget test, and the only gate that can fail fast.

    Running the suite twice and seeing green cannot prove this fix works: the
    defect fired 3 times out of an unknown denominator, so two passes are equally
    consistent with "fixed" and "unchanged". This is the assertion that is not
    vacuous -- it fails the instant someone swaps min for mean, or drops the
    sample list from the message, and it does so without measuring anything.
    """
    floor, message = _summarise([70.0, 500.0, 80.0, 600.0, 75.0])

    assert floor == 70.0, "the floor is the minimum, not the mean or the median"
    for sample in ("70", "500", "80", "600", "75"):
        assert sample in message, f"the message must list every sample; {sample} is missing"


def test_warm_load_is_within_budget(library):
    """A warm load's floor must stay under budget, which is what ADR-4 rests on.

    Warm, that load is ~76ms: about 31ms of json parsing plus about 45ms of graph
    building. Asserted on the minimum of several samples rather than on one, for
    the reasons WARM_LOAD_SAMPLES records.
    """
    load_graph(library.root)

    samples = []
    for _ in range(WARM_LOAD_SAMPLES):
        started = time.perf_counter()
        load_graph(library.root)
        samples.append((time.perf_counter() - started) * 1000)

    floor, message = _summarise(samples)
    assert floor < WARM_LOAD_BUDGET_MS, f"warm load {message}, budget {WARM_LOAD_BUDGET_MS}ms"


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
