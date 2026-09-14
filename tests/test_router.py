"""Unit tests for router.py's cross-provider role resolution and fallback logic."""

from __future__ import annotations

import pytest

from vishwakarma.config import ConfigError, ModelConfig, RoleCandidate
from vishwakarma.llm_client import ModelUnavailableError
from vishwakarma.router import Router


class FakeClient:
    """Minimal stand-in for LLMClient exposing only what Router needs."""

    def __init__(self, available_providers: set[str], live_ids_by_provider: dict[str, set[str]]):
        self.available_providers = available_providers
        self.live_ids_by_provider = live_ids_by_provider

    def is_available(self, provider: str, api_key_env: str | None = None) -> bool:
        return provider in self.available_providers

    def list_model_ids(self, provider: str, api_key_env: str | None = None) -> set[str]:
        return self.live_ids_by_provider.get(provider, set())


def _models(candidates_by_role: dict[str, list[RoleCandidate]] | None = None) -> ModelConfig:
    default = {
        "primary_coder": [
            RoleCandidate(provider="nvidia", model="coder-a"),
            RoleCandidate(provider="openrouter", model="coder-b"),
        ],
        "router_fast": [RoleCandidate(provider="nvidia", model="fast-a")],
        "reasoner": [RoleCandidate(provider="nvidia", model="reasoner-a")],
        "fallback_long_context": [RoleCandidate(provider="nvidia", model="fallback-a")],
    }
    return ModelConfig(
        roles=candidates_by_role or default,
        max_heal_attempts=3,
        heal_timeout_seconds=300,
    )


def test_resolve_returns_first_candidate_by_default():
    models = _models()
    client = FakeClient(
        available_providers={"nvidia", "openrouter"},
        live_ids_by_provider={"nvidia": {"coder-a", "fast-a", "reasoner-a", "fallback-a"}},
    )
    router = Router(models, client)
    router.validate_startup()
    assert router.resolve("primary_coder") == RoleCandidate(provider="nvidia", model="coder-a")


def test_validate_startup_falls_across_providers_when_first_candidate_missing():
    models = _models()
    client = FakeClient(
        available_providers={"nvidia", "openrouter"},
        live_ids_by_provider={
            "nvidia": {"fast-a", "reasoner-a", "fallback-a"},
            "openrouter": {"coder-b"},
        },
    )
    router = Router(models, client)

    router.validate_startup()

    assert router.resolve("primary_coder") == RoleCandidate(provider="openrouter", model="coder-b")


def test_validate_startup_skips_provider_with_no_api_key():
    models = _models(
        {
            "primary_coder": [
                RoleCandidate(provider="nvidia", model="coder-a"),
                RoleCandidate(provider="openrouter", model="coder-b"),
            ],
            "router_fast": [
                RoleCandidate(provider="nvidia", model="fast-a"),
                RoleCandidate(provider="openrouter", model="fast-b"),
            ],
            "reasoner": [
                RoleCandidate(provider="nvidia", model="reasoner-a"),
                RoleCandidate(provider="openrouter", model="reasoner-b"),
            ],
            "fallback_long_context": [
                RoleCandidate(provider="nvidia", model="fallback-a"),
                RoleCandidate(provider="openrouter", model="fallback-b"),
            ],
        }
    )
    client = FakeClient(
        available_providers={"openrouter"},
        live_ids_by_provider={"openrouter": {"coder-b", "fast-b", "reasoner-b", "fallback-b"}},
    )
    router = Router(models, client)

    router.validate_startup()

    assert router.resolve("primary_coder") == RoleCandidate(provider="openrouter", model="coder-b")


def test_validate_startup_raises_when_every_candidate_unusable():
    models = _models(
        {
            "primary_coder": [RoleCandidate(provider="nvidia", model="coder-a")],
            "router_fast": [RoleCandidate(provider="nvidia", model="fast-a")],
            "reasoner": [RoleCandidate(provider="nvidia", model="reasoner-a")],
            "fallback_long_context": [RoleCandidate(provider="nvidia", model="fallback-a")],
        }
    )
    client = FakeClient(available_providers=set(), live_ids_by_provider={})
    router = Router(models, client)

    with pytest.raises(ConfigError):
        router.validate_startup()


def test_handle_unavailable_advances_to_next_candidate():
    models = _models()
    client = FakeClient(
        available_providers={"nvidia", "openrouter"},
        live_ids_by_provider={"nvidia": {"coder-a", "fast-a", "reasoner-a", "fallback-a"}, "openrouter": {"coder-b"}},
    )
    router = Router(models, client)
    router.validate_startup()

    failed = router.resolve("primary_coder")
    next_candidate = router.handle_unavailable("primary_coder", ModelUnavailableError("nvidia", "coder-a"))

    assert failed == RoleCandidate(provider="nvidia", model="coder-a")
    assert next_candidate == RoleCandidate(provider="openrouter", model="coder-b")
    assert router.resolve("primary_coder") == next_candidate


def test_handle_unavailable_raises_config_error_when_no_candidates_remain():
    models = _models(
        {
            "primary_coder": [RoleCandidate(provider="nvidia", model="coder-a")],
            "router_fast": [RoleCandidate(provider="nvidia", model="fast-a")],
            "reasoner": [RoleCandidate(provider="nvidia", model="reasoner-a")],
            "fallback_long_context": [RoleCandidate(provider="nvidia", model="fallback-a")],
        }
    )
    client = FakeClient(
        available_providers={"nvidia"},
        live_ids_by_provider={"nvidia": {"coder-a", "fast-a", "reasoner-a", "fallback-a"}},
    )
    router = Router(models, client)
    router.validate_startup()

    with pytest.raises(ConfigError):
        router.handle_unavailable("primary_coder", ModelUnavailableError("nvidia", "coder-a"))


