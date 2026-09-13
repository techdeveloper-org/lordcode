"""kgf's own authored phase topology over the library's 44 phases.

ADR-5. The library names 44 phases in `_orchestration-decision-tree/phases.json`
and models no dependency between any two of them: those records carry exactly
three keys -- `group`, `id`, `title` -- and no `depends_on`, `steps`, `order`,
`inputs` or `outputs` field exists anywhere in that directory. A DAG cannot be
read from the library, only authored against it. So kgf invents this graph,
owns it, and maintains it against a library that does not model it.

Every node is labelled with where its placement came from. Measured over the
44: 13 carry traversal.md#6.3, 3 carry an ordering stated in their own title,
and 28 are kgf's judgement -- so roughly a third of this graph is the
library's and two thirds are ours, which is the honest cost of ADR-5:

    traversal.md#6.3    the seven explicit precedence constraints and the
                        Enterprise order A -> A.5 -> A.6 -> A.6.1 -> IV.1 ->
                        IV.2 -> B -> C -> D -> H -> F -> E -> G
    phases.json#title   an ordering stated inside a phase's own title, e.g.
                        Ops.1 "immediately after Phase G"
    authored: kgf       kgf's judgement, with a rationale on the node

`phase:F` does not exist. traversal.md#6.3 constrains `phase:F`, but
phases.json has `F.1`-`F.6` and no bare `F`, so the seed chain would fail
12 of its 13 links taken literally. LIBRARY_PHASE_ALIASES maps it to the six.

Two edges are deliberately NOT authored, because authoring them would make
this graph cyclic and the library says so itself:

    SC.1/SC.2/SC.3 do not close a loop back to the gate that rejected.
    traversal.md:312 is explicit -- "The DAG stays acyclic -- the loop is a
    RUNTIME loop in the adapter, not a D23->D22 graph edge." The re-run is
    recorded as `reruns_on_success`, which an executor acts on and the
    scheduler ignores.

    Ops.5 does not depend on, or feed, phase:6. Its title says it "routes
    postmortem action items ... back into the next Sprint Planning cycle
    (Phase 6), closing the pipeline loop" -- but that is the NEXT cycle. As an
    edge it would be a cycle through the whole pipeline.

Pruning splices, it does not drop. A Solo or Squad-no-AI run prunes A.6,
A.6.1 and H (traversal.md#6.5), and simply removing them from the node set was
measurably wrong: kgf.dag ignores an edge whose endpoint is absent, so phase:B
lost its A.6.1 dependency, phase:F.1 floated to level 0 -- scheduling the
security audit before implementation -- and phase:A.5 sat at level 11 with its
own dependents above it. `effective_edges` hands a pruned node's dependents its
dependencies instead, transitively, so losing a link shortens the chain rather
than breaking it. Verified: the Solo schedule is 27 levels against the full
30, with every precedence relation still holding.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from kgf.dag import CyclePolicy, levels
from kgf.errors import ProblemLog
from kgf.source import LibrarySource

PHASES_FILENAME = "phases.json"

LIBRARY_PHASE_ALIASES: dict[str, tuple[str, ...]] = {
    "phase:F": (
        "phase:F.1",
        "phase:F.2",
        "phase:F.3",
        "phase:F.4",
        "phase:F.5",
        "phase:F.6",
    ),
}
"""Library references that name a phase group rather than a phase id.

traversal.md#6.3 writes `phase:H  <  phase:F` and `phase:F  <  phase:E`, but
no `phase:F` record exists. Recorded as data so the seed chain is machine-
checkable instead of being silently reinterpreted.
"""

SEED_CHAIN: tuple[str, ...] = (
    "phase:A",
    "phase:A.5",
    "phase:A.6",
    "phase:A.6.1",
    "phase:IV.1",
    "phase:IV.2",
    "phase:B",
    "phase:C",
    "phase:D",
    "phase:H",
    "phase:F",
    "phase:E",
    "phase:G",
)
"""traversal.md#6.3's "Full Enterprise/AI-LLM order", verbatim.

