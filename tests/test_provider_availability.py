"""Issue #21: a keyless provider must be selectable, or "any LLM" is false.

LLMClient.is_available gated purely on a non-empty env var, and
router.validate_startup skips any candidate it refuses -- so a local Ollama,
which has no key at all, was unselectable by construction. That made the claim
that any LLM is just configuration false for precisely the provider class that
runs without spend.

Windows-safe: ASCII only.
"""

from __future__ import annotations

import pytest

from vishwakarma.config import ConfigError, ProviderConfig, load_config
from vishwakarma.llm_client import LLMClient, ProviderUnavailableError


def _providers() -> dict[str, ProviderConfig]:
    return {
        "keyed": ProviderConfig(
            name="keyed",
            base_url="https://example.invalid/v1",
            api_key_env="A_KEY_NOBODY_HAS",
            rpm_budget=30,
            tpm_budget=6000,
        ),
        "keyless": ProviderConfig(
            name="keyless",
            base_url="http://localhost:11434/v1",
            rpm_budget=600,
            api_key_required=False,
        ),
    }


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("A_KEY_NOBODY_HAS", raising=False)
    return LLMClient(_providers())


class TestAvailability:
    def test_a_keyless_provider_is_available_with_no_env_var(self, client):
        assert client.is_available("keyless") is True

    def test_a_keyed_provider_without_its_key_is_still_unavailable(self, client):
        """The flag must not become a blanket bypass."""
        assert client.is_available("keyed") is False

    def test_a_keyed_provider_with_its_key_is_available(self, client, monkeypatch):
        monkeypatch.setenv("A_KEY_NOBODY_HAS", "sk-something")
        assert client.is_available("keyed") is True

    def test_an_empty_env_var_name_does_not_read_the_whole_environment(self, client):
        """api_key_env defaults to "", and os.environ.get("") is None -- but
        relying on that would make an empty name mean "no key needed", which is
        what api_key_required says explicitly."""
        broken = ProviderConfig(name="broken", base_url="x", rpm_budget=1, api_key_env="")
        assert LLMClient({"broken": broken}).is_available("broken") is False


class TestClientConstruction:
    def test_a_keyless_provider_constructs_a_client(self, client):
        """The OpenAI SDK refuses to construct without a key, while a keyless
        OpenAI-compatible endpoint ignores whatever is sent."""
        assert client._get_client("keyless") is not None

    def test_the_placeholder_is_not_a_credential(self, client):
        constructed = client._get_client("keyless")
        assert constructed.api_key == "not-required"

    def test_a_keyed_provider_without_its_key_still_refuses(self, client):
        with pytest.raises(ProviderUnavailableError):
            client._get_client("keyed")


