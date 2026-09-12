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