Kept as written, `phase:F` included, so the alias table above is exercised by
the topology test rather than being a claim in a docstring.
"""

LIBRARY_PRECEDENCE: tuple[tuple[str, str], ...] = (
    ("phase:A.6", "phase:A.6.1"),
    ("phase:A.6.1", "phase:B"),
    ("phase:IV.1", "phase:IV.2"),
    ("phase:IV.2", "phase:B"),
    ("phase:D", "phase:H"),
    ("phase:H", "phase:F"),
    ("phase:F", "phase:E"),
)
"""The seven constraints traversal.md#6.3 states as MUST, as (before, after).

The topology must satisfy every one of these transitively. Asserted as a test
rather than trusted, because these are the only dependency facts the library
actually provides and an authoring slip here is invisible otherwise.
"""

PROVENANCE_TRAVERSAL = "traversal.md#6.3"
PROVENANCE_TITLE = "phases.json#title"
PROVENANCE_AUTHORED = "authored: kgf"


@dataclass(frozen=True)
class Phase:
    """One phase node: what it needs, what it yields, and why it sits there.

    `depends_on` is the scheduling edge set. `reruns_on_success` is not an
    edge -- it records a phase an executor re-runs at runtime, which is how
    self-correction recovers without making the graph cyclic.
    """

    id: str
    group: str
    depends_on: frozenset[str] = frozenset()
    consumes: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()
    is_gate: bool = False
    blocking: bool = False
    provenance: str = PROVENANCE_AUTHORED
    rationale: str = ""
    triggered_by: tuple[str, ...] = ()
    reruns_on_success: tuple[str, ...] = ()

    @property
    def is_entry(self) -> bool:
        """True when nothing must complete before this phase may run."""
        return not self.depends_on


def _phase(
    phase_id: str,
    group: str,
    depends_on: Iterable[str] = (),
    *,
    consumes: tuple[str, ...] = (),
    produces: tuple[str, ...] = (),
    is_gate: bool = False,
    blocking: bool = False,
    provenance: str = PROVENANCE_AUTHORED,
    rationale: str = "",
    triggered_by: tuple[str, ...] = (),
    reruns_on_success: tuple[str, ...] = (),
) -> Phase:
    """Build one Phase, keeping the authored table below readable."""
    return Phase(
        id=phase_id,
        group=group,
        depends_on=frozenset(depends_on),
        consumes=consumes,
        produces=produces,
        is_gate=is_gate,
        blocking=blocking,
        provenance=provenance,
        rationale=rationale,
        triggered_by=triggered_by,
        reruns_on_success=reruns_on_success,
    )


AUTHORED_PHASES: tuple[Phase, ...] = (
    _phase(
        "phase:execution-plan",
        "terminal",
        produces=("execution_plan",),
        provenance=PROVENANCE_TITLE,
        rationale=(
            "TERMINAL in the library means terminal of the DECISION TREE spine "
            "(... D20 -> phase:execution-plan), not last in execution. The "
            "assembled plan is the input every other phase needs, so here it is "
            "the single root and every group entry point depends on it."
        ),
    ),
    _phase(
        "phase:0",
        "pre-processing",
        ("phase:execution-plan",),
        consumes=("execution_plan",),
        produces=("prd", "brd"),
        rationale="Requirements gathering is the front end; nothing precedes it but the plan.",
    ),
    _phase(
        "phase:1",
        "pre-processing",
        ("phase:0",),
        consumes=("prd", "brd"),
        produces=("hld", "adr"),
        rationale="Architecture is designed against stated requirements, not before them.",
    ),
    _phase(
        "phase:1.5",
        "pre-processing",
        ("phase:1",),
        consumes=("hld",),
        produces=("openapi",),
        rationale="An API contract expresses component boundaries the HLD has already drawn.",
    ),
    _phase(
        "phase:2",
        "pre-processing",
        ("phase:1", "phase:1.5"),
        consumes=("hld", "adr", "openapi"),
        produces=("blueprint_verdict",),
        is_gate=True,
        rationale=(
            "Joint validation is joint: it needs both artefacts it validates. "
            "Gate because a rejected blueprint must not reach UI or sprint planning."
        ),
    ),
    _phase(
        "phase:3",
        "pre-processing",
        ("phase:1.5",),
        consumes=("openapi",),
        produces=("ui_spec", "design_system"),
        rationale=(
            "UI/UX depends on the contract rather than the HLD because the shape of "
            "the payloads is what constrains the screens."
        ),
    ),
    _phase(
        "phase:4",
        "pre-processing",
        ("phase:2", "phase:3"),
        consumes=("blueprint_verdict", "ui_spec", "openapi"),
        produces=("reconciled_blueprint",),
        rationale="Reconciliation is where the validated backend blueprint meets the UI spec.",
    ),
    _phase(
        "phase:5",
        "pre-processing",
        ("phase:4",),
        consumes=("reconciled_blueprint",),
        produces=("srs", "uml"),
        rationale="Documentation describes the reconciled blueprint, so it cannot precede it.",
    ),
    _phase(
        "phase:6",
        "pre-processing",
        ("phase:5",),
        consumes=("srs",),
        produces=("sprint_plan",),
        rationale=(
            "Sprint planning sizes documented requirements. Ops.5 feeds the NEXT "
            "cycle's instance of this phase, which is why that is not an edge."
        ),
    ),
    _phase(
        "phase:7",
        "pre-processing",
        ("phase:6",),
        consumes=("sprint_plan",),
        produces=("agent_task_routing",),
        is_gate=True,
        rationale=(
            "Gate on the library's own evidence: traversal.md lists Phase 7 in D22's "
            "wraps_gates, so a REJECT here enters self-correction."
        ),
    ),
    _phase(
        "phase:8",
        "pre-processing",
        ("phase:7",),
        consumes=("agent_task_routing", "srs"),
        produces=("alignment_verdict",),
        is_gate=True,
        blocking=True,
        rationale=(
            "Gate on the library's own evidence: D22's alignment_bridge reads a "
            "phase:8 ir5_alignment_verdict.json for BLOCKED/drift."
        ),
    ),
    _phase(
        "phase:re-c.1",
        "reverse-engineering",
        ("phase:execution-plan",),
        consumes=("execution_plan",),
        produces=("structural_inventory",),
        rationale=(
            "An existing codebase is read before it is analysed; the inventory is the "
            "cheapest pass and every later RE phase narrows from it."
        ),
    ),
    _phase(
        "phase:re-0.1",
        "reverse-engineering",
        ("phase:re-c.1",),
        consumes=("structural_inventory",),
        produces=("ast_call_graph",),
        rationale="The call graph is built over the files the inventory found.",
    ),
    _phase(
        "phase:re-0.0",
        "reverse-engineering",
        ("phase:re-0.1",),
        consumes=("ast_call_graph",),
        produces=("dead_code_report",),
        rationale=(
            "Dead code is unreachability in the call graph, so it depends on the graph "
            "even though its id sorts first."
        ),
    ),
    _phase(
        "phase:re-0.2",
        "reverse-engineering",
        ("phase:re-0.1",),
        consumes=("ast_call_graph",),
        produces=("impact_analysis",),
        rationale="Impact analysis walks the call graph; it is independent of dead-code detection.",
    ),
    _phase(
        "phase:re-c.2",
        "reverse-engineering",
        ("phase:re-0.0", "phase:re-0.2"),
        consumes=("dead_code_report", "impact_analysis"),
        produces=("re_analysis",),
        rationale="The analysis narrative consumes both mechanical passes.",
    ),
    _phase(
        "phase:re-c.2.5",
        "reverse-engineering",
        ("phase:re-c.2",),
        consumes=("re_analysis", "ast_call_graph"),
        produces=("codebase_kg",),
        rationale="The unified codebase KG is assembled from the completed analysis.",
    ),
    _phase(
        "phase:re-c.3",
        "reverse-engineering",
        ("phase:re-c.2.5",),
        consumes=("codebase_kg",),
        produces=("as_built_doc",),
        rationale="As-built documentation is generated from the KG, not from raw files.",
    ),
    _phase(
        "phase:A",
        "main-pipeline",
        ("phase:8",),
        consumes=("alignment_verdict", "hld", "adr"),
        produces=("architecture",),
        rationale=(
            "The Enterprise order in traversal.md#6.3 starts at A and says nothing "
            "about the pre-processing front end, so this one edge is authored: when "
            "both are present, implementation architecture follows alignment. When "
            "phase:8 is pruned the edge is simply not followed."
        ),
    ),
    _phase(
        "phase:A.5",
        "main-pipeline",
        ("phase:A",),
        consumes=("architecture",),
        produces=("engineered_context",),
        provenance=PROVENANCE_TRAVERSAL,
        rationale="Second link of the Enterprise order.",
    ),
    _phase(
        "phase:A.6",
        "main-pipeline",
        ("phase:A.5",),
        consumes=("engineered_context",),
        produces=("harness_control_policy",),
        is_gate=True,
        blocking=True,
        provenance=PROVENANCE_TRAVERSAL,
        rationale=(
            "Third link of the Enterprise order. Its own title names it a BLOCKING "
            "gate before Phase B. Pruned by D13::B2 and D21::B2/B3 on Solo or "
            "Squad-no-AI runs."
        ),
    ),
    _phase(
        "phase:A.6.1",
        "main-pipeline",
        ("phase:A.6",),
        consumes=("harness_control_policy",),
        produces=("resource_elastic_policy",),
        provenance=PROVENANCE_TRAVERSAL,
        rationale="Library MUST: A.6 < A.6.1, the F2 policy builds on the A.6 budget policy.",
    ),
    _phase(
        "phase:IV.1",
        "invariant-revalidation",
        ("phase:A.6.1",),
        consumes=("resource_elastic_policy", "codebase_kg"),
        produces=("dirty_marks",),
        provenance=PROVENANCE_TRAVERSAL,
        rationale=(
            "Position taken from the Enterprise order. The real trigger is D23::B1 "
            "finding DIRTY marks, so on a clean run IV.1 and IV.2 are both pruned."
        ),
    ),
    _phase(
        "phase:IV.2",
        "invariant-revalidation",
        ("phase:IV.1",),
        consumes=("dirty_marks",),
        produces=("invariant_verdict",),
        is_gate=True,
        blocking=True,
        provenance=PROVENANCE_TRAVERSAL,
        rationale="Library MUST: IV.1 < IV.2, and its title says BLOCKING until all marks clear.",
    ),
    _phase(
        "phase:B",
        "main-pipeline",
        ("phase:A.6.1", "phase:IV.2"),
        consumes=("engineered_context", "resource_elastic_policy", "invariant_verdict"),
        produces=("implementation",),
        provenance=PROVENANCE_TRAVERSAL,
        rationale=(
            "Two library MUSTs converge here: A.6.1 < B (policy committed before any "
            "implementer runs) and IV.2 < B (DIRTY domains re-validated first)."
        ),
    ),
    _phase(
        "phase:C",
        "main-pipeline",
        ("phase:B",),
        consumes=("implementation",),
        produces=("faithfulness_verdict",),
        is_gate=True,
        blocking=True,
        provenance=PROVENANCE_TRAVERSAL,
        rationale="Enterprise order B -> C. A gate per D22's wraps_gates.",
    ),
    _phase(
        "phase:D",
        "main-pipeline",
        ("phase:C",),
        consumes=("implementation", "faithfulness_verdict"),
        produces=("qa_verdict",),
        is_gate=True,
        blocking=True,
        provenance=PROVENANCE_TRAVERSAL,
        rationale="Enterprise order C -> D; #6.3 calls it the QA gate that must be APPROVED.",
    ),
    _phase(
        "phase:H",
        "main-pipeline",
        ("phase:D",),
        consumes=("qa_verdict", "implementation"),
        produces=("regression_verdict",),
        is_gate=True,
        blocking=True,
        provenance=PROVENANCE_TRAVERSAL,
        rationale=(
            "Library MUST: D < H, QA APPROVED before the regression harness runs. "
            "BINARY gate by its own title. Pruned alongside A.6/A.6.1."
        ),
    ),
    _phase(
        "phase:F.1",
        "security",
        ("phase:H",),
        consumes=("regression_verdict", "architecture"),
        produces=("threat_model",),
        provenance=PROVENANCE_TRAVERSAL,
        rationale="Library MUST: H < F, expanded through LIBRARY_PHASE_ALIASES since phase:F has no record.",
    ),
    _phase(
        "phase:F.2",
        "security",
        ("phase:H",),
        consumes=("regression_verdict", "implementation"),
        produces=("sast_report", "sca_report"),
        provenance=PROVENANCE_TRAVERSAL,
        rationale="Library MUST: H < F. Static analysis is independent of threat modelling, so both start together.",
    ),
    _phase(
        "phase:F.3",
        "security",
        ("phase:F.1",),
        consumes=("threat_model",),
        produces=("dast_report",),
        rationale="Dynamic and API testing is steered by the threat model, so it follows F.1 rather than H.",
    ),
    _phase(
        "phase:F.4",
        "security",
        ("phase:F.1",),
        consumes=("threat_model",),
        produces=("infra_crypto_report",),
        rationale="Infrastructure and crypto review is likewise scoped by the threat model.",
    ),
    _phase(
        "phase:F.5",
        "security",
        ("phase:F.2", "phase:F.3", "phase:F.4"),
        consumes=("sast_report", "sca_report", "dast_report", "infra_crypto_report"),
        produces=("compliance_mapping",),
        rationale="Compliance mapping cites findings, so every finding-producing audit precedes it.",
    ),
    _phase(
        "phase:F.6",
        "security",
        ("phase:F.5",),
        consumes=("compliance_mapping",),
        produces=("security_verdict",),
        is_gate=True,
        blocking=True,
        provenance=PROVENANCE_TITLE,
        rationale="Its title is 'Verdict Gate (BINARY)': one verdict over the five audits above it.",
    ),
    _phase(
        "phase:E",
        "main-pipeline",
        ("phase:F.6",),
        consumes=("security_verdict", "qa_verdict"),
        produces=("reliability_verdict",),
        is_gate=True,
        blocking=True,
        provenance=PROVENANCE_TRAVERSAL,
        rationale="Library MUST: F < E, security clean before the RS computation.",
    ),
    _phase(
        "phase:G",
        "main-pipeline",
        ("phase:E",),
        consumes=("reliability_verdict", "implementation"),
        produces=("integrated_release",),
        provenance=PROVENANCE_TRAVERSAL,
        rationale="Last link of the Enterprise order.",
    ),
    _phase(
        "phase:Ops.1",
        "production-operations",
        ("phase:G",),
        consumes=("integrated_release",),
        produces=("prr_verdict",),
        is_gate=True,
        blocking=True,
        provenance=PROVENANCE_TITLE,
        rationale="Its title says 'immediately after Phase G' and 'BLOCKING go/no-go'.",
    ),
    _phase(
        "phase:Ops.2",
        "production-operations",
        ("phase:Ops.1",),
        consumes=("prr_verdict",),
        produces=("slo_policy", "dashboards", "burn_rate_alerts"),
        rationale="Observability is activated only for a release the PRR gate passed.",
    ),
    _phase(
        "phase:Ops.3",
        "production-operations",
        ("phase:Ops.1",),
        consumes=("prr_verdict",),
        produces=("dr_confirmation",),
        rationale="DR confirmation is independent of SLO activation, so it runs beside Ops.2, not after it.",
    ),
    _phase(
        "phase:Ops.4",
        "production-operations",
        ("phase:Ops.2", "phase:Ops.3"),
        consumes=("slo_policy", "burn_rate_alerts", "dr_confirmation"),
        produces=("bake_result",),
        is_gate=True,
        rationale=(
            "Hypercare is elevated monitoring, so the monitoring must exist first. Gate "
            "because its title holds until the Crow-AMSAA stabilization test passes."
        ),
    ),
    _phase(
        "phase:Ops.5",
        "production-operations",
        ("phase:Ops.4",),
        consumes=("bake_result",),
        produces=("readiness_debt", "postmortem_actions"),
        rationale=(
            "Feedback closure needs the bake window's findings. It feeds the NEXT "
            "cycle's phase:6 and that is deliberately not an edge: as an edge it would "
            "make the whole pipeline one cycle."
        ),
    ),
    _phase(
        "phase:SC.1",
        "self-correction",
        ("phase:execution-plan",),
        produces=("correction_adr", "root_cause"),
        triggered_by=(
            "phase:7",
            "phase:8",
            "phase:C",
            "phase:E",
            "phase:F.6",
            "phase:IV.2",
        ),
        rationale=(
            "Recovery, not a pipeline step: it is scheduled when one of the gates in "
            "triggered_by REJECTs, so it must not depend on those gates or it could "
            "not run until all of them had passed."
        ),
    ),
    _phase(
        "phase:SC.2",
        "self-correction",
        ("phase:SC.1",),
        consumes=("root_cause", "correction_adr"),
        produces=("repaired_prompt", "repaired_context"),
        reruns_on_success=("<the gate that rejected>",),
        rationale=(
            "Repair follows diagnosis. The re-run of the failed gate is a RUNTIME "
            "action bounded to 3 iterations by ADR-9, recorded in reruns_on_success "
            "rather than as an edge -- traversal.md:312 states the loop lives in the "
            "adapter and the DAG stays acyclic."
        ),
    ),
    _phase(
        "phase:SC.3",
        "self-correction",
        ("phase:SC.2",),
        consumes=("root_cause",),
        produces=("human_escalation",),
        rationale="Terminal escalation after the ADR-9 bound of 3 iterations is exhausted.",
    ),
)


@dataclass(frozen=True)
class Topology:
    """kgf's authored phase graph, queryable and schedulable."""

    phases: dict[str, Phase]

    @property
    def ids(self) -> tuple[str, ...]:
        """Every authored phase id, in authoring order."""
        return tuple(self.phases)

    def edges(self) -> dict[str, frozenset[str]]:
        """id -> the ids it depends on, in the shape kgf.dag consumes."""
        return {phase_id: phase.depends_on for phase_id, phase in self.phases.items()}

    def get(self, phase_id: str) -> Phase:
        """One phase by id.

        Raises:
            KeyError: if the id is not authored. Unlike the library registries,
                this table is kgf's own, so an unknown id is a bug here rather
                than ragged upstream data.
        """
        return self.phases[phase_id]

    def resolve(self, reference: str) -> tuple[str, ...]:
        """Expand a library phase reference into real phase ids.

        `phase:F` appears in traversal.md#6.3 and has no record in
        phases.json, so it expands to F.1-F.6. Anything else resolves to
        itself when authored, and to an empty tuple when it is not.
        """
        if reference in LIBRARY_PHASE_ALIASES:
            return tuple(p for p in LIBRARY_PHASE_ALIASES[reference] if p in self.phases)
        return (reference,) if reference in self.phases else ()

    def select(self, pruned: Iterable[str] = ()) -> tuple[str, ...]:
        """Every phase except the pruned ones, in authoring order.

        Pruning is how a Solo or Squad-no-AI run drops A.6, A.6.1 and H
        (traversal.md#6.5).
        """
        removed = set(pruned)
        return tuple(phase_id for phase_id in self.phases if phase_id not in removed)

    def effective_edges(self, pruned: Iterable[str] = ()) -> dict[str, frozenset[str]]:
        """Dependencies with pruned phases spliced out, not merely dropped.

        Dropping a pruned node and letting kgf.dag ignore the dangling edge is
        wrong, and measurably so: pruning A.6, A.6.1 and H for a Solo run left
        phase:B depending on nothing but IV.2 and floated phase:F.1 to level 0,
        scheduling the security audit before implementation while phase:A.5 sat
        at level 11. A prune must hand a pruned node's dependents its own
        dependencies, transitively, so the chain survives losing a link.
        """
        removed = set(pruned)

        def surviving(start: str) -> set[str]:
            found: set[str] = set()
            seen: set[str] = {start}
            frontier = [start]
            while frontier:
                current = frontier.pop()
                if current not in removed:
                    found.add(current)
                    continue
                for dependency in self.phases[current].depends_on:
                    if dependency not in seen:
                        seen.add(dependency)
                        frontier.append(dependency)
            return found

        rewired: dict[str, frozenset[str]] = {}
        for phase_id, phase in self.phases.items():
            if phase_id in removed:
                continue
            inherited: set[str] = set()
            for dependency in phase.depends_on:
                inherited |= surviving(dependency)
            rewired[phase_id] = frozenset(inherited - {phase_id})
        return rewired

    def levels(self, pruned: Iterable[str] = ()) -> list[list[str]]:
        """Execution levels over the selected phases.

        Uses CyclePolicy.FATAL: a cycle here is an authoring mistake in this
        module, and collapsing it the way parallel_generate does would hide
        exactly what the topology test exists to catch.
        """
        selected = self.select(pruned)
        return levels(selected, self.effective_edges(pruned), cycle_policy=CyclePolicy.FATAL)

    def precedes(self, before: str, after: str) -> bool:
        """True when `before` is a transitive dependency of `after`.

        Used to assert the library's seven MUST constraints hold, which is the
        only external check available on an otherwise self-authored graph.
        """
        seen: set[str] = set()
        frontier = [after]
        while frontier:
            current = frontier.pop()
            for dependency in self.phases.get(current, Phase(id=current, group="")).depends_on:
                if dependency == before:
                    return True
                if dependency not in seen:
                    seen.add(dependency)
                    frontier.append(dependency)
        return False

    def entry_points(self) -> tuple[str, ...]:
        """Phases with no dependency at all."""
        return tuple(phase_id for phase_id, phase in self.phases.items() if phase.is_entry)

    def gates(self) -> tuple[str, ...]:
        """Every phase marked as a gate."""
        return tuple(phase_id for phase_id, phase in self.phases.items() if phase.is_gate)

    def unknown_dependencies(self) -> dict[str, tuple[str, ...]]:
        """Any depends_on entry that is not itself an authored phase.

        Always empty in a correct table; checked because a typo in a frozenset
        of strings is otherwise silent -- kgf.dag ignores edges leaving the
        node set, which is right for pruning and wrong for a typo.
        """
        missing: dict[str, tuple[str, ...]] = {}
        for phase_id, phase in self.phases.items():
            absent = tuple(sorted(d for d in phase.depends_on if d not in self.phases))
            if absent:
                missing[phase_id] = absent
        return missing


