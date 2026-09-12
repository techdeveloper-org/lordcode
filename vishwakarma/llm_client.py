"""Multi-provider OpenAI-compatible client (Groq today, others pluggable).

A provider's `api_key_env` in models.yaml is only the DEFAULT key. A role's
candidate can optionally override `api_key_env` to use its own dedicated
key/quota instead of sharing the provider's single default key -- both the
OpenAI client cache and the rate limiter are keyed by (provider, resolved
env var), not just provider, so distinct keys never share a limiter
bucket. A key whose env var is unset is simply unavailable
(ProviderUnavailableError), letting the router move on to that role's
next candidate rather than crashing.
"""

from __future__ import annotations

import logging
import os
import random
import time
from typing import Any, Callable

import openai

from vishwakarma.config import ProviderConfig
from vishwakarma.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

MAX_RETRIES = 5
BASE_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 30.0
REQUEST_TIMEOUT_SECONDS = 120.0
"""Applied as httpx's connect/read/write timeout. Because every call streams
(see chat_completion), the 'read' timeout means max seconds between chunks,
not max total response time -- so a reasoning model that is slow but still
producing tokens is never killed, only a genuinely stalled connection is."""


class ProviderUnavailableError(Exception):
    """Raised when a provider's (or a candidate's override) API key env var is not set."""

    def __init__(self, provider: str, api_key_env: str | None = None):
        self.provider = provider
        self.api_key_env = api_key_env
        label = f"provider '{provider}'" if api_key_env is None else f"key env '{api_key_env}'"
        super().__init__(f"No API key set for {label}; skipping it")


class ModelUnavailableError(Exception):
    """Raised when a provider no longer serves a pinned model ID (404/410)."""

    def __init__(self, provider: str, model: str):
        self.provider = provider
        self.model = model
        super().__init__(f"Model '{model}' is no longer available on provider '{provider}'")


class EmptyResponseError(Exception):
    """Raised when a provider returns a response with no usable completion.

    Some free-tier models occasionally return an empty/malformed response
    (no choices, or a null message) under load or on longer prompts, even
    though the same model responds fine on a short prompt. Treated as a
    candidate-level failure (like ModelUnavailableError) so the router
    tries the role's next candidate instead of crashing.
    """

    def __init__(self, provider: str, model: str):
        self.provider = provider
        self.model = model
        super().__init__(f"Model '{model}' on provider '{provider}' returned an empty/malformed response")


