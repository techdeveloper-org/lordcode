"""Reading kgf's own server registry.

Separate from `kgf.mcp.__init__` so the CLI can read the registry without
importing four server modules, each of which pulls in the loader, the selector
and the tool runtime. `kgf mcp list` should not cost a graph build.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

REGISTRY_FILENAME = "servers.json"


def registry_path() -> Path:
    """Absolute path to servers.json, from the installed package location."""
    return Path(__file__).resolve().parent / REGISTRY_FILENAME


@lru_cache(maxsize=1)
def registry() -> dict:
    """The parsed registry.

    Cached because it is read by every `kgf mcp` invocation and never changes
    within a process.
    """
    return json.loads(registry_path().read_text(encoding="utf-8"))
