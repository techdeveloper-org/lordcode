"""Tests for the 429 path: bounded same-candidate retry that never burns a role.

Issue #2 item 2. A rate limit used to reach calling.py as a generic
openai.APIError, which advanced Router._active_index permanently for the
session. Because every candidate for a role resolves to the same provider
key, the next candidate shared the same exhausted budget, so a single
throttled minute consumed the role's whole fallback chain and then raised
ConfigError as though the models had been withdrawn.
"""

from __future__ import annotations

import httpx
import openai
import pytest

from vishwakarma.config import ModelConfig, ProviderConfig, RoleCandidate
from vishwakarma.engine.calling import call_role
from vishwakarma.llm_client import (
    ModelUnavailableError,
    RATE_LIMIT_WALL_CLOCK_SECONDS,
    LLMClient,
    RateLimitExhaustedError,
    _retry_after_seconds,
    estimate_call_tokens,
)
from vishwakarma.config import ConfigError
from vishwakarma.router import ProviderTroubleError, Router

MESSAGES = [{"role": "user", "content": "hello"}]


def _rate_limit_error(retry_after: str | None = None) -> openai.RateLimitError:
    """Build a real openai.RateLimitError, optionally carrying Retry-After."""
    headers = {"retry-after": retry_after} if retry_after is not None else {}
    response = httpx.Response(
        status_code=429,
        headers=headers,
        request=httpx.Request("POST", "https://example.test/v1/chat/completions"),
    )
    return openai.RateLimitError("rate limited", response=response, body=None)


def _models() -> ModelConfig:
    return ModelConfig(
        roles={
            "primary_coder": [
                RoleCandidate(provider="groq", model="coder-a"),
                RoleCandidate(provider="groq", model="coder-b"),
            ],
            "router_fast": [RoleCandidate(provider="groq", model="fast-a")],
            "reasoner": [RoleCandidate(provider="groq", model="reasoner-a")],
            "fallback_long_context": [RoleCandidate(provider="groq", model="fallback-a")],
        },
        max_heal_attempts=3,
        heal_timeout_seconds=300,
    )


class _AlwaysRateLimitedClient:
    """Stands in for LLMClient, raising RateLimitExhaustedError like the real one."""

    def __init__(self):
        self.calls = 0

    def chat_completion(self, provider, model, messages, **kwargs):
        self.calls += 1
        raise RateLimitExhaustedError(provider, model, RATE_LIMIT_WALL_CLOCK_SECONDS, 4)

    def is_available(self, provider: str, api_key_env: str | None = None) -> bool:
        return True

    def list_model_ids(self, provider: str, api_key_env: str | None = None) -> set[str]:
        return {"coder-a", "coder-b", "fast-a", "reasoner-a", "fallback-a"}


def test_rate_limit_exhausted_is_not_an_api_error():
    """calling.py's candidate-failure clause catches openai.APIError.

    If RateLimitExhaustedError were a subclass it would be swallowed there
    and would advance the router, which is the whole bug.
    """
    assert not issubclass(RateLimitExhaustedError, openai.APIError)


def test_call_role_leaves_active_candidate_untouched_on_rate_limit():
    client = _AlwaysRateLimitedClient()
    router = Router(_models(), client)
    router.validate_startup()

    before = router.resolve("primary_coder")

    with pytest.raises(RateLimitExhaustedError):
        call_role("primary_coder", "test", MESSAGES, router, client)

    after = router.resolve("primary_coder")
    assert (after.provider, after.model) == (before.provider, before.model)
    assert client.calls == 1, "a rate limit must not be retried against another candidate"


def test_call_role_emits_a_rate_limited_event():
    client = _AlwaysRateLimitedClient()
    router = Router(_models(), client)
    router.validate_startup()

    events: list[dict] = []
    with pytest.raises(RateLimitExhaustedError):
        call_role("primary_coder", "test", MESSAGES, router, client, on_event=events.append)

    assert any(event["type"] == "call_rate_limited" for event in events)
    assert not any(event["type"] == "call_fallback" for event in events)


def test_retry_after_header_is_honoured_when_present():
    assert _retry_after_seconds(_rate_limit_error(retry_after="7")) == 7.0


def test_retry_after_absent_or_unparseable_falls_back_to_backoff():
    assert _retry_after_seconds(_rate_limit_error()) is None
    assert _retry_after_seconds(_rate_limit_error(retry_after="Wed, 21 Oct 2026 07:28:00 GMT")) is None
    assert _retry_after_seconds(_rate_limit_error(retry_after="-3")) is None
    assert _retry_after_seconds(RuntimeError("no response attribute")) is None


