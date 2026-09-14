"""Resolves each role to a live (provider, model) candidate, falling across
providers -- not just across models within one provider -- when a candidate
turns out to be unavailable (no API key) or deprecated (404/410).

Candidate order is entirely data-driven from models.yaml's roles: lists, so
adding a new provider or reordering preference is a one-line YAML edit, not
a code change.
"""

from __future__ import annotations

import logging

import openai

from vishwakarma.config import ConfigError, ModelConfig, RoleCandidate
from vishwakarma.llm_client import LLMClient, ModelUnavailableError, ProviderUnavailableError

logger = logging.getLogger(__name__)

# Startup catalogue-probe failures, split by what the operator should DO about
# them. A blanket `except openai.APIError` would collapse all three, and every
# one of these is a subclass of it -- which is why the split is spelled out
# rather than left to one catch.
#
# ORDER MATTERS in validate_startup's except clauses: these are not disjoint.
# RateLimitError and the credential errors are all APIStatusError subclasses,
# and APIStatusError is where the 5xx arm lives, so the narrow arms must be
# caught BEFORE _REACHABILITY_ERRORS or they would be swallowed by it.
_CREDENTIAL_ERRORS = (openai.AuthenticationError, openai.PermissionDeniedError)
"""The key is wrong, not the host. Actionable configuration, so WARNING."""

_RATE_LIMIT_ERRORS = (openai.RateLimitError,)
"""Throttled while LISTING models. Says nothing about the model itself."""

_REACHABILITY_ERRORS = (
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.InternalServerError,
    openai.APIStatusError,
)
"""Host down, timed out, or a server-side error. Transient; skip quietly."""


class ProviderTroubleError(ConfigError):
    """Every candidate failed, and at least one failed TRANSIENTLY.

    Distinct from its parent because the remedy is opposite. `ConfigError` from
    an exhausted chain tells the operator to edit `models.yaml`; that advice is
    correct for a withdrawn model and actively harmful here, where the
    configuration was fine and the provider simply had a bad thirty seconds. A
    user who edits working configuration in response to a blip has been misled
    by the error message (#45).

    A ConfigError subclass so nothing that already catches the documented
    contract stops working, and so the CLI still exits non-zero -- the run did
    fail, and pretending otherwise would be worse than the wrong diagnosis.
    """


