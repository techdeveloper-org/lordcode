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

RATE_LIMIT_WALL_CLOCK_SECONDS = 150.0
"""Total wall-clock ceiling on retrying ONE call that keeps returning 429.

A rate limit differs from every other transient failure in that retrying the
same candidate is the only correct response -- the next candidate shares the
same key, and therefore the same exhausted budget, so advancing to it merely
burns a fallback for nothing (see calling.py). But 'retry the same candidate'
without a bound is an infinite loop against a key that is out of quota for
the day, so the retry is bounded by wall clock rather than by attempt count:
the provider's own Retry-After may be tens of seconds, which a fixed small
attempt count would exhaust far too early."""

CHARS_PER_TOKEN_ESTIMATE = 4
"""Crude but adequate chars-to-tokens ratio for pre-flight budgeting.

The limiter needs a cost estimate BEFORE the call, and the only exact source
is the provider's own post-hoc usage report. Four characters per token is the
standard approximation for English prose and code; it is used solely to
decide admission order, never to report usage, so a modest error costs a
slightly early or late admission and nothing else."""
REQUEST_TIMEOUT_SECONDS = 30.0
"""Applied as httpx's connect/read/write timeout. Because every call streams
(see chat_completion), the 'read' timeout means max seconds BETWEEN CHUNKS,
not max total response time -- so a reasoning model that is slow but still
producing tokens is never killed, only a genuinely stalled connection is.

That inter-chunk reading is why 120s was far too loose: a provider emitting one
token every 119 seconds read as perfectly healthy, and since the router advances
only on exceptions and a slow stream raises none, such a call had no timeout, no
error and no failover -- it simply never returned (#56). 30s is still an order of
magnitude above any observed inter-chunk gap on a working provider.

It DOES bound time-to-first-byte, which is worth recording because the obvious
worry about the stream deadline planned in #56 is that a per-chunk check cannot
fire when no chunk ever arrives. Measured against a socket that accepts and then
stays silent: httpx.ReadTimeout at 4.6s against a 4s configured read timeout. So
a server that accepts and sends nothing is killed here, by the transport, and
only the "alive but crawling" case needs the throughput bound."""

TOTAL_RESPONSE_TIMEOUT_BASE_SECONDS = 60.0
TOTAL_RESPONSE_TIMEOUT_SECONDS_PER_TOKEN = 0.15
"""Together, bound TOTAL streamed response time -- the throughput floor #56
itself identifies as still missing after REQUEST_TIMEOUT_SECONDS above: a
provider that emits small chunks steadily, each well inside the 30s inter-chunk
gap, never trips that timeout and never raises, so the router never fails over
and an interactive caller waits indefinitely. #56 found this while evaluating a
1-3B local Ollama model swapping on constrained hardware -- alive, streaming,
unusably slow -- but it is not local-only: a remote provider under severe load,
or a proxy trickling bytes to hold a connection open, produces the same shape.

The ceiling scales with the call's own max_tokens (already available in
chat_completion's kwargs at every call site in this codebase, so no role needs
threading through separately) because a role's legitimate call duration varies
enormously with its completion budget: router_fast asks for 60 tokens,
primary_coder asks for up to 8000. GENEROUS AND UNVERIFIED -- these two numbers
are a conservative starting estimate, not a measured throughput floor (#56's
own text asks for exactly that measurement before landing option 2, the
minimum-throughput-floor refinement). ceiling = BASE + max_tokens * PER_TOKEN,
e.g. ~69s for router_fast (60 tokens), ~1260s (21min) for primary_coder (8000
tokens) -- bounded instead of the current unbounded hang, not yet tuned against
real observed throughput. Revisit both constants once real numbers exist."""


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


class ResponseStalledError(Exception):
    """Raised when a stream's TOTAL elapsed time exceeds its computed ceiling.

    Distinct from httpx's own read timeout (REQUEST_TIMEOUT_SECONDS above),
    which only bounds the gap BETWEEN chunks -- this bounds the whole call, for
    the "alive but crawling" case #56 describes, where chunks keep arriving
    just often enough that the inter-chunk timeout never fires. Treated as a
    candidate-level failure like EmptyResponseError/ModelUnavailableError (the
    router advances to the role's next candidate), but a stall means the
    candidate is UP, merely slow right now -- calling.py deliberately marks
    this transient (saw_transient=True) rather than joining the same permanent-
    demotion bucket as a genuinely withdrawn model, so a role recovers via
    restore_active_index if every candidate happens to stall in one session
    rather than getting ConfigError'd for the rest of the process.
    """

    def __init__(self, provider: str, model: str, elapsed_seconds: float, ceiling_seconds: float):
        self.provider = provider
        self.model = model
        self.elapsed_seconds = elapsed_seconds
        self.ceiling_seconds = ceiling_seconds
        super().__init__(
            f"Provider '{provider}' model '{model}' has been streaming for "
            f"{elapsed_seconds:.0f}s, past its {ceiling_seconds:.0f}s ceiling -- "
            f"the connection is alive but too slow to be usable; advancing to "
            f"the next candidate."
        )


