"""Unit tests for the shared token-bucket rate limiter's priority admission."""

from __future__ import annotations

import threading
import time

import pytest

from vishwakarma.rate_limiter import RateLimiter


def test_acquire_consumes_one_token():
    limiter = RateLimiter(rpm_budget=60)
    tokens_before = limiter._tokens
    limiter.acquire(priority="interactive")
    assert limiter._tokens == pytest.approx(tokens_before - 1, abs=0.5)


def test_interactive_never_starves_behind_background():
    limiter = RateLimiter(rpm_budget=60)
    with limiter._condition:
        limiter._tokens = 0.0

    order: list[str] = []
    order_lock = threading.Lock()
    background_waiting = threading.Event()
    interactive_waiting = threading.Event()

    def background_worker() -> None:
        background_waiting.set()
        limiter.acquire(priority="background")
        with order_lock:
            order.append("background")

    def interactive_worker() -> None:
        interactive_waiting.wait()
        limiter.acquire(priority="interactive")
        with order_lock:
            order.append("interactive")

    background_thread = threading.Thread(target=background_worker)
    interactive_thread = threading.Thread(target=interactive_worker)

    background_thread.start()
    background_waiting.wait(timeout=1)
    time.sleep(0.05)

    interactive_thread.start()
    interactive_waiting.set()
    time.sleep(0.2)

    with limiter._condition:
        limiter._tokens = 5.0
        limiter._condition.notify_all()

    background_thread.join(timeout=2)
    interactive_thread.join(timeout=2)

    assert order[0] == "interactive"


def test_tpm_bucket_disabled_when_no_budget_given():
    """A provider with no published token ceiling is request-limited only."""
    limiter = RateLimiter(rpm_budget=60)
    assert limiter.tpm_budget is None
    limiter.acquire(priority="interactive", estimated_tokens=10_000_000)


def test_tpm_bucket_consumes_estimated_tokens():
    limiter = RateLimiter(rpm_budget=60, tpm_budget=6000)
    assert limiter.tpm_budget == 6000
    limiter.acquire(priority="interactive", estimated_tokens=2000)
    assert limiter._token_tokens == pytest.approx(4000, abs=50)


def test_tpm_bucket_holds_a_call_it_cannot_afford_yet():
    """A call is held until the token bucket has refilled enough for it."""
    limiter = RateLimiter(rpm_budget=600, tpm_budget=6000)
    with limiter._condition:
        limiter._token_tokens = 0.0

    admitted = threading.Event()

    def worker() -> None:
        limiter.acquire(priority="interactive", estimated_tokens=500)
        admitted.set()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    assert not admitted.wait(timeout=0.3), "admitted despite an empty token bucket"

    with limiter._condition:
        limiter._token_tokens = 6000.0
        limiter._condition.notify_all()

    assert admitted.wait(timeout=2.0), "never admitted after the token bucket refilled"
    thread.join(timeout=1)


def test_call_costing_more_than_the_whole_ceiling_is_admitted_not_deadlocked():
    """MAX_CODER_TOKENS (8000) exceeds the real 6000 TPM ceiling.

    Waiting can never make such a call affordable, so it must be admitted
    once the bucket is full rather than hanging the run forever.
    """
    limiter = RateLimiter(rpm_budget=60, tpm_budget=6000)
    limiter.acquire(priority="interactive", estimated_tokens=8000)
    assert limiter._token_tokens == pytest.approx(0.0, abs=50)