class ChainExhaustedError(ConfigError):
    """Every candidate for a role has been walked without one succeeding.

    A ConfigError subclass so existing handlers and the documented contract are
    unchanged -- but a distinct type, because "the chain ran out" and "your
    configuration is wrong" are not the same claim and only the caller knows
    which it was. A caller that saw only TRANSIENT failures on the way down the
    chain should catch this, put the index back, and report a provider problem;
    the default message stays correct for a genuinely withdrawn model (#45).
    """


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

    def active_index(self, role: str) -> int:
        """This role's current position in its candidate list.

        Exposed so a caller can SNAPSHOT the position before a call that might
        walk the chain, and give it back if the walk turned out to be nobody's
        fault. Paired with restore_active_index; see #45.
        """
        return self._active_index.get(role, 0)

    def restore_active_index(self, role: str, index: int) -> None:
        """Put a role back to a previously snapshotted position.

        The one writer that moves the index BACKWARDS, and deliberately narrow.
        `handle_unavailable` advances permanently ("for the rest of this
        session") because a withdrawn model stays withdrawn -- correct for that
        case, wrong when the failures were transient. A provider having a bad
        thirty seconds must not silently demote a role's preferred model for the
        remaining lifetime of the process.

        Only rolls back, never forward: passing a larger index than the current
        one is ignored rather than used as a shortcut to advance, so this cannot
        become a second way to do what handle_unavailable does.
        """
        current = self._active_index.get(role, 0)
        if index >= current:
            return
        self._active_index[role] = index
        candidate = self._models.roles[role][index]
        logger.info(
            "Role '%s': restored to %s/%s -- the failures that advanced it were transient.",
            role,
            candidate.provider,
            candidate.model,
        )

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
            raise ChainExhaustedError(
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
        unreachable_cache: dict[tuple[str, str | None], str] = {}
        """Why a provider could not be probed, so it is probed at most ONCE.

        `live_ids_cache` memoises only successes; every failure arm below used to
        `continue` without recording anything, so a provider that is down, dead or
        mis-keyed was re-probed once per role naming it. Measured against an absent
        provider on `localhost`: 13.8s each time, so four roles cost ~55s of startup
        to learn the same fact four times (#57).

        Zero cost today because only groq is wired and reachable -- and live the
        moment a second provider joins more than one role's candidate list, which
        is exactly what the xkiro work does.
        """

        for role, candidates in self._models.roles.items():
            skipped: list[str] = []
            for index, candidate in enumerate(candidates):
                label = f"{candidate.provider}/{candidate.model}"
                if not self._client.is_available(candidate.provider, candidate.api_key_env):
                    key_name = (
                        candidate.api_key_env or f"provider '{candidate.provider}' default key"
                    )
                    logger.info(
                        "Role '%s' candidate %s skipped: no API key set (%s).",
                        role,
                        label,
                        key_name,
                    )
                    skipped.append(f"{label} (no API key: {key_name})")
                    continue

                cache_key = (candidate.provider, candidate.api_key_env)
                if cache_key in unreachable_cache:
                    skipped.append(f"{label} ({unreachable_cache[cache_key]})")
                    continue

                if cache_key not in live_ids_cache:
                    try:
                        live_ids_cache[cache_key] = self._client.list_model_ids(
                            candidate.provider, candidate.api_key_env
                        )
                    except ProviderUnavailableError:
                        unreachable_cache[cache_key] = "provider unavailable"
                        skipped.append(f"{label} (provider unavailable)")
                        continue
                    except _CREDENTIAL_ERRORS as exc:
                        # An actionable configuration fault, not an outage, so it is
                        # the one catalogue failure that warrants WARNING: a typo'd
                        # key is something the operator can fix, and the existing
                        # missing-key path logs at INFO where nobody sees it.
                        key_name = (
                            candidate.api_key_env
                            or f"provider '{candidate.provider}' default key"
                        )
                        logger.warning(
                            "Role '%s' candidate %s skipped: %s rejected the credential in "
                            "%s (%s). Check that key rather than the model.",
                            role,
                            label,
                            candidate.provider,
                            key_name,
                            type(exc).__name__,
                        )
                        unreachable_cache[cache_key] = f"credential rejected via {key_name}"
                        skipped.append(f"{label} (credential rejected via {key_name})")
                        continue
                    except _RATE_LIMIT_ERRORS:
                        # NOT a skip. A throttled catalogue endpoint says nothing
                        # about whether the model works, and skipping here would
                        # retire the candidate for the whole session -- _active_index
                        # never resets. Admit it unverified and let the first real
                        # call decide.
                        logger.info(
                            "Role '%s' candidate %s admitted unverified: %s throttled the "
                            "catalogue listing, which is not evidence about the model.",
                            role,
                            label,
                            candidate.provider,
                        )
                        self._active_index[role] = index
                        break
                    except _REACHABILITY_ERRORS as exc:
                        # Unreachable host, timeout, or a 5xx. Survivable at runtime
                        # via failover, so it must be survivable here too -- this
                        # used to escape and kill startup outright, naming neither
                        # the role nor the provider (#41).
                        logger.info(
                            "Role '%s' candidate %s skipped: %s unreachable (%s).",
                            role,
                            label,
                            candidate.provider,
                            type(exc).__name__,
                        )
                        unreachable_cache[cache_key] = f"{candidate.provider} unreachable"
                        skipped.append(f"{label} ({candidate.provider} unreachable)")
                        continue

                if candidate.model not in live_ids_cache[cache_key]:
                    logger.info(
                        "Role '%s' candidate %s skipped: not in %s's live catalog.",
                        role,
                        label,
                        candidate.provider,
                    )
                    skipped.append(f"{label} (not in live catalog)")
                    continue

                self._active_index[role] = index
                break
            else:
                detail = "; ".join(skipped) if skipped else "no candidates configured"
                raise ConfigError(
                    f"Role '{role}': none of its configured candidates are usable. "
                    f"Tried: {detail}. Update models.yaml."
                )
