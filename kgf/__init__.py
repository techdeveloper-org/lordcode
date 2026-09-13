"""kgf -- a knowledge-graph framework over claude-global-library.

Reads the library's 528 agents, 1034 skills, 104 domains, 368 regulations and
9146 typed edges as DATA, so routing, context assembly and tool grants are
derived from the graph rather than from keyword-matched prose.

Deliberately standalone. kgf imports nothing from vishwakarma, nothing from
claude-workflow-engine and nothing from Claude Code; its only input is the
library's files on disk. The dependency runs one way -- a consumer imports
kgf, never the reverse -- and a test enforces that by importing every module
here in a subprocess with the consumer absent from sys.path, because a
same-repo sibling package makes the wrong import trivially easy to write.
"""

from __future__ import annotations

from kgf.errors import (
    GraphBuildError,
    LibraryNotFoundError,
    Problem,
    ProblemLog,
    Severity,
)
from kgf.graph import (
    EDGE_TYPES,
    TOOL_TIERS,
    Agent,
    Domain,
    Edge,
    KnowledgeGraph,
    Regulation,
    Skill,
    ToolTier,
)
from kgf.loader import build_graph, cached_graph, load_graph
from kgf.source import LibrarySource, locate_library
from kgf.validate import MarkdownReport, summarize, validate_graph, validate_markdown

__all__ = [
    "Agent",
    "Domain",
    "EDGE_TYPES",
    "Edge",
    "GraphBuildError",
    "KnowledgeGraph",
    "LibraryNotFoundError",
    "LibrarySource",
    "MarkdownReport",
    "Problem",
    "ProblemLog",
    "Regulation",
    "Severity",
    "Skill",
    "TOOL_TIERS",
    "ToolTier",
    "build_graph",
    "cached_graph",
    "load_graph",
    "locate_library",
    "summarize",
    "validate_graph",
    "validate_markdown",
]