class RateLimitExhaustedError(Exception):
    """Raised when one call kept returning 429 until its wall-clock bound ran out.

    Deliberately NOT an openai.APIError subclass, and deliberately distinct
    from the candidate-level failures above. calling.py treats those as
    "this candidate is broken, advance the router" -- which is exactly the
    wrong response to a rate limit, because every candidate for the role
    resolves to the same key and therefore the same exhausted budget.
    Advancing would spend the role's whole fallback chain on one throttled
    minute and then raise ConfigError as though the models had vanished.
    So this type propagates past calling.py untouched, leaving the router's
    active candidate exactly where it was.
    """

    def __init__(self, provider: str, model: str, elapsed_seconds: float, attempts: int):
        self.provider = provider
        self.model = model
        self.elapsed_seconds = elapsed_seconds
        self.attempts = attempts
        super().__init__(
            f"Provider '{provider}' rate-limited model '{model}' for "
            f"{elapsed_seconds:.0f}s across {attempts} attempt(s); giving up on this call. "
            f"The key's per-minute or per-day quota is exhausted -- retry later, "
            f"or add a second key/provider to spread the budget."
        )


def estimate_call_tokens(messages: list[dict[str, str]], max_tokens: int | None) -> int:
    """Estimate one call's total token cost for pre-flight rate limiting.

    Counts the prompt AND the requested completion, because a tokens-per-minute
    ceiling is charged on both and the completion is usually the larger half:
    the coder role sends a ~2000-token prompt and asks for up to 8000 back.

    Args:
        messages: OpenAI-format chat messages about to be sent.
        max_tokens: The call's requested completion ceiling, or None if the
            caller did not set one.

    Returns:
        Estimated total tokens, never negative.
    """
    prompt_chars = sum(len(str(message.get("content") or "")) for message in messages)
    prompt_tokens = prompt_chars // CHARS_PER_TOKEN_ESTIMATE
    return prompt_tokens + int(max_tokens or 0)