class _RaisingClient(FakeClient):
    """A client whose catalogue listing raises, to exercise validate_startup's arms.

    The whole point of #41 is what happens when `list_model_ids` fails in a way
    that is NOT ProviderUnavailableError. `is_available` deliberately still
    returns True -- it checks only that a key is set, never reachability
    (llm_client.py documents this), which is exactly how the failure reaches
    the catalogue probe instead of being caught earlier.
    """

    def __init__(self, raise_for: dict[str, Exception], **kwargs):
        super().__init__(**kwargs)
        self.raise_for = raise_for
        self.listed: list[str] = []

    def list_model_ids(self, provider: str, api_key_env: str | None = None) -> set[str]:
        self.listed.append(provider)
        if provider in self.raise_for:
            raise self.raise_for[provider]
        return super().list_model_ids(provider, api_key_env)


def _api_error(kind: str) -> Exception:
    """Build a real openai exception of the requested kind.

    Constructed rather than faked because the arms are selected by subclass and
    these types are not disjoint -- AuthenticationError, PermissionDeniedError,
    RateLimitError and InternalServerError are ALL APIStatusError subclasses, so
    a test against a stand-in class would not prove the except ordering.
    """
    import httpx
    import openai

    request = httpx.Request("GET", "https://example.invalid/v1/models")
    if kind == "connection":
        return openai.APIConnectionError(request=request)
    statuses = {
        "auth": (401, openai.AuthenticationError),
        "permission": (403, openai.PermissionDeniedError),
        "rate_limit": (429, openai.RateLimitError),
        "server": (500, openai.InternalServerError),
    }
    status, cls = statuses[kind]
    response = httpx.Response(status, request=request)
    return cls("boom", response=response, body=None)


class TestStartupSurvivesAProviderItCannotVerify:
    """#41. Every case here killed the process before this change."""

    def _two_provider_models(self):
        return _models(
            {
                "primary_coder": [
                    RoleCandidate(provider="flaky", model="first"),
                    RoleCandidate(provider="nvidia", model="coder-b"),
                ]
            }
        )

    def _client(self, kind: str):
        return _RaisingClient(
            raise_for={"flaky": _api_error(kind)},
            available_providers={"flaky", "nvidia"},
            live_ids_by_provider={"nvidia": {"coder-b"}, "flaky": {"first"}},
        )

    def test_an_unreachable_provider_is_skipped_rather_than_fatal(self):
        """The measured crash: key set, host unreachable, startup dead with an
        error naming neither the role nor the provider."""
        router = Router(self._two_provider_models(), self._client("connection"))
        router.validate_startup()
        assert router.resolve("primary_coder") == RoleCandidate(
            provider="nvidia", model="coder-b"
        )

    def test_a_server_error_is_skipped_rather_than_fatal(self):
        router = Router(self._two_provider_models(), self._client("server"))
        router.validate_startup()
        assert router.resolve("primary_coder").provider == "nvidia"

    @pytest.mark.parametrize("kind", ["auth", "permission"])
    def test_a_rejected_credential_is_skipped_and_warned_about(self, kind, caplog):
        """WARNING, not INFO. A typo'd key is actionable configuration, and the
        existing missing-key path logs at INFO where nobody sees it."""
        import logging

        router = Router(self._two_provider_models(), self._client(kind))
        with caplog.at_level(logging.WARNING, logger="vishwakarma.router"):
            router.validate_startup()

        assert router.resolve("primary_coder").provider == "nvidia"
        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert warnings, "a rejected credential must reach the default log level"
        message = warnings[0].getMessage()
        assert "primary_coder" in message and "flaky" in message, (
            f"the warning must name the role and the provider, got: {message}"
        )
        assert "credential" in message.lower()

    def test_a_throttled_catalogue_does_NOT_skip_the_candidate(self):
        """The arm that must not be a skip.

        A 429 while LISTING models says nothing about whether the model works,
        and skipping would retire the candidate for the whole session because
        _active_index never resets.
        """
        router = Router(self._two_provider_models(), self._client("rate_limit"))
        router.validate_startup()
        assert router.resolve("primary_coder") == RoleCandidate(
            provider="flaky", model="first"
        ), "a throttled listing must leave the preferred candidate in place"

    def test_the_exhaustion_error_names_what_it_skipped_and_why(self):
        """Previously it named the role and nothing else, leaving the reasons in
        INFO logs that are invisible at the default level."""
        models = _models({"primary_coder": [RoleCandidate(provider="flaky", model="first")]})
        client = _RaisingClient(
            raise_for={"flaky": _api_error("connection")},
            available_providers={"flaky"},
            live_ids_by_provider={},
        )
        with pytest.raises(ConfigError) as excinfo:
            Router(models, client).validate_startup()

        message = str(excinfo.value)
        assert "primary_coder" in message
        assert "flaky/first" in message, f"must name the candidate, got: {message}"
        assert "unreachable" in message, f"must give the reason, got: {message}"

    def test_a_missing_key_is_still_reported_in_the_exhaustion_message(self):
        models = _models({"reasoner": [RoleCandidate(provider="absent", model="m")]})
        client = FakeClient(available_providers=set(), live_ids_by_provider={})
        with pytest.raises(ConfigError) as excinfo:
            Router(models, client).validate_startup()
        assert "absent/m" in str(excinfo.value)
        assert "no API key" in str(excinfo.value)
