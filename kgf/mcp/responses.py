"""The response envelope every kgf MCP tool returns, and the error wrapper.

Three versions travel in every response and they move for unrelated reasons,
so conflating any two of them would be the mistake `kg_version` already
demonstrates in the library itself:

    surface_version   this API's shape. Additive-only: a new optional field or
                      a new tool is free, a removal or a rename is breaking.
                      api-design-core M4 prices version proliferation at
                      O(n x codebase_size), so the rule is stated before there
                      is more than one version rather than after.
    library_version   which release of claude-global-library answered.
    fingerprint       sha256 per registry -- the CONTENT identity, which the
                      version cannot supply because an unreleased local edit
                      does not move a release label.

`correlation_id` ties one compose together across four processes.
logging-patterns requires an id that "ties together all log entries for a
single request across services", and four stdio servers are exactly that
topology: without one, a compose is four unrelated log streams and nobody can
answer "what did this single request actually do". It also closes a hole in
manifest merging -- two fragments from DIFFERENT composes against the same
library agree on their registry digests and would otherwise merge into a
decision nobody made.

`manifest_fragment` appears only on the four tools that produce a decision
worth recording. It was on all 17 in the first draft, which meant 13 responses
carrying an empty key: kgf_stats has no decision to record, and a field that is
empty most of the time teaches a caller to ignore it.

The error wrapper is reimplemented here rather than imported from a sibling
repo's `base` package. It is about forty lines, and importing it would be the
cross-repository coupling ADR-2 exists to prevent -- paying a dependency on
another project's framework to avoid writing a decorator.
"""

from __future__ import annotations

import functools
import json
import logging
from typing import Any, Callable

SURFACE_VERSION = "1"
"""Version of the tool surface itself. Additive changes do not bump it."""

MAX_RESPONSE_BYTES = 64_000
"""Ceiling on one tool's serialised response.

Output size is a real constraint here and is not one on the CLI. `kgf validate`
prints to a terminal a human scrolls past; the same payload over MCP lands in a
model's context window, and M1 catalogues 6,696 EdgeID-pattern failures, 1,051
duplicate triples and 591 null edge ids. A full inline defect list is tens of
thousands of tokens and would evict the very context M3 exists to budget.

Exceeding this is an ERROR, never a silent truncation -- the same discipline M4
applied to the WebFetch size cap, and for the same reason: a truncated document
that looks complete is worse than one that failed.
"""

TOOLS_WITH_MANIFEST = ("kgf_route", "kgf_closure", "kgf_context", "kgf_grant")
"""The only tools that record a decision, so the only ones carrying a fragment."""

logger = logging.getLogger("kgf.mcp")


class ResponseTooLarge(Exception):
    """Raised when a tool's payload exceeds MAX_RESPONSE_BYTES."""


def envelope(
    tool: str,
    data: Any,
    *,
    library_version: str = "",
    fingerprint: tuple | list = (),
    correlation_id: str = "",
    manifest_fragment: dict | None = None,
) -> dict:
    """Build a successful response.

    Raises:
        ResponseTooLarge: if the serialised payload exceeds the cap. Checked
            here rather than in each tool so no tool can forget it.
    """
    payload: dict[str, Any] = {
        "ok": True,
        "data": data,
        "error": None,
        "surface_version": SURFACE_VERSION,
        "library_version": library_version,
        "fingerprint": [list(item) for item in fingerprint],
        "correlation_id": correlation_id,
    }
    if manifest_fragment is not None:
        if tool not in TOOLS_WITH_MANIFEST:
            raise ValueError(
                f"{tool} supplied a manifest_fragment; only {', '.join(TOOLS_WITH_MANIFEST)} "
                "record a decision worth replaying"
            )
        payload["manifest_fragment"] = manifest_fragment

    size = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    if size > MAX_RESPONSE_BYTES:
        raise ResponseTooLarge(
            f"{tool} produced {size} bytes, over the {MAX_RESPONSE_BYTES} cap. "
            "Narrow the request -- ask for one defect class, a smaller budget, or "
            "fewer matches. The response is refused rather than truncated, because a "
            "truncated result that looks complete is worse than one that failed."
        )
    return payload


def failure(tool: str, error: str, *, correlation_id: str = "") -> dict:
    """Build a failed response.

    A failure is still a RESPONSE, not a raised exception across the wire: the
    session survives so a caller can ask something else, which is the same
    reasoning M4 used to make a tool denial a result rather than an exception.
    """
    return {
        "ok": False,
        "data": None,
        "error": error,
        "surface_version": SURFACE_VERSION,
        "library_version": "",
        "fingerprint": [],
        "correlation_id": correlation_id,
    }


def tool_handler(fn: Callable[..., dict]) -> Callable[..., str]:
    """Wrap a tool so no exception escapes and every call is logged with its id.

    Returns JSON text. `structuredContent` is populated by the MCP server layer
    from the same dict, so vishwakarma's `_extract_result_data` takes its typed
    path rather than the JSON-text fallback -- both are fed from one object so
    they cannot disagree.

    Structured logging per logging-patterns: service, surface_version and
    correlation_id on every line, so four servers' logs can be stitched into
    one request.
    """

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> str:
        correlation_id = str(kwargs.get("correlation_id") or "")
        name = fn.__name__
        try:
            result = fn(*args, **kwargs)
        except ResponseTooLarge as exc:
            logger.warning(
                "tool response over cap",
                extra={"service": "kgf.mcp", "tool": name, "correlation_id": correlation_id},
            )
            result = failure(name, str(exc), correlation_id=correlation_id)
        except Exception as exc:
            logger.error(
                "tool raised",
                extra={"service": "kgf.mcp", "tool": name, "correlation_id": correlation_id},
                exc_info=True,
            )
            result = failure(name, f"{type(exc).__name__}: {exc}", correlation_id=correlation_id)
        else:
            logger.info(
                "tool completed",
                extra={
                    "service": "kgf.mcp",
                    "tool": name,
                    "correlation_id": correlation_id,
                    "surface_version": SURFACE_VERSION,
                },
            )
        return json.dumps(result, ensure_ascii=False, default=str)

    return wrapper
