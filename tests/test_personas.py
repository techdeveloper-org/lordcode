"""Tests for the persona role gate (issue #2 item 3).

The defect being fixed was not an unused feature but an active
mis-application: because no library agent.md declares a `role:` field and the
loader defaulted it to "primary_coder", every reviewer, auditor and consensus
persona was injected as the persona that writes code.
"""

from __future__ import annotations

import pytest

from vishwakarma.engine.generate import _build_system_prompt
from vishwakarma.engine.personas import SubAgent, persona_for_role


def _persona(name: str, role: str | None) -> SubAgent:
    return SubAgent(name=name, description="d", role=role, system_prompt=f"PROMPT::{name}")


def test_undeclared_role_defaults_to_none_not_primary_coder():
    """The dataclass default is what made the mis-application invisible."""
    assert SubAgent(name="x", description="d").role is None


def test_persona_with_no_declared_role_is_refused():
    assert persona_for_role(_persona("consensus-agent", None), "primary_coder") is None
    assert persona_for_role(_persona("consensus-agent", None), "reasoner") is None


def test_persona_is_applied_only_to_the_role_it_declares():
    reviewer = _persona("strict-reviewer", "reasoner")
    assert persona_for_role(reviewer, "reasoner") is reviewer
    assert persona_for_role(reviewer, "primary_coder") is None


def test_none_persona_is_passed_through():
    assert persona_for_role(None, "primary_coder") is None


def test_refusal_emits_an_observable_event():
    events: list[dict] = []
    persona_for_role(_persona("api-security-auditor", None), "primary_coder", events.append)

    assert len(events) == 1
    assert events[0]["type"] == "persona_refused"
    assert events[0]["persona"] == "api-security-auditor"
    assert events[0]["requested_role"] == "primary_coder"
    assert events[0]["reason"] == "no role declared"


def test_role_mismatch_refusal_names_the_declared_role():
    events: list[dict] = []
    persona_for_role(_persona("strict-reviewer", "reasoner"), "primary_coder", events.append)
    assert events[0]["reason"] == "declares role reasoner"


def test_auditor_persona_is_not_injected_into_the_coder_prompt():
    """The live defect: an auditor persona reaching the code-writing prompt."""
    auditor = _persona("architecture-conformance-auditor", None)
    prompt = _build_system_prompt("python", auditor)

    assert "PROMPT::architecture-conformance-auditor" not in prompt
    assert "Persona override" not in prompt


def test_declared_coder_persona_still_reaches_the_coder_prompt():
    """The gate must refuse guesses without breaking explicit declarations."""
    coder = _persona("strict-tester", "primary_coder")
    prompt = _build_system_prompt("python", coder)

    assert "PROMPT::strict-tester" in prompt
    assert "Persona override (strict-tester)" in prompt


def test_library_personas_declare_no_role_today():
    """Documents why the gate refuses everything from the library for now.

    If this ever fails, the library has started declaring roles and the
    interim regression recorded in issue #2 can be lifted.
    """
    from kgf.documents import parse_document
    from kgf.errors import LibraryNotFoundError
    from kgf.source import locate_library

    try:
        source = locate_library(None)
    except LibraryNotFoundError:
        pytest.skip("claude-global-library is not on disk")

    documents = sorted(source.agents_dir.glob("*/agent.md"))
    if not documents:
        pytest.skip("no agent documents found")

    declared = [
        path.parent.name
        for path in documents
        if parse_document(source, path).frontmatter.get("role")
    ]
    assert declared == [], f"{len(declared)} agents now declare a role: {declared[:5]}"