class TestConfigParsing:
    def test_api_key_env_is_optional_when_no_key_is_required(self):
        provider = ProviderConfig(name="p", base_url="x", rpm_budget=1, api_key_required=False)
        assert provider.api_key_env == ""

    def test_the_shipped_models_yaml_declares_the_new_providers(self):
        config = load_config()
        assert {
            "groq",
            "ollama",
            "openai",
            "anthropic-compatible",
            "gemini",
        } <= set(config.providers)

    def test_gemini_is_declared_and_selectable_once_its_key_exists(self, monkeypatch):
        """Adding a provider must be configuration, not a code change.

        This is the assertion behind that claim: the gemini block was added to
        models.yaml with no edit to config.py or llm_client.py, and it becomes
        selectable the moment GEMINI_API_KEY is set -- which is exactly what
        `api_key_required` and the per-provider budgets exist to make true.
        """
        config = load_config()
        gemini = config.providers["gemini"]
        assert gemini.api_key_env == "GEMINI_API_KEY"
        assert gemini.api_key_required is True

        client = LLMClient(config.providers)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        assert client.is_available("gemini") is False, "no key means unavailable"

        monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-a-real-credential")
        assert client.is_available("gemini") is True

    def test_gemini_points_at_the_openai_compatible_endpoint(self):
        """The native Gemini API is not OpenAI-shaped.

        `/v1beta` alone would fail on the REQUEST SHAPE rather than on the key,
        which is the confusing failure the anthropic-compatible block documents.
        Only `/v1beta/openai/` speaks what this client sends.
        """
        base_url = load_config().providers["gemini"].base_url
        assert base_url.rstrip("/").endswith("/openai"), (
            f"gemini must use the OpenAI-compatible path, got {base_url}"
        )

    def test_ollama_needs_no_key_and_declares_no_token_ceiling(self):
        """A local runtime has no published limit, so inventing one would pace
        it for no reason."""
        ollama = load_config().providers["ollama"]
        assert ollama.api_key_required is False
        assert ollama.api_key_env == ""
        assert ollama.tpm_budget is None

    def test_ollama_colab_needs_no_key_and_declares_no_token_ceiling(self):
        """Same reasoning as local ollama: a free Colab GPU session has no
        published limit and no billing."""
        ollama_colab = load_config().providers["ollama-colab"]
        assert ollama_colab.api_key_required is False
        assert ollama_colab.api_key_env == ""
        assert ollama_colab.tpm_budget is None

    def test_the_new_providers_are_defined_but_unused(self):
        """validate_startup only walks providers a role names, so declaring one
        costs nothing -- and pointing a role at it is then a config edit.

        gemini and ollama-colab are the two declared providers that ARE
        wired (into primary_coder and reasoner only -- see test_router.py
        for the fallback-resolution coverage), so they are excluded from
        this set. openai and anthropic-compatible remain genuinely unused.
        """
        config = load_config()
        named = {
            candidate.provider
            for candidates in config.models.roles.values()
            for candidate in candidates
        }
        assert named == {"groq", "gemini", "ollama-colab"}

    def test_a_keyed_provider_missing_api_key_env_is_a_config_error(self):
        from vishwakarma.config import _parse_providers

        with pytest.raises(ConfigError, match="api_key_required: false"):
            _parse_providers({"providers": {"p": {"base_url": "x", "rpm_budget": 1}}})

    def test_the_error_names_the_flag_that_fixes_it(self):
        from vishwakarma.config import _parse_providers

        with pytest.raises(ConfigError) as raised:
            _parse_providers({"providers": {"p": {"base_url": "x", "rpm_budget": 1}}})
        assert "api_key_env" in str(raised.value)

    def test_base_url_and_rpm_are_still_required(self):
        from vishwakarma.config import _parse_providers

        with pytest.raises(ConfigError, match="base_url"):
            _parse_providers({"providers": {"p": {"rpm_budget": 1, "api_key_required": False}}})

    def test_base_url_env_overrides_the_literal_when_set(self, monkeypatch):
        """The mechanism ollama-colab uses to keep a session-scoped tunnel URL
        out of git-tracked models.yaml."""
        from vishwakarma.config import _parse_providers

        monkeypatch.setenv("SOME_TUNNEL_URL", "https://real-tunnel.example/v1")
        providers = _parse_providers(
            {
                "providers": {
                    "p": {
                        "base_url": "https://placeholder.invalid/v1",
                        "base_url_env": "SOME_TUNNEL_URL",
                        "rpm_budget": 1,
                        "api_key_required": False,
                    }
                }
            }
        )
        assert providers["p"].base_url == "https://real-tunnel.example/v1"

    def test_base_url_env_falls_back_to_the_literal_when_unset(self, monkeypatch):
        from vishwakarma.config import _parse_providers

        monkeypatch.delenv("SOME_TUNNEL_URL", raising=False)
        providers = _parse_providers(
            {
                "providers": {
                    "p": {
                        "base_url": "https://placeholder.invalid/v1",
                        "base_url_env": "SOME_TUNNEL_URL",
                        "rpm_budget": 1,
                        "api_key_required": False,
                    }
                }
            }
        )
        assert providers["p"].base_url == "https://placeholder.invalid/v1"


class TestStartupIsUnaffected:
    def test_startup_still_succeeds_with_only_the_groq_key(self, monkeypatch):
        """Adding three provider blocks must not make the tool refuse to start
        for want of keys it does not use."""
        monkeypatch.setenv("GROQ_API_KEY", "sk-test")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        config = load_config()
        client = LLMClient(config.providers)

        assert client.is_available("groq") is True
        assert client.is_available("openai") is False
        assert client.is_available("anthropic-compatible") is False
