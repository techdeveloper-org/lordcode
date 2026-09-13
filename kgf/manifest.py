"""ADR-7's run manifest: what a selection decided, and whether it still holds.

A manifest records `library_version`, the agent selected with its score and
edge path, the closure, and the assembled context's included and dropped
sections with token counts. `kgf replay` re-derives all of it from the library
as it stands now and reports what changed.

Drift detection is the whole point. A manifest that only round-trips proves
nothing -- the interesting question is never "can this file be read back" but
"would this run still produce this result", and the honest answers are all
negative ones: the library moved, the ranker changed its mind, the context got
smaller. So replay reports differences and exits non-zero, rather than
succeeding quietly and leaving a caller to diff by eye.

Three shipped decisions depend on this existing, which is why it is worth more
than its size:

    ADR-7 promises replay with no model call. Selection and context assembly
    make none, so that is free -- but it was unverifiable while nothing could
    be replayed.

    lexicon.py:196 justifies its deterministic tie-break with "replay depends
    on this being stable". That is now a claim a test can exercise end to end.

    M11's third embedding trigger is stated in the plan as unmeasurable without
    a `disambiguation_considered` field here. SelectionResult already carried
    it; it simply had nowhere to be recorded.

The context TEXT is not stored, only its sha256. A manifest is a record of a
decision, not a cache of its output: keeping 2000 tokens of prose per run would
make manifests large enough that nobody keeps them, and the hash answers the
only question asked of the text -- is it the same one.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kgf.closure import Closure, build_closure
from kgf.context import AssembledContext, Intent, assemble_context
from kgf.loader import load_graph
from kgf.select import SelectionResult, Selector
from kgf.source import LibrarySource, locate_library

MANIFEST_VERSION = "1"
"""Schema version of the manifest itself.

Separate from library_version because they move for unrelated reasons: this
changes when kgf changes what it records, that changes when the library is
rebuilt. Conflating them is the mistake kg_version already demonstrates.
"""

CONFIDENCE_TOLERANCE = 1e-6
"""Float comparison slack for a recorded confidence.

Small on purpose. Scoring is deterministic given the same corpus, so any real
difference here means the ranker or the corpus changed -- which is exactly the
drift worth reporting, not noise to absorb.
"""


@dataclass(frozen=True)
class Manifest:
    """One recorded run: the inputs, the decision, and the evidence for it."""

    manifest_version: str
    created_at: str
    library_version: str
    library_root: str
    registry_digests: tuple[tuple[str, str], ...]

    task: str
    intent: str
    budget_tokens: int
    forced_agent: bool = False
    forced_skill: str = ""

    outcome: str = ""
    agent: str = ""
    domain: str = ""
    confidence: float = 0.0
    lexical_score: float = 0.0
    edge_path: tuple[str, ...] = ()
    considered: int = 0
    query_terms: tuple[str, ...] = ()
    disambiguation_considered: tuple[str, ...] = ()
    runner_up: str = ""

    mandatory_skills: tuple[str, ...] = ()
    required_skills: tuple[str, ...] = ()
    optional_skills: tuple[str, ...] = ()
    math_agents: tuple[str, ...] = ()
    coordinating_agents: tuple[str, ...] = ()
    regulations: tuple[str, ...] = ()
    truncated: tuple[str, ...] = ()
    depth_reached: int = 0

    context_tokens: int = 0
    included: tuple[str, ...] = ()
    dropped: tuple[str, ...] = ()
    context_defects: tuple[str, ...] = ()
    context_sha256: str = ""

    def to_json(self) -> str:
        """Serialise as indented JSON, keys in declaration order."""
        return json.dumps(asdict(self), indent=2, ensure_ascii=False)

    def write(self, path: Path) -> Path:
        """Write this manifest to disk as utf-8, creating parent directories."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")
        return path


@dataclass
class ReplayReport:
    """The result of replaying one manifest against the current library."""

    manifest_version: str = ""
    recorded_library_version: str = ""
    current_library_version: str = ""
    differences: list[str] = field(default_factory=list)

    @property
    def matches(self) -> bool:
        """True when nothing about the decision changed."""
        return not self.differences

    def summary(self) -> str:
        """One line per difference, or a single line saying there are none."""
        if self.matches:
            return f"replay matches: library_version {self.current_library_version}, no differences"
        lines = [f"{len(self.differences)} difference(s) since this manifest was written:"]
        lines.extend(f"  {difference}" for difference in self.differences)
        return "\n".join(lines)