def load_topology() -> Topology:
    """kgf's authored topology. Reads nothing; the data is this module."""
    return Topology(phases={phase.id: phase for phase in AUTHORED_PHASES})


def library_phase_ids(source: LibrarySource) -> tuple[str, ...]:
    """Every phase id the library declares, in file order."""
    records: Any = source.read_json(source.tree_dir / PHASES_FILENAME)
    entries = records if isinstance(records, list) else records.get("phases", [])
    return tuple(str(record["id"]) for record in entries if "id" in record)


@dataclass
class TopologyReport:
    """The result of checking the authored topology against a real library."""

    library_version: str
    authored_count: int
    library_count: int
    missing_from_library: tuple[str, ...] = ()
    missing_from_topology: tuple[str, ...] = ()
    unknown_dependencies: dict[str, tuple[str, ...]] = field(default_factory=dict)
    level_count: int = 0

    @property
    def ok(self) -> bool:
        """True when the topology and the library agree on the phase set."""
        return not (
            self.missing_from_library or self.missing_from_topology or self.unknown_dependencies
        )


def check_against_library(
    topology: Topology, source: LibrarySource, log: ProblemLog | None = None
) -> TopologyReport:
    """Verify every authored phase still exists, and vice versa.

    Both directions matter and for different reasons. An authored id the
    library dropped means kgf schedules a phase that no longer exists. A
    library id kgf never authored means a new phase is being silently ignored
    -- which is the failure mode ADR-5 accepted when it made kgf the owner of
    a graph the library does not model.
    """
    declared = library_phase_ids(source)
    declared_set = set(declared)
    authored_set = set(topology.phases)

    report = TopologyReport(
        library_version=source.library_version,
        authored_count=len(authored_set),
        library_count=len(declared_set),
        missing_from_library=tuple(sorted(authored_set - declared_set)),
        missing_from_topology=tuple(sorted(declared_set - authored_set)),
        unknown_dependencies=topology.unknown_dependencies(),
        level_count=len(topology.levels()),
    )

    if log is not None:
        for phase_id in report.missing_from_library:
            log.defect(
                "TOPOLOGY_PHASE_GONE",
                f"authored phase {phase_id} is absent from {PHASES_FILENAME}",
                source=phase_id,
            )
        for phase_id in report.missing_from_topology:
            log.defect(
                "TOPOLOGY_PHASE_UNAUTHORED",
                f"library declares {phase_id}, which kgf's topology does not author",
                source=phase_id,
            )
        for phase_id, absent in report.unknown_dependencies.items():
            log.fatal(
                "TOPOLOGY_UNKNOWN_DEPENDENCY",
                f"{phase_id} depends on unauthored {', '.join(absent)}",
                source=phase_id,
            )

    return report


