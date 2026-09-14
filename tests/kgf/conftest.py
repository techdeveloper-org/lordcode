"""Shared fixtures for the kgf suite.

Fixtures pin library_version so a library rebuild fails loudly on drift rather
than on arithmetic: three vintages of these counts already coexist in this
environment (plugins.py says 371/195, the live library is 1034/528), and a
suite asserting absolute totals against a moving library trains you to edit
the assertion instead of reading it.
"""

from __future__ import annotations

import pytest

from kgf.errors import LibraryNotFoundError
from kgf.loader import load_graph
from kgf.source import locate_library

PINNED_LIBRARY_VERSION = "29.98.0"
"""The library version every measured figure in this suite was derived from.

Moved from 29.97.4 when the library repaired 31 unloadable documents and closed
a five-release drift in its own VERSION file (their #160/#161).

**Re-pin before re-measuring, never after.** `at_pinned_version` compares against
this string, so while it is stale every exact-count assertion below falls to its
`else` branch -- `null_ids >= 0`, a truthy-list check, four grant counts skipped
outright. A stale pin therefore does not turn this suite red; it turns three
measured assertions off and leaves it green. That is the failure this module's
docstring exists to prevent, arriving through the mechanism meant to prevent it,
which is why `test_the_pin_is_not_stale` now guards it.
"""


@pytest.fixture(scope="session")
def library():
    """The located library, or skip if no checkout is present."""
    try:
        return locate_library()
    except LibraryNotFoundError as exc:
        pytest.skip(f"claude-global-library not available: {exc}")


@pytest.fixture(scope="session")
def loaded(library):
    """The graph and its problem log, loaded once for the session."""
    return load_graph(library.root)


@pytest.fixture(scope="session")
def graph(loaded):
    """The loaded KnowledgeGraph."""
    return loaded[0]


@pytest.fixture(scope="session")
def problems(loaded):
    """The ProblemLog from loading the graph."""
    return loaded[1]


@pytest.fixture(scope="session")
def pinned_version():
    """The pinned version string itself, for tests that report the mismatch."""
    return PINNED_LIBRARY_VERSION


@pytest.fixture(scope="session")
def at_pinned_version(graph):
    """True when the live library matches the version the figures came from.

    Tests asserting an exact measured count consult this and fall back to a
    bounded assertion otherwise, so a library bump reports "drifted" rather
    than "broken".
    """
    return graph.library_version == PINNED_LIBRARY_VERSION