class LLMClient:
    """Wraps every configured provider with per-(provider, key) rate limiting and retries."""

    def __init__(self, providers: dict[str, ProviderConfig]):
        self._providers = providers
        self._clients: dict[tuple[str, str], openai.OpenAI] = {}
        self._limiters: dict[tuple[str, str], RateLimiter] = {}

    def _resolve_api_key_env(self, provider: str, api_key_env: str | None) -> str:
        """Return the env var to use: a candidate's override, or the provider's default."""
        return api_key_env or self._providers[provider].api_key_env

    def is_available(self, provider: str, api_key_env: str | None = None) -> bool:
        """Return whether the resolved API key env var is set in the environment."""
        env_name = self._resolve_api_key_env(provider, api_key_env)
        return bool(os.environ.get(env_name))

    def _get_limiter(self, provider: str, env_name: str) -> RateLimiter:
        """Lazily construct (and cache) a rate limiter for one (provider, key) pair."""
        cache_key = (provider, env_name)
        if cache_key not in self._limiters:
            self._limiters[cache_key] = RateLimiter(self._providers[provider].rpm_budget)
        return self._limiters[cache_key]

    def _get_client(self, provider: str, api_key_env: str | None = None) -> openai.OpenAI:
        """Lazily construct (and cache) the OpenAI-compatible client for one (provider, key) pair.

        Raises:
            ProviderUnavailableError: If the resolved API key env var is unset.
        """
        env_name = self._resolve_api_key_env(provider, api_key_env)
        cache_key = (provider, env_name)
        if cache_key in self._clients:
            return self._clients[cache_key]

        cfg = self._providers[provider]
        api_key = os.environ.get(env_name)
        if not api_key:
            raise ProviderUnavailableError(provider, api_key_env)

        client = openai.OpenAI(api_key=api_key, base_url=cfg.base_url, timeout=REQUEST_TIMEOUT_SECONDS)
        self._clients[cache_key] = client
        return client

    def list_model_ids(self, provider: str, api_key_env: str | None = None) -> set[str]:
        """Fetch the set of model IDs currently served by a provider's catalog.

        Raises:
            ProviderUnavailableError: If the resolved API key env var is unset.
        """
        client = self._get_client(provider, api_key_env)
        response = client.models.list()
        return {item.id for item in response.data}

    def chat_completion(
        self,
        provider: str,
        model: str,
        messages: list[dict[str, str]],
        priority: str = "interactive",
        on_token: Callable[[str], None] | None = None,
        api_key_env: str | None = None,
        **kwargs: Any,
    ) -> str:
        """Run a streamed chat completion against one provider's model, with retry/backoff.

        Streaming (rather than waiting for the full completion) serves two
        purposes: on_token can be used to surface live token-by-token
        progress, and the client's read timeout becomes "max seconds between
        chunks" instead of "max seconds for the whole response" -- a
        reasoning model that's slow but still producing tokens is never
        killed, only a genuinely stalled connection is.

        Args:
            provider: Provider name (must be declared in models.yaml's providers:).
            model: Model ID on that provider's catalog.
            messages: OpenAI-format chat messages.
            priority: "interactive" for a fresh user request, "background" for
                a self-heal retry -- passed through to this (provider, key)
                pair's rate-limiter priority queue.
            on_token: Optional callback invoked with each content fragment as
                it streams in.
            api_key_env: Optional override naming a different env var than
                the provider's default -- for a candidate using its own
                per-model key.
            **kwargs: Extra OpenAI chat-completion parameters.

        Returns:
            The full assembled response content string.

        Raises:
            ProviderUnavailableError: If the resolved API key is unset.
            ModelUnavailableError: If the model returns 404/410, or 403 (a
                model can be listed in /v1/models yet still be gated behind
                separate access approval -- NVIDIA's catalog does this for
                some entries), on this provider.
            EmptyResponseError: If the stream ends with no content at all.
            openai.APIError: For any other unrecoverable API error.
        """
        client = self._get_client(provider, api_key_env)
        env_name = self._resolve_api_key_env(provider, api_key_env)
        limiter = self._get_limiter(provider, env_name)

        last_error: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            limiter.acquire(priority=priority)
            try:
                stream = client.chat.completions.create(
                    model=model, messages=messages, stream=True, **kwargs
                )
                pieces: list[str] = []
                for chunk in stream:
                    if not chunk.choices:
                        continue
                    piece = chunk.choices[0].delta.content
                    if piece:
                        pieces.append(piece)
                        if on_token is not None:
                            on_token(piece)

                if not pieces:
                    raise EmptyResponseError(provider, model)
                return "".join(pieces)
            except (openai.NotFoundError, openai.PermissionDeniedError) as exc:
                raise ModelUnavailableError(provider, model) from exc
            except openai.APIError as exc:
                # Free-tier proxies (OpenRouter routing to an overloaded
                # upstream, etc.) surface capacity/transient failures under a
                # wide and inconsistently-shaped set of openai.APIError
                # subclasses (RateLimitError, InternalServerError,
                # APITimeoutError, and others not worth enumerating one at a
                # time as new phrasings show up). 404/403 are handled above
                # as permanent; everything else in this hierarchy is treated
                # as transient: back off and retry the SAME candidate first,
                # then let calling.py's matching except clause advance to the
                # role's next candidate once retries are exhausted.
                last_error = exc
                delay = min(BASE_BACKOFF_SECONDS * (2 ** (attempt - 1)), MAX_BACKOFF_SECONDS)
                delay += random.uniform(0, delay * 0.25)
                logger.warning(
                    "%s from provider=%s model=%s attempt=%d/%d, backing off %.1fs",
                    type(exc).__name__,
                    provider,
                    model,
                    attempt,
                    MAX_RETRIES,
                    delay,
                )
                time.sleep(delay)

        assert last_error is not None
        raise last_error
