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

PINNED_LIBRARY_VERSION = "29.97.4"
"""The library version every measured figure in this suite was derived from."""


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
def at_pinned_version(graph):
    """True when the live library matches the version the figures came from.

    Tests asserting an exact measured count consult this and fall back to a
    bounded assertion otherwise, so a library bump reports "drifted" rather
    than "broken".
    """
    return graph.library_version == PINNED_LIBRARY_VERSION