def unsatisfied_library_precedence(topology: Topology) -> tuple[tuple[str, str], ...]:
    """Which of traversal.md#6.3's seven MUSTs the topology fails to satisfy.

    A constraint naming `phase:F` is satisfied when EVERY phase it expands to
    sits on the correct side, so a group reference cannot be half-honoured.
    """
    failures: list[tuple[str, str]] = []
    for before, after in LIBRARY_PRECEDENCE:
        befores = topology.resolve(before)
        afters = topology.resolve(after)
        if not befores or not afters:
            failures.append((before, after))
            continue
        if not all(topology.precedes(b, a) for b in befores for a in afters):
            failures.append((before, after))
    return tuple(failures)


def seed_chain_links(topology: Topology) -> tuple[tuple[str, str], ...]:
    """traversal.md#6.3's Enterprise order as consecutive (before, after) pairs.

    Expanded through the alias table, so `... H -> F -> E ...` becomes the
    twelve real links it stands for rather than failing on a phase id that
    does not exist.
    """
    links: list[tuple[str, str]] = []
    for before, after in zip(SEED_CHAIN, SEED_CHAIN[1:]):
        for b in topology.resolve(before):
            for a in topology.resolve(after):
                links.append((b, a))
    return tuple(links)


def unsatisfied_seed_chain(topology: Topology) -> tuple[tuple[str, str], ...]:
    """Which links of the seeded Enterprise order the topology does not honour."""
    return tuple(
        (before, after)
        for before, after in seed_chain_links(topology)
        if not topology.precedes(before, after)
    )


def describe(topology: Topology, pruned: Sequence[str] = ()) -> str:
    """Human-readable level listing, for `kgf topology`."""
    lines: list[str] = []
    for index, level in enumerate(topology.levels(pruned)):
        lines.append(f"level {index}:")
        for phase_id in level:
            phase = topology.get(phase_id)
            marks = []
            if phase.is_gate:
                marks.append("BLOCKING gate" if phase.blocking else "gate")
            if phase.triggered_by:
                marks.append("on-reject")
            suffix = f"  [{', '.join(marks)}]" if marks else ""
            lines.append(f"  {phase_id:<24} {phase.group:<22} {phase.provenance}{suffix}")
    return "\n".join(lines)