def _section_labels(sections: Any) -> tuple[str, ...]:
    """Render included/dropped sections as `entity :: heading` strings.

    Strings rather than nested objects because the manifest is compared field
    by field, and a flat label makes the difference report readable: "dropped
    section X that was previously included" beats two JSON blobs.
    """
    labels = []
    for section in sections:
        entity = getattr(section, "entity", "") or ""
        heading = getattr(section, "heading", "") or ""
        labels.append(f"{entity} :: {heading}" if entity else str(heading))
    return tuple(labels)


def build(
    task: str,
    source: LibrarySource,
    selection: SelectionResult | None = None,
    closure: Closure | None = None,
    assembled: AssembledContext | None = None,
    *,
    intent: str = Intent.IMPLEMENT.value,
    budget_tokens: int = 0,
    forced_agent: bool = False,
    forced_skill: str = "",
) -> Manifest:
    """Assemble a manifest from whatever stage of a run has completed.

    Every part after `task` is optional so `kgf route` can write a
    selection-only manifest and `kgf context` a full one, rather than forcing
    the cheap command to do the expensive work just to record it.
    """
    library_version, digests = source.fingerprint()
    best = selection.best if selection is not None else None

    return Manifest(
        manifest_version=MANIFEST_VERSION,
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        library_version=library_version,
        library_root=str(source.root),
        registry_digests=digests,
        task=task,
        intent=intent,
        budget_tokens=budget_tokens,
        forced_agent=forced_agent,
        forced_skill=forced_skill,
        outcome=selection.outcome.value if selection is not None else "",
        agent=best.agent if best is not None else (closure.agent if closure is not None else ""),
        domain=best.domain if best is not None else (closure.domain if closure is not None else ""),
        confidence=best.confidence if best is not None else 0.0,
        lexical_score=best.lexical_score if best is not None else 0.0,
        edge_path=tuple(best.edge_path) if best is not None else (),
        considered=selection.considered if selection is not None else 0,
        query_terms=tuple(selection.query_terms) if selection is not None else (),
        disambiguation_considered=(
            tuple(selection.disambiguation_considered) if selection is not None else ()
        ),
        runner_up=(
            selection.matches[1].agent if selection is not None and len(selection.matches) > 1 else ""
        ),
        mandatory_skills=tuple(closure.mandatory_skills) if closure is not None else (),
        required_skills=tuple(closure.required_skills) if closure is not None else (),
        optional_skills=tuple(closure.optional_skills) if closure is not None else (),
        math_agents=tuple(closure.math_agents) if closure is not None else (),
        coordinating_agents=tuple(closure.coordinating_agents) if closure is not None else (),
        regulations=tuple(closure.regulations) if closure is not None else (),
        truncated=tuple(closure.truncated) if closure is not None else (),
        depth_reached=closure.depth_reached if closure is not None else 0,
        context_tokens=assembled.assembled_context_tokens if assembled is not None else 0,
        included=_section_labels(assembled.included) if assembled is not None else (),
        dropped=_section_labels(assembled.dropped) if assembled is not None else (),
        context_defects=tuple(assembled.defects) if assembled is not None else (),
        context_sha256=(
            hashlib.sha256(assembled.text.encode("utf-8")).hexdigest() if assembled is not None else ""
        ),
    )


