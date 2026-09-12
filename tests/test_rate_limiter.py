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
