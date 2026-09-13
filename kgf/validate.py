"""Validate a loaded graph, and validate the markdown the graph does not cover.

Two halves, and the second is the one that is easy to leave out:

  The JSON half checks adjacency integrity, the schema's structural
  constraints, and that dangling endpoints stay inside two known allowlists.

  The MARKDOWN half exists because every malformed skill file is perfectly
  VALID in skills_all.json. The registries are generated, so a file whose
  frontmatter will not parse still contributes a complete record. A JSON-only
  validator therefore reports a clean library while 18 documents cannot be
  read at all -- which is exactly how they went unnoticed. Their contents are
  what a prompt would carry, so they have to be checked at source.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from kgf import ids
from kgf.errors import ProblemLog, Severity
from kgf.graph import KnowledgeGraph
from kgf.source import LibrarySource

KNOWN_DANGLING_REGULATIONS = frozenset(
    {
        "reg:navic_gagan_std",
        "reg:ngp_2022",
        "reg:rsdp_2011",
        "reg:soi_act_1958",
        "reg:svamitva_uas_2021",
    }
)
"""REGULATED_BY sources naming regulations that do not exist.

These 5 ids across 9 edge occurrences are the library's OWN known defects: its
qa_report.json records each as a W-013 warning. Allowlisted because the
library already tracks them, not because they are acceptable.
"""

KNOWN_DANGLING_SKILLS = frozenset(
    {
        "skill:analysts_notebook",
        "skill:bitcoin_blockchain",
        "skill:censys",
        "skill:hunter_io",
        "skill:i2p_network",
        "skill:maltego",
        "skill:monero_blockchain",
        "skill:natgrid",
        "skill:onion_browser",
        "skill:palantir",
        "skill:recon_ng",
        "skill:shodan",
        "skill:sigint_framework",
        "skill:spiderfoot",
        "skill:theharvester",
        "skill:tor_network",
    }
)
"""SKILL_SIMILAR_TO targets naming skills that do not exist.

Unlike the regulations above, the library's qa_report.json does NOT flag any
of these 16 -- this is kgf's own finding, allowlisted so drift is still
detected while the library is told about them. All 16 are OSINT and
surveillance tooling that no skill document defines.
"""

MAX_DANGLING_OCCURRENCES = 25
"""Ceiling on dangling endpoint occurrences at the pinned library_version.

Bounded rather than exact: an equality assertion against a moving library
fails on arithmetic instead of on a real regression. 21 distinct ids account
for these 25 occurrences, and both allowlists together cover all 21.
"""

MAX_DUPLICATE_TRIPLES = 1051
"""Ceiling on excess duplicate (source, target, type) rows.