def load(path: Path) -> Manifest:
    """Read a manifest from disk.

    Unknown keys are dropped and absent ones take their defaults, so a manifest
    written by an older kgf still replays. The recorded `manifest_version` is
    reported in the replay rather than enforced: refusing to read an older
    manifest would destroy the only record of what a past run decided, which is
    the opposite of what this file is for.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path} holds {type(raw).__name__}, not a manifest object")

    fields = {f for f in Manifest.__dataclass_fields__}
    known = {key: value for key, value in raw.items() if key in fields}

    required = {
        name
        for name, spec in Manifest.__dataclass_fields__.items()
        if spec.default is dataclasses.MISSING and spec.default_factory is dataclasses.MISSING
    }
    absent = sorted(required - known.keys())
    if absent:
        # Named explicitly rather than letting the dataclass raise: a TypeError
        # about missing positional arguments describes this module's internals,
        # not the file the caller is actually holding.
        raise ValueError(f"{path} is missing manifest field(s): {', '.join(absent)}")

    for key in ("registry_digests",):
        if key in known:
            known[key] = tuple(tuple(item) for item in known[key])
    for key in (
        "edge_path", "query_terms", "disambiguation_considered", "mandatory_skills",
        "required_skills", "optional_skills", "math_agents", "coordinating_agents",
        "regulations", "truncated", "included", "dropped", "context_defects",
    ):
        if key in known:
            known[key] = tuple(known[key])
    return Manifest(**known)


def _compare(report: ReplayReport, label: str, recorded: Any, current: Any) -> None:
    """Record a difference when a re-derived value does not match the record."""
    if isinstance(recorded, float) and isinstance(current, float):
        if abs(recorded - current) <= CONFIDENCE_TOLERANCE:
            return
    if recorded == current:
        return
    if isinstance(recorded, tuple) and isinstance(current, tuple):
        added = [item for item in current if item not in recorded]
        removed = [item for item in recorded if item not in current]
        detail = []
        if removed:
            detail.append(f"-{len(removed)} ({', '.join(str(x) for x in removed[:3])})")
        if added:
            detail.append(f"+{len(added)} ({', '.join(str(x) for x in added[:3])})")
        report.differences.append(f"{label}: {' '.join(detail) or 'reordered'}")
        return
    report.differences.append(f"{label}: recorded {recorded!r}, now {current!r}")


def replay(manifest: Manifest, library: Path | None = None) -> ReplayReport:
    """Re-derive a manifest's decision from the current library and diff it.

    Makes no model call, which is what makes this cheap enough to run in CI:
    selection ranks lexically and context assembly reads markdown, so the whole
    replay is disk and arithmetic.

    A forced-agent manifest skips ranking on replay too -- re-ranking it would
    compare a decision that was never made.
    """
    source = locate_library(library)
    graph, _log = load_graph(library)

    report = ReplayReport(
        manifest_version=manifest.manifest_version,
        recorded_library_version=manifest.library_version,
        current_library_version=source.library_version,
    )

    current_version, current_digests = source.fingerprint()
    _compare(report, "library_version", manifest.library_version, current_version)
    if manifest.registry_digests and tuple(manifest.registry_digests) != current_digests:
        changed = [
            name
            for (name, digest), (_current_name, current_digest) in zip(
                manifest.registry_digests, current_digests
            )
            if digest != current_digest
        ]
        report.differences.append(
            f"registry content changed: {', '.join(changed) or 'file set differs'}"
        )

    agent_ref = manifest.agent
    if not manifest.forced_agent and manifest.task:
        selection = Selector(graph, source).select(manifest.task)
        best = selection.best
        _compare(report, "outcome", manifest.outcome, selection.outcome.value)
        _compare(report, "agent", manifest.agent, best.agent if best is not None else "")
        _compare(report, "domain", manifest.domain, best.domain if best is not None else "")
        _compare(report, "confidence", manifest.confidence, best.confidence if best is not None else 0.0)
        _compare(report, "considered", manifest.considered, selection.considered)
        _compare(
            report,
            "disambiguation_considered",
            manifest.disambiguation_considered,
            tuple(selection.disambiguation_considered),
        )
        agent_ref = best.agent if best is not None else ""

    if not agent_ref:
        return report

    closure = build_closure(graph, agent_ref)
    if closure is None:
        report.differences.append(f"closure: agent {agent_ref} no longer resolves")
        return report

    if manifest.mandatory_skills or manifest.required_skills:
        _compare(report, "mandatory_skills", manifest.mandatory_skills, tuple(closure.mandatory_skills))
        _compare(report, "required_skills", manifest.required_skills, tuple(closure.required_skills))
        _compare(report, "regulations", manifest.regulations, tuple(closure.regulations))

    if manifest.context_sha256:
        assembled = assemble_context(
            graph,
            source,
            closure,
            intent=Intent(manifest.intent) if manifest.intent else Intent.IMPLEMENT,
            budget_tokens=manifest.budget_tokens,
        )
        _compare(report, "context_tokens", manifest.context_tokens, assembled.assembled_context_tokens)
        _compare(report, "included", manifest.included, _section_labels(assembled.included))
        _compare(
            report,
            "context_sha256",
            manifest.context_sha256,
            hashlib.sha256(assembled.text.encode("utf-8")).hexdigest(),
        )

    return report
