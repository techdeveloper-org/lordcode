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

from vishwakarma.llm_client import EmptyResponseError, LLMClient, ModelUnavailableError, ProviderUnavailableError
from vishwakarma.router import Router

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
        except (
            ModelUnavailableError,
            ProviderUnavailableError,
            EmptyResponseError,
            openai.APIError,
        ) as exc:
            # openai.APIError (RateLimitError, InternalServerError,
            # APITimeoutError, and other transient subclasses) only reaches
            # here after llm_client.py's own backoff/retry loop is exhausted
            # -- a still-busy shared free-tier pool, a transient 5xx, or a
            # stalled connection after ~30s of retrying is exactly what the
            # role's next candidate exists for.
            on_event({**event_base, "type": "call_fallback", "reason": str(exc)})
            logger.warning(
                "role=%s candidate=%s/%s failed (%s); advancing to next candidate",
                role,
                candidate.provider,
                candidate.model,
                exc,
            )
            router.handle_unavailable(role, candidate)
            continue

        duration_ms = int((time.monotonic() - started) * 1000)
        on_event({**event_base, "type": "call_end", "duration_ms": duration_ms})
        logger.info("role=%s call finished in %dms", role, duration_ms)
        return result
