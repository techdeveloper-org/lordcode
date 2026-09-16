"""Three independent open-issue fixes, mirroring test_cheap_independent_fixes.py's
convention (#56/57/58) for a near-identical prior batch of small, unrelated fixes.

#56 -- REQUEST_TIMEOUT_SECONDS bounds the gap BETWEEN chunks, not total response
time, so a provider emitting small chunks steadily (each gap comfortably inside
30s) never fails over and an interactive caller waits indefinitely.

#40 -- declares the xkiro provider (api.xkiro.com) in models.yaml, matching the
existing gemini/anthropic-compatible "declared but unused" pattern.

#61 -- the coder's first generation attempt frequently omits the test file it
was asked for. This file's #61 tests can only assert PROMPT WORDING, never
actual model compliance -- see the class docstring below for why a green
result here must not be read as "issue resolved."
"""

from __future__ import annotations

import pytest

from vishwakarma.config import ConfigError, load_config
from vishwakarma.engine.calling import call_role
from vishwakarma.engine.generate import TEST_FILE_REMINDER, _build_system_prompt
from vishwakarma.engine.orchestrator import PROMPT_ENGINEER_SYSTEM_PROMPT
from vishwakarma.engine.personas import SubAgent
from vishwakarma.llm_client import (
    TOTAL_RESPONSE_TIMEOUT_BASE_SECONDS,
    TOTAL_RESPONSE_TIMEOUT_SECONDS_PER_TOKEN,
    LLMClient,
    ResponseStalledError,
)
from vishwakarma.router import ProviderTroubleError, Router
from vishwakarma.config import ModelConfig, ProviderConfig, RoleCandidate

MESSAGES = [{"role": "user", "content": "hello"}]


class _Delta:
    def __init__(self, content: str | None):
        self.content = content


class _Choice:
    def __init__(self, content: str | None):
        self.delta = _Delta(content)


class _Chunk:
    def __init__(self, content: str | None):
        self.choices = [_Choice(content)]


def _make_client(monkeypatch, chunks: list[_Chunk], step_seconds: float):
    """A real LLMClient whose transport is faked, with a controllable fake clock.

    Mirrors test_rate_limit_escalation.py's test_repeated_429_... pattern:
    monkeypatch time.monotonic to a step function so the test needs no real
    sleeping, and monkeypatch _get_client to hand back a stream of pre-built
    chunk objects instead of a live HTTP connection.
    """
    providers = {
        "groq": ProviderConfig(
            name="groq",
            base_url="https://example.test/v1",
            api_key_env="TEST_KEY",
            rpm_budget=600,
            tpm_budget=60_000,
        )
    }
    monkeypatch.setenv("TEST_KEY", "sk-test")
    client = LLMClient(providers)

    clock = {"now": 0.0}

    def fake_monotonic() -> float:
        clock["now"] += step_seconds
        return clock["now"]

    monkeypatch.setattr("vishwakarma.llm_client.time.monotonic", fake_monotonic)

    class _Stream:
        def create(self, **kwargs):
            return iter(chunks)

    class _Chat:
        completions = _Stream()

    monkeypatch.setattr(client, "_get_client", lambda *a, **k: type("C", (), {"chat": _Chat()})())
    return client


class TestTotalResponseTimeIsBounded:
    """#56. A steady trickle -- every gap under 30s -- must still be bounded."""

    def test_ceiling_scales_with_max_tokens(self):
        """The whole role-awareness of the fix: router_fast (60) vs primary_coder (8000)."""
        small = TOTAL_RESPONSE_TIMEOUT_BASE_SECONDS + 60 * TOTAL_RESPONSE_TIMEOUT_SECONDS_PER_TOKEN
        large = TOTAL_RESPONSE_TIMEOUT_BASE_SECONDS + 8000 * TOTAL_RESPONSE_TIMEOUT_SECONDS_PER_TOKEN
        assert large > small, "a bigger completion budget must earn a bigger ceiling"
        assert small >= TOTAL_RESPONSE_TIMEOUT_BASE_SECONDS, "the base floor must never be undercut"

    def test_a_steady_trickle_past_the_ceiling_raises_response_stalled(self, monkeypatch):
        """Regular small chunks forever, no single gap exceeding 30s -- the exact
        shape #56 describes as invisible to the existing per-chunk timeout."""
        chunks = [_Chunk("x") for _ in range(20)]
        # step_seconds=10 -> with max_tokens=0 (ceiling=60s base), trips well
        # before the 20 chunks are exhausted.
        client = _make_client(monkeypatch, chunks, step_seconds=10.0)

        with pytest.raises(ResponseStalledError):
            client.chat_completion("groq", "coder-a", MESSAGES, max_tokens=0)

    def test_a_stream_finishing_within_the_ceiling_returns_normally(self, monkeypatch):
        """No false positive: a normal-speed stream must not be killed."""
        chunks = [_Chunk("a"), _Chunk("b"), _Chunk(None), _Chunk("c")]
        client = _make_client(monkeypatch, chunks, step_seconds=1.0)

        result = client.chat_completion("groq", "coder-a", MESSAGES, max_tokens=0)

        assert result == "abc"

    def test_response_stalled_error_message_names_provider_and_model(self, monkeypatch):
        chunks = [_Chunk("x") for _ in range(20)]
        client = _make_client(monkeypatch, chunks, step_seconds=10.0)

        with pytest.raises(ResponseStalledError) as excinfo:
            client.chat_completion("groq", "coder-a", MESSAGES, max_tokens=0)

        assert excinfo.value.provider == "groq"
        assert excinfo.value.model == "coder-a"
        assert "coder-a" in str(excinfo.value)


