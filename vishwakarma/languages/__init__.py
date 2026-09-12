"""Pluggable language-adapter registry.

Adding a new target stack means writing one adapter module and calling
register() once here -- no other file needs to change (cli.py, executor.py,
and the web UI all resolve adapters through get_adapter()).
"""

from __future__ import annotations

from vishwakarma.languages.base import LanguageAdapter
from vishwakarma.languages.java_spring_adapter import JavaSpringAdapter
from vishwakarma.languages.python_adapter import PythonAdapter
from vishwakarma.languages.web_adapter import WebAdapter

_REGISTRY: dict[str, LanguageAdapter] = {}


def register(adapter: LanguageAdapter) -> None:
    """Add a language adapter to the registry under its own `.name`."""
    _REGISTRY[adapter.name] = adapter


def get_adapter(name: str) -> LanguageAdapter:
    """Look up a registered language adapter by name.

    Args:
        name: The adapter's registered name (e.g. "python", "java", "web").

    Returns:
        The matching LanguageAdapter.

    Raises:
        KeyError: If no adapter is registered under that name.
    """
    if name not in _REGISTRY:
        raise KeyError(
            f"No language adapter registered for '{name}'. "
            f"Available: {sorted(_REGISTRY)}"
        )
    return _REGISTRY[name]


def available_languages() -> list[str]:
    """Return the names of all currently registered language adapters."""
    return sorted(_REGISTRY)


register(PythonAdapter())
register(JavaSpringAdapter())
register(WebAdapter())
