"""Resolves each role to a live (provider, model) candidate, falling across
providers -- not just across models within one provider -- when a candidate
turns out to be unavailable (no API key) or deprecated (404/410).

Candidate order is entirely data-driven from models.yaml's roles: lists, so
adding a new provider or reordering preference is a one-line YAML edit, not
a code change.
"""

from __future__ import annotations

import logging

from vishwakarma.config import ConfigError, ModelConfig, RoleCandidate
from vishwakarma.llm_client import LLMClient, ModelUnavailableError, ProviderUnavailableError

logger = logging.getLogger(__name__)


class Router:
    """Resolves a logical model role to a live (provider, model) pair for this session."""

    def __init__(self, models: ModelConfig, client: LLMClient):
        self._models = models
        self._client = client
        self._active_index: dict[str, int] = {}

    def resolve(self, role: str) -> RoleCandidate:
        """Return the currently active candidate for a role.

        Returns:
            The RoleCandidate this role is currently pinned to for the session
            (index 0 unless a prior failure advanced it).
        """
        index = self._active_index.get(role, 0)
        return self._models.roles[role][index]

    def handle_unavailable(self, role: str, failed: RoleCandidate) -> RoleCandidate:
        """Advance a role past a failed candidate to its next configured option.

        Args:
            role: The role whose current candidate just failed.
            failed: The candidate that failed (for logging/context only).

        Returns:
            The next candidate now active for this role.

        Raises:
            ConfigError: If no further candidates remain for this role.
        """
        candidates = self._models.roles[role]
        next_index = self._active_index.get(role, 0) + 1
        if next_index >= len(candidates):
            raise ConfigError(
                f"Role '{role}': every configured candidate is unavailable "
                f"(last tried {failed.provider}/{failed.model}). Add more candidates to models.yaml."
            )

        self._active_index[role] = next_index
        new_candidate = candidates[next_index]
        logger.warning(
            "Role '%s': %s/%s unavailable, falling back to %s/%s for the rest of this session.",
            role,
            failed.provider,
            failed.model,
            new_candidate.provider,
            new_candidate.model,
        )
        return new_candidate

    def validate_startup(self) -> None:
        """Pick the first genuinely usable candidate for every role.

        For each role, walks its candidate list in order: skips providers
        with no API key configured, skips models missing from a reachable
        provider's live catalog, and settles on the first fully-usable
        candidate. Never crashes on a single missing provider/model --
        only raises if a role's ENTIRE candidate list is unusable.

        Raises:
            ConfigError: If a role has no usable candidate at all.
        """
        live_ids_cache: dict[tuple[str, str | None], set[str]] = {}

        for role, candidates in self._models.roles.items():
            for index, candidate in enumerate(candidates):
                if not self._client.is_available(candidate.provider, candidate.api_key_env):
                    logger.info(
                        "Role '%s' candidate %s/%s skipped: no API key set (%s).",
                        role,
                        candidate.provider,
                        candidate.model,
                        candidate.api_key_env or f"provider '{candidate.provider}' default key",
                    )
                    continue

                cache_key = (candidate.provider, candidate.api_key_env)
                if cache_key not in live_ids_cache:
                    try:
                        live_ids_cache[cache_key] = self._client.list_model_ids(
                            candidate.provider, candidate.api_key_env
                        )
                    except ProviderUnavailableError:
                        continue

                if candidate.model not in live_ids_cache[cache_key]:
                    logger.info(
                        "Role '%s' candidate %s/%s skipped: not in %s's live catalog.",
                        role,
                        candidate.provider,
                        candidate.model,
                        candidate.provider,
                    )
                    continue

                self._active_index[role] = index
                break
            else:
                raise ConfigError(
                    f"Role '{role}': none of its configured candidates are usable "
                    f"(missing API keys or deprecated models). Update models.yaml."
                )
