"""Identifier normalisation for claude-global-library's several id conventions.

The library does not use one identifier form, and the differences are not
cosmetic: get them wrong and thousands of edge endpoints resolve to nothing.
Every rule below was measured against library_version 29.97.4, and the
measurement is recorded next to it because the obvious rule is not always the
right one.

  Node ids in agents_all/skills_all are `agent:snake_case` / `skill:snake_case`.
  All 528 agent ids match ^agent:[a-z0-9_]+$; none violate it.

  domains_all.json has NO `id` field on any of its 104 records -- only an
  integer `domain_id` and a HYPHENATED `slug`. Edge endpoints meanwhile say
  `domain:2d_game_engineering` with an underscore, so a domain node id has to
  be synthesised. Measured: 3930 domain-prefixed endpoints, 0 unresolved once
  synthesised this way.

  A prefixed reference can ALSO carry hyphens after the colon.
  patterns.json's `lead_domain` is `domain:frontend-engineering`. Folding only
  the unprefixed part is not enough: 12 of 105 patterns resolve without a
  hyphen-tolerant fold, 105 of 105 with it. This is the rule most easily
  missed, and it silently drops 93 of 105 routing patterns.

  mandatory_skills / optional_skills hold BARE hyphenated slugs, not ids --
  `java-spring-boot-microservices`, not `skill:java_spring_boot_microservices`.
  Measured: 2477 mandatory and 807 optional values, 0 unresolved once lifted
  to a `skill:` id.

  An agent record's own math_delegation_target is hyphenated INSIDE the
  prefix and is unreliable: of 253 non-empty values, 209 fail to resolve raw
  and 39 still fail even folded. The DELEGATES_MATH_TO edges are the correct
  source -- 452 edges, 85 distinct targets, 0 unresolved. Hence the rule:
  relational facts come from edges_all.json, never from a record's own
  denormalised copy.

  A00x/S00x/E00x opaque codes are deliberately NOT handled. They appear
  nowhere in _master; they belong to the per-domain files, which this
  milestone does not read. Supporting a convention we never encounter would
  be untested code pretending to be robustness.
"""

from __future__ import annotations

import re

AGENT_PREFIX = "agent"
SKILL_PREFIX = "skill"
DOMAIN_PREFIX = "domain"
REGULATION_PREFIX = "reg"
TOOL_PREFIX = "tool"

KNOWN_PREFIXES = frozenset(
    {AGENT_PREFIX, SKILL_PREFIX, DOMAIN_PREFIX, REGULATION_PREFIX, TOOL_PREFIX}
)

AGENT_ID_PATTERN = re.compile(r"^agent:[a-z0-9_]+$")
SKILL_ID_PATTERN = re.compile(r"^skill:[a-z0-9_]+$")


def canonical(ref: str) -> str:
    """Fold any reference into the one form the graph is keyed by.

    Hyphens become underscores in the part AFTER the prefix, and the prefix
    itself is preserved. Both halves matter: stripping the prefix would break
    the twelve library names whose slug legitimately begins with a type word
    (a skill called `agent-tooling-...` is not an agent), and leaving hyphens
    alone loses the 93 routing patterns described in this module's docstring.

    Args:
        ref: Any reference -- prefixed or bare, hyphenated or not.

    Returns:
        The canonical form. Non-string input is coerced via str() so a
        malformed registry value becomes a resolvable-or-not id rather than a
        TypeError deep inside a traversal.
    """
    text = str(ref).strip()
    prefix, separator, rest = text.partition(":")
    if separator and prefix in KNOWN_PREFIXES:
        return f"{prefix}:{rest.replace('-', '_')}"
    return text.replace("-", "_")


def agent_id(ref: str) -> str:
    """Canonical agent id for a reference that may lack the prefix."""
    return _with_prefix(ref, AGENT_PREFIX)


def skill_id(ref: str) -> str:
    """Canonical skill id for a bare slug or an already-prefixed reference.

    This is the lift that makes mandatory_skills resolvable: the registries
    store `java-spring-boot-microservices` while the graph is keyed by
    `skill:java_spring_boot_microservices`.
    """
    return _with_prefix(ref, SKILL_PREFIX)


def domain_id(ref: str) -> str:
    """Canonical domain id, synthesised for records that carry only a slug.

    domains_all.json has no `id` field at all, so this is the only way a
    domain node can be addressed.
    """
    return _with_prefix(ref, DOMAIN_PREFIX)


def regulation_id(ref: str) -> str:
    """Canonical regulation id."""
    return _with_prefix(ref, REGULATION_PREFIX)


def tool_tier_id(ref: str) -> str:
    """Canonical tool-tier id.

    Note the deliberate divergence from schema.json, which declares
    ^tool:(readonly|web-write|implementation)$ with a HYPHEN in `web-write`,
    while 29 HAS_TOOL_ACCESS edges target `tool:web_write` with an underscore.
    kgf follows the edges, because resolving them is the point; validate.py
    exempts kgf's synthetic tier nodes from the schema pattern and reports the
    divergence rather than hiding it.
    """
    return _with_prefix(ref, TOOL_PREFIX)


def _with_prefix(ref: str, prefix: str) -> str:
    """Canonicalise ref, adding prefix when it carries no known one."""
    text = str(ref).strip()
    head, separator, _ = text.partition(":")
    if separator and head in KNOWN_PREFIXES:
        return canonical(text)
    return f"{prefix}:{text.replace('-', '_')}"


def kind_of(node_id: str) -> str | None:
    """The node kind a canonical id names, or None if the prefix is unknown."""
    prefix, separator, _ = node_id.partition(":")
    if separator and prefix in KNOWN_PREFIXES:
        return prefix
    return None


def slug_of(node_id: str) -> str:
    """The part of a canonical id after its prefix."""
    _, separator, rest = node_id.partition(":")
    return rest if separator else node_id