def test_repeated_429_raises_rate_limit_exhausted_without_advancing(monkeypatch):
    """The real client must give up on the call, not on the candidate."""
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

    slept: list[float] = []
    monkeypatch.setattr("vishwakarma.llm_client.time.sleep", slept.append)

    clock = {"now": 0.0}

    def fake_monotonic() -> float:
        clock["now"] += 40.0
        return clock["now"]

    monkeypatch.setattr("vishwakarma.llm_client.time.monotonic", fake_monotonic)

    class _Stream:
        def create(self, **kwargs):
            raise _rate_limit_error(retry_after="2")

    class _Chat:
        completions = _Stream()

    monkeypatch.setattr(client, "_get_client", lambda *a, **k: type("C", (), {"chat": _Chat()})())

    with pytest.raises(RateLimitExhaustedError) as excinfo:
        client.chat_completion("groq", "coder-a", MESSAGES, max_tokens=100)

    assert excinfo.value.attempts >= 1
    assert all(delay <= 2.0 for delay in slept), "Retry-After of 2s must cap each wait"


def test_estimate_call_tokens_counts_prompt_and_completion():
    messages = [{"role": "user", "content": "x" * 400}]
    assert estimate_call_tokens(messages, max_tokens=8000) == 100 + 8000
    assert estimate_call_tokens(messages, max_tokens=None) == 100
    assert estimate_call_tokens([{"role": "user", "content": None}], max_tokens=None) == 0


def _server_error() -> openai.InternalServerError:
    """A real transient 5xx -- the class llm_client raises after its own retries."""
    response = httpx.Response(
        status_code=500,
        request=httpx.Request("POST", "https://example.test/v1/chat/completions"),
    )
    return openai.InternalServerError("upstream blew up", response=response, body=None)


class _AlwaysFailingClient:
    """Raises the same exception for every candidate, to walk the whole chain."""

    def __init__(self, exc_factory):
        self.exc_factory = exc_factory
        self.calls = 0

    def chat_completion(self, provider, model, messages, **kwargs):
        self.calls += 1
        raise self.exc_factory(provider, model)

    def is_available(self, provider: str, api_key_env: str | None = None) -> bool:
        return True

    def list_model_ids(self, provider: str, api_key_env: str | None = None) -> set[str]:
        return {"coder-a", "coder-b", "fast-a", "reasoner-a", "fallback-a"}


class TestATransientMustNotSpendACandidate:
    """#45. Observed in a real run: two transients killed it and blamed models.yaml.

    The message said "every configured candidate is unavailable ... Add more
    candidates" while the very next run of the same command succeeded and wrote
    25 files. The configuration was never the problem.
    """

    def test_a_chain_walked_by_transients_leaves_the_index_where_it_started(self):
        """The permanent demotion is the half that outlives the run.

        _active_index has no reset anywhere, so before this fix one bad thirty
        seconds pinned the role to its fallback model for the whole session --
        silently, even on runs that then succeeded.
        """
        models = _models()
        client = _AlwaysFailingClient(lambda p, m: _server_error())
        router = Router(models, client)

        with pytest.raises(ProviderTroubleError):
            call_role("primary_coder", "p", [{"role": "user", "content": "x"}], router, client)

        assert router.active_index("primary_coder") == 0, (
            "a transient walk must hand the index back, not demote the role"
        )
        assert client.calls == 2, "both candidates should have been tried once each"

    def test_the_error_does_not_blame_the_user_s_configuration(self):
        models = _models()
        client = _AlwaysFailingClient(lambda p, m: _server_error())
        router = Router(models, client)

        with pytest.raises(ProviderTroubleError) as excinfo:
            call_role("primary_coder", "p", [{"role": "user", "content": "x"}], router, client)

        message = str(excinfo.value)
        assert "models.yaml" not in message, (
            f"a transient must not tell the operator to edit working config: {message}"
        )
        assert "provider problem" in message
        assert "Retry" in message

    def test_a_PERMANENT_failure_still_gets_today_s_diagnosis(self):
        """The control. If this fix swallowed the real case too, it would have
        replaced a wrong diagnosis with no diagnosis."""
        models = _models()
        client = _AlwaysFailingClient(lambda p, m: ModelUnavailableError(p, m))
        router = Router(models, client)

        with pytest.raises(ConfigError) as excinfo:
            call_role("primary_coder", "p", [{"role": "user", "content": "x"}], router, client)

        message = str(excinfo.value)
        assert not isinstance(excinfo.value, ProviderTroubleError), (
            "a withdrawn model IS a configuration problem and must say so"
        )
        assert "models.yaml" in message
        assert router.active_index("primary_coder") == 1, (
            "a genuinely withdrawn model must still advance permanently"
        )

    def test_restore_only_rolls_back_never_forward(self):
        """So it cannot become a second way to advance."""
        models = _models()
        client = _AlwaysFailingClient(lambda p, m: _server_error())
        router = Router(models, client)

        router.restore_active_index("primary_coder", 1)
        assert router.active_index("primary_coder") == 0, "forward moves are ignored"