def _retry_after_seconds(exc: Exception) -> float | None:
    """Read a 429's Retry-After hint, in seconds, if the provider sent one.

    Groq returns it as a seconds value; the header is optional and other
    OpenAI-compatible providers may omit it or send an HTTP date, so anything
    not parseable as a positive number is reported as absent and the caller
    falls back to exponential backoff.
    """
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    raw = headers.get("retry-after") or headers.get("Retry-After")
    if raw is None:
        return None
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        return None
    return seconds if seconds > 0 else None


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
        """Whether this provider can be called: it has its key, or needs none.

        A provider declaring `api_key_required: false` is always available. A
        local Ollama has no key to set, and gating purely on a non-empty env
        var made it unselectable by construction -- `validate_startup` skips
        any candidate this refuses, so the one provider class that runs without
        spend could never be reached.

        Reachability is deliberately NOT checked here. A local runtime that is
        installed but not running would pass this and fail at call time, which
        is the same shape as a valid key whose provider is down: the router's
        fallback chain handles both, and a health probe on every availability
        question would cost a network round-trip per candidate per role.
        """
        provider_config = self._providers.get(provider)
        if provider_config is not None and not provider_config.api_key_required:
            return True
        env_name = self._resolve_api_key_env(provider, api_key_env)
        return bool(env_name) and bool(os.environ.get(env_name))

    def _get_limiter(self, provider: str, env_name: str) -> RateLimiter:
        """Lazily construct (and cache) a rate limiter for one (provider, key) pair.

        Keyed by (provider, key) rather than by provider alone because the
        physical budgets belong to the KEY: two candidates pointing at the
        same provider through different key env vars have genuinely separate
        quotas and must not share a bucket.
        """
        cache_key = (provider, env_name)
        if cache_key not in self._limiters:
            config = self._providers[provider]
            self._limiters[cache_key] = RateLimiter(config.rpm_budget, config.tpm_budget)
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
        api_key = os.environ.get(env_name) if env_name else None
        if not api_key:
            if not cfg.api_key_required:
                # The OpenAI SDK refuses to construct without a key, while a
                # keyless OpenAI-compatible endpoint (Ollama) ignores whatever
                # is sent. A placeholder satisfies the client and is never a
                # credential, so it cannot leak one.
                api_key = "not-required"
            else:
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
        # No SDK retries on a liveness check. This asks "is the provider there",
        # and the answer does not change on retry -- but the SDK's default of 2
        # adds two more connect attempts plus backoff to every DEAD provider,
        # measured at 13.8s against 4.1s without them. The caller already treats
        # a failure here as "skip this candidate", never as fatal (#41), so a
        # single attempt carries exactly the information it uses (#57).
        response = client.with_options(max_retries=0).models.list()
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
            ResponseStalledError: If the stream's TOTAL elapsed time exceeds
                its max_tokens-derived ceiling -- the connection is alive and
                producing chunks (so REQUEST_TIMEOUT_SECONDS never fires) but
                too slowly to be usable.
            RateLimitExhaustedError: If the provider kept returning 429 for
                RATE_LIMIT_WALL_CLOCK_SECONDS. Distinct from the errors above
                because it says nothing about this model's health -- the key's
                quota is spent, so advancing to another candidate would only
                waste the role's fallback chain.
            openai.APIError: For any other unrecoverable API error.
        """
        client = self._get_client(provider, api_key_env)
        env_name = self._resolve_api_key_env(provider, api_key_env)
        limiter = self._get_limiter(provider, env_name)
        estimated_tokens = estimate_call_tokens(messages, kwargs.get("max_tokens"))
        total_response_ceiling = TOTAL_RESPONSE_TIMEOUT_BASE_SECONDS + (
            (kwargs.get("max_tokens") or 0) * TOTAL_RESPONSE_TIMEOUT_SECONDS_PER_TOKEN
        )

        rate_limit_started: float | None = None
        rate_limit_attempts = 0
        last_error: Exception | None = None
        attempt = 0
        while attempt < MAX_RETRIES:
            attempt += 1
            limiter.acquire(priority=priority, estimated_tokens=estimated_tokens)
            try:
                stream = client.chat.completions.create(
                    model=model, messages=messages, stream=True, **kwargs
                )
                pieces: list[str] = []
                stream_started = time.monotonic()
                for chunk in stream:
                    if time.monotonic() - stream_started > total_response_ceiling:
                        raise ResponseStalledError(
                            provider, model, time.monotonic() - stream_started, total_response_ceiling
                        )
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
            except openai.RateLimitError as exc:
                # A 429 is the one transient failure that must NOT count
                # against MAX_RETRIES or advance the router: the next
                # candidate shares this key's exhausted budget, so the only
                # useful response is to wait on this same candidate. The
                # attempt counter is therefore rolled back and the loop is
                # bounded by wall clock instead -- see
                # RATE_LIMIT_WALL_CLOCK_SECONDS.
                now = time.monotonic()
                if rate_limit_started is None:
                    rate_limit_started = now
                rate_limit_attempts += 1
                elapsed = now - rate_limit_started
                if elapsed >= RATE_LIMIT_WALL_CLOCK_SECONDS:
                    raise RateLimitExhaustedError(
                        provider, model, elapsed, rate_limit_attempts
                    ) from exc

                attempt -= 1
                hinted = _retry_after_seconds(exc)
                if hinted is None:
                    hinted = min(
                        BASE_BACKOFF_SECONDS * (2 ** (rate_limit_attempts - 1)),
                        MAX_BACKOFF_SECONDS,
                    )
                remaining = RATE_LIMIT_WALL_CLOCK_SECONDS - elapsed
                delay = min(hinted, remaining)
                logger.warning(
                    "429 from provider=%s model=%s (rate-limit attempt %d, %.0fs elapsed of %.0fs); "
                    "waiting %.1fs and retrying the SAME candidate",
                    provider,
                    model,
                    rate_limit_attempts,
                    elapsed,
                    RATE_LIMIT_WALL_CLOCK_SECONDS,
                    delay,
                )
                time.sleep(delay)
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

        if last_error is None:
            # Reachable only if MAX_RETRIES is misconfigured to <= 0, in which
            # case the loop body never ran. A bare assert would strip under -O
            # and leave an implicit `return None` violating the -> str contract.
            raise RuntimeError(
                f"chat_completion made no attempt for provider={provider!r} model={model!r}: "
                f"MAX_RETRIES is {MAX_RETRIES}, which must be at least 1"
            )
        raise last_error
