"""Unit tests for Milestone 5's OpenAPI contract generation + joint validation.

Matches responses by a distinctive keyword in the system prompt (same
FakeClient pattern as tests/test_documentation.py), since the persona
functions run as spawned agent processes.
"""

from __future__ import annotations

import pytest

from vishwakarma.config import ModelConfig, RoleCandidate
from vishwakarma.engine import api_contract as ac
from vishwakarma.engine.generate import GenerationError
from vishwakarma.router import Router

HLD_WITH_API = """## System Overview
A REST API exposing several endpoints for managing widgets.

## Files & Responsibilities
- app.py: FastAPI application with route handlers.
"""

HLD_WITHOUT_API = """## System Overview
A simple stopwatch CLI with start, stop, and reset commands.

## Files & Responsibilities
- stopwatch.py: the whole CLI.
"""

VALID_SRS = """## 1. Purpose
Builds a thing.

## 3. Requirements
### 3.1 Functional Requirements
FR-001: Do the thing.
"""

VALID_OPENAPI = """openapi: 3.1.0
info:
  title: Widgets API
  version: 1.0.0
paths:
  /widgets:
    get:
      responses:
        "200":
          description: OK
"""

FENCED_OPENAPI = "```yaml\n" + VALID_OPENAPI + "```"

MALFORMED_OPENAPI_MISSING_PATHS = "openapi: 3.1.0\ninfo:\n  title: X\n  version: 1.0.0\n"
MALFORMED_OPENAPI_WRONG_VERSION = "openapi: 3.0.0\npaths: {}\n"
MALFORMED_OPENAPI_EMPTY_PATHS = "openapi: 3.1.0\ninfo: {}\npaths: {}\n"
# Live-discovered failure mode: a degenerate response repeats a garbage block
# after real content; YAML collapses duplicate top-level keys to their LAST
# value, so naive "paths key present" validation would pass while the real
# paths content is silently discarded.
MALFORMED_OPENAPI_DEGENERATE_REPETITION = (
    VALID_OPENAPI + "\nopenapi: 3.1.0\npaths: {}\ninfo: {}\n" * 5
)

_OPENAPI_KEYWORD = "OpenAPI 3.1 specification"
_CONSENSUS_KEYWORD = "architecture validation gate"


class FakeClient:
    """Returns a response keyed by a distinctive keyword found in the system
    prompt, matching the spawned-agent-process call pattern used elsewhere."""

    def __init__(self, response_by_keyword: dict[str, object]):
        self.response_by_keyword = response_by_keyword
        self.call_log: list[str] = []

    def chat_completion(
        self, provider: str, model: str, messages: list[dict], priority: str = "interactive", **kwargs
    ) -> str:
        self.call_log.append(f"{provider}/{model}")
        system_content = messages[0]["content"]
        for keyword, response in self.response_by_keyword.items():
            if keyword in system_content:
                if isinstance(response, Exception):
                    raise response
                return response
        raise AssertionError(f"No fake response configured for system prompt: {system_content[:120]!r}")


def _models() -> ModelConfig:
    return ModelConfig(
        roles={"fallback_long_context": [RoleCandidate(provider="groq", model="long-context")]},
        max_heal_attempts=3,
        heal_timeout_seconds=300,
    )


def test_generate_api_contract_skips_when_no_api_surface(tmp_path):
    client = FakeClient({})
    router = Router(_models(), client)
    events = []

    result = ac.generate_api_contract(
        VALID_SRS, HLD_WITHOUT_API, tmp_path, router, client, on_event=events.append
    )

    assert result is None
    assert client.call_log == []
    assert events == [{"type": "api_contract_skipped", "reason": "no API surface described in HLD"}]
    assert not ac.api_contract_path_for(tmp_path).exists()


def test_generate_api_contract_writes_valid_spec(tmp_path):
    client = FakeClient({_OPENAPI_KEYWORD: VALID_OPENAPI})
    router = Router(_models(), client)

    result = ac.generate_api_contract(VALID_SRS, HLD_WITH_API, tmp_path, router, client)

    assert result.strip() == VALID_OPENAPI.strip()
    written = ac.api_contract_path_for(tmp_path).read_text(encoding="utf-8")
    assert written.strip() == VALID_OPENAPI.strip()


def test_generate_api_contract_accepts_fenced_yaml(tmp_path):
    client = FakeClient({_OPENAPI_KEYWORD: FENCED_OPENAPI})
    router = Router(_models(), client)

    result = ac.generate_api_contract(VALID_SRS, HLD_WITH_API, tmp_path, router, client)

    assert "```" not in result
    written = ac.api_contract_path_for(tmp_path).read_text(encoding="utf-8")
    assert "```" not in written
    assert written.strip() == VALID_OPENAPI.strip()


