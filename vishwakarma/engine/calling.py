"""Single choke point for every model call in the pipeline.

Resolves a role to its currently active (provider, model) via the router,
fires structured progress events (consumed by the CLI's live echo and the
web UI's activity log / SSE stream), retries across the role's remaining
candidates on a provider/model failure, and logs every call and fallback.
"""

from __future__ import annotations

import logging
import time
from typing import Callable

import openai

from vishwakarma.llm_client import (
    EmptyResponseError,
    LLMClient,
    ModelUnavailableError,
    ProviderUnavailableError,
    RateLimitExhaustedError,
    ResponseStalledError,
)
from vishwakarma.router import ChainExhaustedError, ProviderTroubleError, Router

logger = logging.getLogger(__name__)

OnEvent = Callable[[dict], None]


def noop_event(_event: dict) -> None:
    """Default no-op progress sink for callers that don't care about events."""


# Groq's reasoning models each define reasoning_effort's valid values
# differently (gpt-oss: low/medium/high; qwen3.6: none/default -- passing
# the wrong family's value is a hard 400), and none of them auto-scale the
# reasoning phase's token spend to a fixed max_tokens budget: a model can
# burn its entire completion budget on the <think> trace and never reach
# the actual answer, which surfaces downstream as a truncated/empty
# response rather than an obvious error. light_reasoning=True on call_role
# asks for whichever "skip the deep chain-of-thought" value fits the
# candidate actually resolved, for call sites (formatting/classification/
# restructuring) that don't need real chain-of-thought -- never overridden
# if the caller already passed reasoning_effort explicitly.
_LIGHT_REASONING_EFFORT_BY_MODEL_PREFIX = (
    ("qwen/", "none"),
    ("openai/gpt-oss", "low"),
)
# ollama-colab's deepseek-coder-v2:16b (models.yaml) matches neither prefix, so a
# router_fast call landing on it would silently skip reasoning_effort -- this
# is exactly why router_fast has no ollama-colab candidate: primary_coder and
# reasoner have large enough max_tokens budgets that a missed light-reasoning
# hint is a safe no-op, but router_fast's small budget is where an
# unrecognized reasoning-capable model actually burns its completion on the
# <think> trace (see models.yaml's xkiro block for the same precedent).


def _light_reasoning_effort_for(model: str) -> str | None:
    """Return the "skip deep reasoning" value for this model, if known."""
    for prefix, effort in _LIGHT_REASONING_EFFORT_BY_MODEL_PREFIX:
        if model.startswith(prefix):
            return effort
    return None