class _AlwaysStalledClient:
    """Raises ResponseStalledError for every candidate, to walk the whole chain."""

    def __init__(self):
        self.calls = 0

    def chat_completion(self, provider, model, messages, **kwargs):
        self.calls += 1
        raise ResponseStalledError(provider, model, 999.0, 60.0)

    def is_available(self, provider: str, api_key_env: str | None = None) -> bool:
        return True

    def list_model_ids(self, provider: str, api_key_env: str | None = None) -> set[str]:
        return {"coder-a", "coder-b"}


class TestAStallIsTreatedAsTransient:
    """#56's explicit bookkeeping decision: a stall must not permanently demote a role.

    Mirrors test_rate_limit_escalation.py's TestATransientMustNotSpendACandidate,
    which asserts the same property for a generic transient openai.APIError.
    """

    def _models(self) -> ModelConfig:
        return ModelConfig(
            roles={
                "primary_coder": [
                    RoleCandidate(provider="groq", model="coder-a"),
                    RoleCandidate(provider="groq", model="coder-b"),
                ],
            },
            max_heal_attempts=3,
            heal_timeout_seconds=300,
        )

    def test_a_chain_walked_entirely_by_stalls_hands_the_index_back(self):
        client = _AlwaysStalledClient()
        router = Router(self._models(), client)

        with pytest.raises(ProviderTroubleError):
            call_role("primary_coder", "p", MESSAGES, router, client)

        assert router.active_index("primary_coder") == 0, (
            "a stall means the candidate is up, merely slow -- it must not "
            "permanently demote the role the way a withdrawn model does"
        )
        assert client.calls == 2, "both candidates should have been tried once each"


class TestXkiroIsDeclaredButUnwired:
    """#40. Declared like gemini/anthropic-compatible: present, unwired, no key required to exist."""

    def test_xkiro_provider_is_present_and_parses(self):
        config = load_config()

        assert "xkiro" in config.providers
        xkiro = config.providers["xkiro"]
        assert xkiro.base_url == "https://api.xkiro.com/v1"
        assert xkiro.api_key_env == "XKIRO_API_KEY"
        assert isinstance(xkiro.rpm_budget, int)

    def test_xkiro_tpm_budget_is_omitted_not_invented(self):
        """#40's own text: xkiro's rate ceilings are unknown and must not be
        invented -- config.py's own convention is to omit, not guess."""
        config = load_config()

        assert config.providers["xkiro"].tpm_budget is None

    def test_no_role_references_xkiro(self):
        """Matches the issue's own stated scope: declared, not wired."""
        config = load_config()

        for role, candidates in config.models.roles.items():
            for candidate in candidates:
                assert candidate.provider != "xkiro", (
                    f"role {role!r} must not be wired to xkiro yet -- #40 scopes "
                    f"this to declaration only, no key is in .env"
                )

    def test_config_loads_with_xkiro_api_key_unset(self, monkeypatch):
        """Lazy validation: an unused provider's missing key must not block startup."""
        monkeypatch.delenv("XKIRO_API_KEY", raising=False)

        try:
            load_config()
        except ConfigError as exc:
            pytest.fail(f"loading config with XKIRO_API_KEY unset must not raise: {exc}")


class TestTestFileRequirementSurvivesPromptEngineering:
    """#61. IMPORTANT: these assertions cover PROMPT WORDING ONLY.

    They are a regression guard against the test-file instruction silently
    being edited away again -- they say nothing about whether the model
    actually complies. The issue's own acceptance bar is an N-run measurement
    of attempt-0 test-file presence, which this file does not and cannot
    provide (there is no LLM call in a unit test). Do not read a green result
    here as "issue #61 resolved" -- this codebase already has a named
    principle for exactly that trap: ADR-0012, "absent evidence is not
    success," and the #59 fix #61 itself was surfaced by.
    """

    def test_prompt_engineer_system_prompt_requires_both_impl_and_test_files(self):
        lowered = PROMPT_ENGINEER_SYSTEM_PROMPT.lower()
        assert "test file" in lowered
        assert "mandatory" in lowered or "must" in lowered

    def test_system_prompt_without_persona_mentions_tests(self):
        prompt = _build_system_prompt("python", subagent=None)
        assert "test" in prompt.lower()

    def test_test_file_reminder_is_the_literal_last_element_with_no_persona(self):
        prompt = _build_system_prompt("python", subagent=None)
        assert prompt.endswith(TEST_FILE_REMINDER)

    def test_test_file_reminder_survives_and_stays_last_when_a_persona_is_active(self):
        """The concrete bug flagged in review: persona_for_role() appends the
        persona's system_prompt AFTER RESPONSE_CONTRACT, so a reminder placed
        merely 'near RESPONSE_CONTRACT' would land BEFORE the persona text,
        not after it -- exactly the case with the most competing text to lose
        the instruction in (complex tasks routed through knowledge.resolve()
        commonly set a subagent persona)."""
        subagent = SubAgent(
            name="test-persona",
            description="a persona that declares primary_coder",
            role="primary_coder",
            system_prompt="Some long persona instructions describing coding style.",
        )

        prompt = _build_system_prompt("python", subagent=subagent)

        assert "Some long persona instructions" in prompt
        assert prompt.endswith(TEST_FILE_REMINDER), (
            "the test-file reminder must be the literal last element even "
            "when a persona override is present, or the persona-steered path "
            "reproduces the exact recency bug this fix exists to close"
        )
        persona_index = prompt.index("Some long persona instructions")
        reminder_index = prompt.index(TEST_FILE_REMINDER)
        assert reminder_index > persona_index, "the reminder must come AFTER the persona block"