@pytest.mark.parametrize(
    "malformed",
    [
        MALFORMED_OPENAPI_MISSING_PATHS,
        MALFORMED_OPENAPI_WRONG_VERSION,
        MALFORMED_OPENAPI_EMPTY_PATHS,
        MALFORMED_OPENAPI_DEGENERATE_REPETITION,
        "not: valid: [yaml",
    ],
)
def test_generate_api_contract_raises_on_malformed_spec(tmp_path, malformed):
    client = FakeClient({_OPENAPI_KEYWORD: malformed})
    router = Router(_models(), client)

    with pytest.raises(GenerationError, match="not a valid OpenAPI"):
        ac.generate_api_contract(VALID_SRS, HLD_WITH_API, tmp_path, router, client)

    assert not ac.api_contract_path_for(tmp_path).exists()


def test_run_joint_validation_reuses_consensus_persona_and_appends_to_hld(tmp_path):
    from vishwakarma.engine.sdlc import hld_path_for  # api_contract writes via this same path

    hld_path = hld_path_for(tmp_path)
    hld_path.parent.mkdir(parents=True)
    hld_path.write_text(HLD_WITH_API, encoding="utf-8")

    client = FakeClient({_CONSENSUS_KEYWORD: "VERDICT: APPROVED\nREASON: All paths trace to the HLD."})
    router = Router(_models(), client)

    result = ac.run_joint_validation(VALID_SRS, HLD_WITH_API, VALID_OPENAPI, tmp_path, router, client)

    assert ac.JOINT_VALIDATION_HEADING in result
    assert "APPROVED" in result
    assert HLD_WITH_API.strip() in result
    assert hld_path.read_text(encoding="utf-8") == result


def test_run_joint_validation_refuses_when_already_present(tmp_path):
    hld_with_validation = HLD_WITH_API + f"\n\n{ac.JOINT_VALIDATION_HEADING}\n\nAlready done.\n"
    client = FakeClient({_CONSENSUS_KEYWORD: "should not be called"})
    router = Router(_models(), client)

    with pytest.raises(GenerationError, match="already present"):
        ac.run_joint_validation(VALID_SRS, hld_with_validation, VALID_OPENAPI, tmp_path, router, client)

    assert client.call_log == []


DESIGN_TOKENS = {"tokens": {"colors": ["#111827"]}, "accessibility": {"violations": []}}


def test_run_full_stack_reconciliation_reuses_consensus_persona_and_appends_to_hld(tmp_path):
    from vishwakarma.engine.sdlc import hld_path_for

    hld_path = hld_path_for(tmp_path)
    hld_path.parent.mkdir(parents=True)
    hld_path.write_text(HLD_WITH_API, encoding="utf-8")

    client = FakeClient({_CONSENSUS_KEYWORD: "VERDICT: APPROVED\nREASON: Tokens match the HLD."})
    router = Router(_models(), client)

    result = ac.run_full_stack_reconciliation(VALID_SRS, HLD_WITH_API, DESIGN_TOKENS, tmp_path, router, client)

    assert ac.RECONCILIATION_HEADING in result
    assert "APPROVED" in result
    assert HLD_WITH_API.strip() in result
    assert hld_path.read_text(encoding="utf-8") == result


def test_run_full_stack_reconciliation_appends_after_existing_joint_validation(tmp_path):
    from vishwakarma.engine.sdlc import hld_path_for

    hld_with_joint_validation = HLD_WITH_API + f"\n\n{ac.JOINT_VALIDATION_HEADING}\n\nAlready approved.\n"
    hld_path = hld_path_for(tmp_path)
    hld_path.parent.mkdir(parents=True)
    hld_path.write_text(hld_with_joint_validation, encoding="utf-8")

    client = FakeClient({_CONSENSUS_KEYWORD: "VERDICT: APPROVED\nREASON: Tokens match the HLD."})
    router = Router(_models(), client)

    result = ac.run_full_stack_reconciliation(
        VALID_SRS, hld_with_joint_validation, DESIGN_TOKENS, tmp_path, router, client
    )

    assert ac.JOINT_VALIDATION_HEADING in result
    assert ac.RECONCILIATION_HEADING in result
    assert result.index(ac.JOINT_VALIDATION_HEADING) < result.index(ac.RECONCILIATION_HEADING)


def test_run_full_stack_reconciliation_refuses_when_already_present(tmp_path):
    hld_with_reconciliation = HLD_WITH_API + f"\n\n{ac.RECONCILIATION_HEADING}\n\nAlready done.\n"
    client = FakeClient({_CONSENSUS_KEYWORD: "should not be called"})
    router = Router(_models(), client)

    with pytest.raises(GenerationError, match="already present"):
        ac.run_full_stack_reconciliation(VALID_SRS, hld_with_reconciliation, DESIGN_TOKENS, tmp_path, router, client)

    assert client.call_log == []
