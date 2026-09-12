"""Unit tests for Milestone 1's SRS/HLD artifact generation, using a mocked
LLM client. No real API calls are made and no API keys are required.
"""

from __future__ import annotations

import pytest

from vishwakarma.config import ModelConfig, RoleCandidate
from vishwakarma.engine import sdlc
from vishwakarma.engine.generate import GenerationError
from vishwakarma.router import Router

VALID_SRS = """## 1. Purpose
Builds a thing.

## 2. Scope
In scope: the thing. Out of scope: other things.

## 3. Requirements
### 3.1 Functional Requirements
FR-001: Do the thing. Priority: High.

### 3.2 Non-Functional Requirements
NFR-001: Do it fast. Priority: Medium.

## 4. Acceptance Criteria
AC-FR-001: The thing is done.

## 5. Out of Scope
Other things.

## 6. Change Log
| Date | Version | Change | Status |
|------|---------|--------|--------|
| 2026-01-01 | 1.0.0 | Initial creation | Done |
"""

INCOMPLETE_SRS = """## 1. Purpose
Builds a thing.

## 2. Scope
In scope.
"""

VALID_HLD = """## System Overview
A thing that does things.

## Files & Responsibilities
- thing.py: does the thing.

## Key Design Decisions
Chose a list. Why: simple. Alternative rejected: a database, overkill.

## Data Flow
Input goes in, output comes out.

## Edge Cases
Empty input (FR-001).

## Risks
None significant.
"""

INCOMPLETE_HLD = """## System Overview
A thing.

## Files & Responsibilities
- thing.py
"""


class FakeClient:
    """Returns queued responses in order, one per chat_completion call."""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.call_log: list[str] = []
        self.messages_log: list[list[dict]] = []

    def chat_completion(
        self, provider: str, model: str, messages: list[dict], priority: str = "interactive", **kwargs
    ) -> str:
        self.call_log.append(f"{provider}/{model}")
        self.messages_log.append(messages)
        return self.responses.pop(0)


def _models() -> ModelConfig:
    return ModelConfig(
        roles={
            "primary_coder": [RoleCandidate(provider="groq", model="coder")],
            "router_fast": [RoleCandidate(provider="groq", model="fast")],
            "reasoner": [RoleCandidate(provider="groq", model="reasoner")],
            "fallback_long_context": [RoleCandidate(provider="groq", model="long-context")],
        },
        max_heal_attempts=3,
        heal_timeout_seconds=300,
    )


def test_generate_srs_writes_file_with_all_sections(tmp_path):
    client = FakeClient(
        ["engineered context", "engineered requirements", VALID_SRS, "VERDICT: APPROVED\nREASON: Covers it."]
    )
    router = Router(_models(), client)

    result = sdlc.generate_srs("build a thing", tmp_path, router, client)

    assert VALID_SRS.strip() in result
    assert "## Requirements Review" in result
    assert "APPROVED" in result
    written = sdlc.srs_path_for(tmp_path).read_text(encoding="utf-8")
    assert written == result
    for heading in sdlc.SRS_REQUIRED_HEADINGS:
        assert heading in written
    # All 4 calls (context, prompt, generate, review) routed to
    # fallback_long_context, never reasoner (qwen's 1000-token cap risk)
    assert client.call_log == ["groq/long-context"] * 4


def test_generate_srs_review_extra_instruction_reaches_request_content(tmp_path):
    client = FakeClient(
        ["engineered context", "engineered requirements", VALID_SRS, "VERDICT: APPROVED\nREASON: fine."]
    )
    router = Router(_models(), client)

    sdlc.generate_srs("build a thing", tmp_path, router, client)

    review_messages = client.messages_log[-1]
    review_content = review_messages[-1]["content"]
    assert sdlc.SRS_INVENTED_SCOPE_INSTRUCTION in review_content


def test_generate_srs_raises_on_missing_sections(tmp_path):
    client = FakeClient(["engineered context", "engineered requirements", INCOMPLETE_SRS])
    router = Router(_models(), client)

    with pytest.raises(GenerationError, match="missing required section"):
        sdlc.generate_srs("build a thing", tmp_path, router, client)

    assert not sdlc.srs_path_for(tmp_path).exists()


def test_generate_srs_refuses_when_file_already_exists(tmp_path):
    srs_path = sdlc.srs_path_for(tmp_path)
    srs_path.parent.mkdir(parents=True)
    srs_path.write_text("already here", encoding="utf-8")

    client = FakeClient(
        ["engineered context", "engineered requirements", VALID_SRS, "VERDICT: APPROVED\nREASON: fine."]
    )
    router = Router(_models(), client)

    with pytest.raises(GenerationError, match="already exists"):
        sdlc.generate_srs("build a thing", tmp_path, router, client)

    # Refused before any model call was made
    assert client.call_log == []
    assert srs_path.read_text(encoding="utf-8") == "already here"


def test_generate_hld_writes_file_with_self_review_section(tmp_path):
    # Calls in order: engineer_context, engineer_prompt, generate HLD, consensus_review.
    client = FakeClient(
        ["engineered context", "engineered input", VALID_HLD, "VERDICT: APPROVED\nREASON: Covers the FRs."]
    )
    router = Router(_models(), client)

    result = sdlc.generate_hld(VALID_SRS, "build a thing", tmp_path, router, client)

    for heading in sdlc.HLD_REQUIRED_HEADINGS:
        assert heading in result
    assert "## Architect Self-Review" in result
    assert "APPROVED" in result
    assert client.call_log == ["groq/long-context"] * 4

    written = sdlc.hld_path_for(tmp_path).read_text(encoding="utf-8")
    assert written == result


def test_generate_hld_raises_on_missing_sections(tmp_path):
    client = FakeClient(["engineered context", "engineered input", INCOMPLETE_HLD])
    router = Router(_models(), client)

    with pytest.raises(GenerationError, match="missing required section"):
        sdlc.generate_hld(VALID_SRS, "build a thing", tmp_path, router, client)

    assert not sdlc.hld_path_for(tmp_path).exists()


def test_generate_hld_refuses_when_file_already_exists(tmp_path):
    hld_path = sdlc.hld_path_for(tmp_path)
    hld_path.parent.mkdir(parents=True)
    hld_path.write_text("already here", encoding="utf-8")

    client = FakeClient(
        ["engineered context", "engineered input", VALID_HLD, "VERDICT: APPROVED\nREASON: fine."]
    )
    router = Router(_models(), client)

    with pytest.raises(GenerationError, match="already exists"):
        sdlc.generate_hld(VALID_SRS, "build a thing", tmp_path, router, client)

    assert client.call_log == []


def test_generate_hld_surfaces_rejected_verdict(tmp_path):
    client = FakeClient(
        ["engineered context", "engineered input", VALID_HLD, "VERDICT: REJECTED\nREASON: Missing an edge case."]
    )
    router = Router(_models(), client)

    result = sdlc.generate_hld(VALID_SRS, "build a thing", tmp_path, router, client)

    assert "REJECTED" in result
    assert "Missing an edge case." in result