def call_role(
    role: str,
    purpose: str,
    messages: list[dict[str, str]],
    router: Router,
    client: LLMClient,
    priority: str = "interactive",
    on_event: OnEvent = noop_event,
    light_reasoning: bool = False,
    **kwargs,
) -> str:
    """Call whichever (provider, model) is currently active for a role.

    On ModelUnavailableError/ProviderUnavailableError, advances the router
    to that role's next configured candidate and retries automatically --
    the caller never has to handle fallback logic itself.

    Args:
        role: Logical role name ("primary_coder", "router_fast", "reasoner",
            "fallback_long_context").
        purpose: Short human-readable reason for this call (e.g. "classify
            task complexity"), surfaced in progress events and logs.
        messages: OpenAI-format chat messages.
        router: Resolves the role to a live (provider, model) candidate.
        client: The multi-provider LLM client to call through.
        priority: Rate-limiter priority tier ("interactive" or "background").
        on_event: Called with a dict describing each call_start/call_end/
            call_fallback event, for live progress reporting.
        light_reasoning: If True, request the resolved model's "skip deep
            chain-of-thought" reasoning_effort value (model-family-aware --
            see _light_reasoning_effort_for), unless the caller already
            passed reasoning_effort explicitly. Use for formatting/
            classification/restructuring calls that don't need real
            reasoning; leave False for calls that genuinely benefit from it
            (e.g. diagnosing a test failure).
        **kwargs: Extra chat-completion parameters (temperature, max_tokens).

    Returns:
        The model's response content string.

    Raises:
        ConfigError: If every candidate for this role is unavailable.
    """
    # Snapshotted so a chain walked entirely by TRANSIENT faults can be given
    # back. handle_unavailable advances permanently, which is right for a
    # withdrawn model and wrong for a provider having a bad thirty seconds (#45).
    entry_index = router.active_index(role)
    saw_transient = False

    while True:
        candidate = router.resolve(role)
        event_base = {
            "role": role,
            "provider": candidate.provider,
            "model": candidate.model,
            "purpose": purpose,
        }
        on_event({**event_base, "type": "call_start"})
        logger.info(
            "role=%s provider=%s model=%s purpose=%r", role, candidate.provider, candidate.model, purpose
        )
        started = time.monotonic()

        def _on_token(piece: str, _event_base=event_base) -> None:
            on_event({**_event_base, "type": "token", "content": piece})

        call_kwargs = dict(kwargs)
        if light_reasoning and "reasoning_effort" not in call_kwargs:
            effort = _light_reasoning_effort_for(candidate.model)
            if effort:
                call_kwargs["reasoning_effort"] = effort

        try:
            result = client.chat_completion(
                candidate.provider,
                candidate.model,
                messages,
                priority=priority,
                on_token=_on_token,
                api_key_env=candidate.api_key_env,
                **call_kwargs,
            )
        except RateLimitExhaustedError:
            # Deliberately re-raised BEFORE the candidate-failure clause
            # below, and deliberately without calling handle_unavailable.
            # Every candidate for a role resolves to the same provider key
            # here, so its budget is the thing that is exhausted, not the
            # model: advancing the router would silently spend the role's
            # entire fallback chain on one throttled minute and then raise
            # ConfigError("every configured candidate is unavailable") as
            # though the models had been withdrawn. The router's active
            # candidate must survive a rate limit untouched.
            on_event({**event_base, "type": "call_rate_limited"})
            logger.error(
                "role=%s candidate=%s/%s exhausted its rate-limit budget; "
                "leaving the active candidate in place",
                role,
                candidate.provider,
                candidate.model,
            )
            raise
        except (
            ModelUnavailableError,
            ProviderUnavailableError,
            EmptyResponseError,
            ResponseStalledError,
            openai.APIError,
        ) as exc:
            # openai.APIError (InternalServerError, APITimeoutError, and other
            # transient subclasses) only reaches here after llm_client.py's own
            # backoff/retry loop is exhausted -- a still-busy shared free-tier
            # pool, a transient 5xx, or a stalled connection after ~30s of
            # retrying is exactly what the role's next candidate exists for.
            # RateLimitError is NOT among them any more: it is handled above,
            # because a shared-key quota is not a candidate-level fault.
            on_event({**event_base, "type": "call_fallback", "reason": str(exc)})
            logger.warning(
                "role=%s candidate=%s/%s failed (%s); advancing to next candidate",
                role,
                candidate.provider,
                candidate.model,
                exc,
            )
            if isinstance(exc, ResponseStalledError) or (
                isinstance(exc, openai.APIError) and not isinstance(exc, ModelUnavailableError)
            ):
                # A stall means the candidate is UP, merely too slow right
                # now (#56) -- the same "the provider had a bad thirty
                # seconds" case openai.APIError already gets this treatment
                # for, and unlike ModelUnavailableError it says nothing about
                # the model being withdrawn. Recorded so that if this walk
                # exhausts the chain, the index can be handed back instead of
                # the role being demoted for the rest of the session over a
                # transient blip.
                saw_transient = True
            try:
                router.handle_unavailable(role, candidate)
            except ChainExhaustedError:
                if not saw_transient:
                    raise
                # Every candidate is spent, but at least one went down to a
                # transient -- so "every configured candidate is unavailable,
                # add more candidates to models.yaml" is a false diagnosis.
                # Put the role back where it started and say what actually
                # happened, so a retry begins from the preferred candidate.
                router.restore_active_index(role, entry_index)
                raise ProviderTroubleError(
                    f"Role '{role}': every candidate failed, and at least one failed "
                    f"transiently (last: {candidate.provider}/{candidate.model} -- {exc}). "
                    f"This is a provider problem, not a configuration one -- the candidate "
                    f"list has been left untouched. Retry; if it persists, check the "
                    f"provider's status."
                ) from exc
            continue

        duration_ms = int((time.monotonic() - started) * 1000)
        on_event({**event_base, "type": "call_end", "duration_ms": duration_ms})
        logger.info("role=%s call finished in %dms", role, duration_ms)
        return result