1039 distinct triples occur more than once, 2090 times in total. The cause is
documented: per-domain edge ids were carried into the master registry without
namespacing, so `E001` alone appears 64 times.
"""

FRONTMATTER_PATTERN = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)


@dataclass
class MarkdownReport:
    """Outcome of parsing every SKILL.md and agent.md at source."""

    parsed: int = 0
    failed: dict[str, str] = field(default_factory=dict)
    bom_stripped: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        """Documents examined."""
        return self.parsed + len(self.failed)

    def by_fault(self) -> dict[str, int]:
        """How many documents failed for each fault class."""
        counts: dict[str, int] = {}
        for fault in self.failed.values():
            counts[fault] = counts.get(fault, 0) + 1
        return counts


def classify_yaml_fault(error: Exception) -> str:
    """Name the fault class of a frontmatter parse failure.

    The classes are distinguished because their REPAIRS differ, and conflating
    them produces a fix that does nothing: a document with an opening quote and
    no closing one needs the terminator added, not its (non-existent) interior
    quotes escaped.
    """
    message = str(error).split("\n")[0].lower()
    if "end of stream" in message or "unexpected end" in message:
        return "unterminated-quote"
    if "mapping values are not allowed" in message:
        return "unquoted-scalar"
    if "block mapping" in message or "expected <block end>" in message:
        return "unescaped-interior-quote"
    if "quoted scalar" in message:
        return "unterminated-quote"
    return "other-yaml-fault"


def validate_markdown(source: LibrarySource) -> MarkdownReport:
    """Parse every skill and agent document, classifying each failure.

    Reading through LibrarySource means utf-8-sig, so the 13 BOM'd files parse
    here and are reported as bom_stripped rather than as failures. They are
    still worth naming: any consumer reading plain utf-8 still drops them.
    """
    report = MarkdownReport()
    documents = [(path, "SKILL.md") for path in sorted(source.skills_dir.glob("*/SKILL.md"))]
    documents += [(path, "agent.md") for path in sorted(source.agents_dir.glob("*/agent.md"))]

    for path, _kind in documents:
        label = path.parent.name
        try:
            raw_bytes = path.read_bytes()
        except OSError as exc:
            report.failed[label] = f"unreadable: {exc}"
            continue

        if raw_bytes.startswith(b"\xef\xbb\xbf"):
            report.bom_stripped.append(label)

        text = source.read_markdown(path)
        match = FRONTMATTER_PATTERN.match(text)
        if match is None:
            report.failed[label] = "no-frontmatter-block"
            continue
        try:
            parsed = yaml.safe_load(match.group(1))
        except yaml.YAMLError as exc:
            report.failed[label] = classify_yaml_fault(exc)
            continue
        if not isinstance(parsed, dict):
            report.failed[label] = "frontmatter-not-a-mapping"
            continue
        report.parsed += 1

    return report


def validate_graph(graph: KnowledgeGraph, log: ProblemLog) -> ProblemLog:
    """Check graph-level invariants, adding problems to the existing log.

    Args:
        graph: The loaded graph.
        log: The load's problem log, appended to in place.

    Returns:
        The same log, for chaining.
    """
    _check_dangling_allowlists(graph, log)
    _check_no_self_loops(graph, log)
    _check_id_patterns(graph, log)
    _check_declared_domains_match_edges(graph, log)
    return log


def _check_declared_domains_match_edges(graph: KnowledgeGraph, log: ProblemLog) -> None:
    """Report records whose own domain field disagrees with their edges.

    Measured: 175 of 1034 skill records store a DISPLAY NAME in `domain`
    ("India CA Suite", "Digital Advertising") rather than a slug, so an id
    built from that field names no node. The membership edges cover every
    skill and agent with no unresolved target, so kgf reads domains from
    edges -- but the divergence is reported rather than quietly routed around,
    because it is the same denormalisation class as math_delegation_target and
    the library should know.
    """
    diverged = 0
    for skill in graph.skills.values():
        declared = skill.declared_domain
        if not declared:
            continue
        if ids.domain_id(declared) not in graph.domains:
            diverged += 1

    if diverged:
        log.defect(
            "DECLARED_DOMAIN_NOT_A_SLUG",
            f"{diverged} skill record(s) store a display name in `domain` rather than a "
            f"slug, so it resolves to no domain node; kgf reads "
            f"SKILL_BELONGS_TO_DOMAIN instead",
        )

    unlinked = [
        skill_id for skill_id in graph.skills if not graph.domain_of(skill_id)
    ]
    if unlinked:
        log.defect(
            "SKILL_WITHOUT_DOMAIN_EDGE",
            f"{len(unlinked)} skill(s) have no resolvable SKILL_BELONGS_TO_DOMAIN edge",
            source=unlinked[0],
        )


def _check_dangling_allowlists(graph: KnowledgeGraph, log: ProblemLog) -> None:
    """Fail on any dangling endpoint outside the two known allowlists."""
    dangling = graph.dangling_endpoints()
    allowed = KNOWN_DANGLING_REGULATIONS | KNOWN_DANGLING_SKILLS

    for node_id, count in sorted(dangling.items()):
        if node_id not in allowed:
            log.defect(
                "UNEXPECTED_DANGLING",
                f"{count} edge(s) reference a node absent from every registry "
                f"and from both allowlists",
                source=node_id,
            )

    occurrences = sum(dangling.values())
    if occurrences > MAX_DANGLING_OCCURRENCES:
        log.defect(
            "DANGLING_BUDGET_EXCEEDED",
            f"{occurrences} dangling endpoint occurrences exceeds the ceiling of "
            f"{MAX_DANGLING_OCCURRENCES} recorded for this library version",
        )

    unused = sorted(node for node in allowed if node not in dangling)
    if unused:
        log.info(
            "ALLOWLIST_ENTRY_UNUSED",
            f"{len(unused)} allowlisted dangling id(s) no longer occur, so the "
            f"library may have fixed them: {', '.join(unused[:5])}",
        )


def _check_no_self_loops(graph: KnowledgeGraph, log: ProblemLog) -> None:
    """Report any edge whose source and target are the same node."""
    for edge in graph.edges:
        if edge.source == edge.target:
            log.defect("SELF_LOOP", f"{edge.type} edge points at its own source", source=edge.source)


def _check_id_patterns(graph: KnowledgeGraph, log: ProblemLog) -> None:
    """Check agent and skill ids against the library's own id patterns.

    Tool-tier nodes are deliberately exempt. schema.json declares
    ^tool:(readonly|web-write|implementation)$ with a hyphen, while 29
    HAS_TOOL_ACCESS edges target `tool:web_write` with an underscore. kgf
    follows the edges so those 29 resolve; the divergence is reported as INFO
    rather than silently conformed to either side.
    """
    for node_id in graph.agents:
        if not ids.AGENT_ID_PATTERN.match(node_id):
            log.defect("ID_PATTERN", "agent id does not match ^agent:[a-z0-9_]+$", source=node_id)
    for node_id in graph.skills:
        if not ids.SKILL_ID_PATTERN.match(node_id):
            log.defect("ID_PATTERN", "skill id does not match ^skill:[a-z0-9_]+$", source=node_id)

    if "tool:web_write" in graph.tool_tiers:
        log.info(
            "TOOLTIER_ID_DIVERGENCE",
            "schema.json declares tool:web-write (hyphen) while the edges target "
            "tool:web_write (underscore); kgf follows the edges so all 29 resolve",
            source="tool:web_write",
        )


def summarize(graph: KnowledgeGraph, log: ProblemLog, markdown: MarkdownReport | None = None) -> str:
    """Human-readable validation summary for the CLI."""
    lines = [
        f"library_version: {graph.library_version}",
        f"nodes: {graph.node_count}  edges: {graph.edge_count}",
        f"  agents={len(graph.agents)} skills={len(graph.skills)} domains={len(graph.domains)} "
        f"regulations={len(graph.regulations)} tool_tiers={len(graph.tool_tiers)}",
    ]

    dangling = graph.dangling_endpoints()
    lines.append(
        f"dangling endpoints: {sum(dangling.values())} occurrence(s) across "
        f"{len(dangling)} distinct id(s) (ceiling {MAX_DANGLING_OCCURRENCES})"
    )

    fatal_count = len(log.of(Severity.FATAL))
    defect_counts = log.counts_by_code(Severity.DEFECT)
    lines.append(f"FATAL: {fatal_count}")
    lines.append("DEFECT: " + (", ".join(f"{k}={v}" for k, v in sorted(defect_counts.items())) or "none"))

    if markdown is not None:
        lines.append(
            f"markdown: {markdown.parsed}/{markdown.total} parsed, "
            f"{len(markdown.bom_stripped)} BOM-stripped, {len(markdown.failed)} malformed"
        )
        for fault, count in sorted(markdown.by_fault().items()):
            lines.append(f"  {fault}: {count}")
        for label, fault in sorted(markdown.failed.items()):
            lines.append(f"    {label}: {fault}")

    return "\n".join(lines)
