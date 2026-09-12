"""Configuration loading and startup validation for Vishwakarma.

Each role (primary_coder, router_fast, reasoner, fallback_long_context) is
backed by an ORDERED list of (provider, model) candidates. This lets the
router fall across providers, not just across models within one provider,
if a provider's catalog changes or a specific model becomes unavailable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

DEFAULT_MODELS_FILE = Path(__file__).resolve().parent.parent / "models.yaml"
ROLE_NAMES = ("primary_coder", "router_fast", "reasoner", "fallback_long_context")

# Loaded once at import time so every entrypoint (cli.py, webapp/server.py,
# tests) sees .env-provided keys without needing its own dotenv call. Real
# environment variables (already exported in the shell) always take
# precedence -- load_dotenv() never overrides an existing os.environ value.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


class ConfigError(Exception):
    """Raised when configuration is missing or invalid."""


@dataclass(frozen=True)
class ProviderConfig:
    """One OpenAI-compatible provider: where to call it and which env var holds its key."""

    name: str
    base_url: str
    api_key_env: str
    rpm_budget: int


@dataclass(frozen=True)
class RoleCandidate:
    """One (provider, model) option for a role, tried in list order.

    api_key_env optionally names a DIFFERENT env var than the provider's
    default -- lets a candidate use its own dedicated key/quota instead of
    sharing the provider's single default key, for any provider that hands
    out multiple keys (unused for Groq today, which has just one key, but
    kept available for future providers that do this).
    """

    provider: str
    model: str
    api_key_env: str | None = None


@dataclass(frozen=True)
class ModelConfig:
    """Per-role candidate chains and operational limits loaded from models.yaml."""

    roles: dict[str, list[RoleCandidate]]
    max_heal_attempts: int
    heal_timeout_seconds: int


@dataclass(frozen=True)
class Config:
    """Fully resolved runtime configuration: available providers + role config."""

    providers: dict[str, ProviderConfig]
    models: ModelConfig


def _parse_providers(raw: dict) -> dict[str, ProviderConfig]:
    """Parse the `providers:` section of models.yaml into ProviderConfig objects."""
    providers_raw = raw.get("providers")
    if not isinstance(providers_raw, dict) or not providers_raw:
        raise ConfigError("models.yaml must define at least one entry under 'providers:'")

    providers: dict[str, ProviderConfig] = {}
    for name, spec in providers_raw.items():
        for key in ("base_url", "api_key_env", "rpm_budget"):
            if key not in spec:
                raise ConfigError(f"providers.{name} is missing required key '{key}'")
        providers[name] = ProviderConfig(
            name=name,
            base_url=spec["base_url"],
            api_key_env=spec["api_key_env"],
            rpm_budget=int(spec["rpm_budget"]),
        )
    return providers


def _parse_roles(raw: dict, known_providers: set[str]) -> dict[str, list[RoleCandidate]]:
    """Parse the `roles:` section of models.yaml into ordered RoleCandidate lists."""
    roles_raw = raw.get("roles")
    if not isinstance(roles_raw, dict):
        raise ConfigError("models.yaml must define a 'roles:' mapping")

    missing_roles = set(ROLE_NAMES) - roles_raw.keys()
    if missing_roles:
        raise ConfigError(f"models.yaml 'roles:' is missing required role(s): {sorted(missing_roles)}")

    roles: dict[str, list[RoleCandidate]] = {}
    for role_name in ROLE_NAMES:
        candidates_raw = roles_raw[role_name]
        if not isinstance(candidates_raw, list) or not candidates_raw:
            raise ConfigError(f"roles.{role_name} must be a non-empty list of candidates")

        candidates = []
        for entry in candidates_raw:
            if "provider" not in entry or "model" not in entry:
                raise ConfigError(f"roles.{role_name} has a candidate missing 'provider' or 'model'")
            if entry["provider"] not in known_providers:
                raise ConfigError(
                    f"roles.{role_name} references unknown provider '{entry['provider']}' "
                    f"-- declare it under 'providers:' first"
                )
            candidates.append(
                RoleCandidate(
                    provider=entry["provider"],
                    model=entry["model"],
                    api_key_env=entry.get("api_key_env"),
                )
            )
        roles[role_name] = candidates
    return roles


def _read_raw_yaml(models_file: Path) -> dict:
    """Read and mapping-validate the raw models.yaml content."""
    if not models_file.exists():
        raise ConfigError(f"models.yaml not found at {models_file}")

    with models_file.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ConfigError(f"models.yaml at {models_file} did not parse to a mapping")
    return raw


def load_config(models_file: Path | None = None) -> Config:
    """Load runtime configuration from models.yaml.

    Provider API keys are read lazily by llm_client.py (a provider with no
    key set is simply treated as unavailable, so the role's next candidate
    is tried) -- so this function does NOT require every declared provider's
    key to be present, only that at least the file itself is valid.

    Args:
        models_file: Optional override path to models.yaml, defaults to the
            repository root copy.

    Returns:
        A fully resolved Config.

    Raises:
        ConfigError: If models.yaml is missing or invalid.
    """
    raw = _read_raw_yaml(models_file or DEFAULT_MODELS_FILE)

    for key in ("max_heal_attempts", "heal_timeout_seconds"):
        if key not in raw:
            raise ConfigError(f"models.yaml is missing required key '{key}'")

    providers = _parse_providers(raw)
    roles = _parse_roles(raw, known_providers=set(providers))
    models = ModelConfig(
        roles=roles,
        max_heal_attempts=int(raw["max_heal_attempts"]),
        heal_timeout_seconds=int(raw["heal_timeout_seconds"]),
    )
    return Config(providers=providers, models=models)
