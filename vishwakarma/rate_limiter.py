"""Shared token-bucket rate limiter with a 2-tier interactive/background priority queue.

NVIDIA's free NIM tier enforces one physical requests-per-minute budget per API
key, shared across every model call. A single limiter instance models that
reality; a small priority rule on top ensures a burst of self-heal retries
("background") can never make a fresh CLI/web request ("interactive") wait
behind them.
"""

from __future__ import annotations

import threading
import time

Priority = str


class RateLimiter:
    """Token bucket sized to the NIM free-tier RPM budget, with priority admission."""

    def __init__(self, rpm_budget: int):
        """Create a limiter refilling at rpm_budget tokens per 60 seconds.

        Args:
            rpm_budget: Requests-per-minute ceiling for the shared API key.
        """
        self._capacity = float(rpm_budget)
        self._tokens = float(rpm_budget)
        self._refill_rate_per_second = rpm_budget / 60.0
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._interactive_waiting = 0

    def acquire(self, priority: Priority = "interactive") -> None:
        """Block until a token is available for this priority tier.

        Args:
            priority: "interactive" for a fresh user request (always admitted
                ahead of background work), or "background" for a self-heal
                retry, which waits while any interactive request is queued.
        """
        with self._condition:
            if priority == "interactive":
                self._interactive_waiting += 1
            try:
                while True:
                    self._refill_locked()
                    admitted = self._tokens >= 1.0 and (
                        priority == "interactive" or self._interactive_waiting == 0
                    )
                    if admitted:
                        self._tokens -= 1.0
                        return
                    self._condition.wait(timeout=0.1)
            finally:
                if priority == "interactive":
                    self._interactive_waiting -= 1
                    self._condition.notify_all()

    def _refill_locked(self) -> None:
        """Add tokens for elapsed time. Caller must hold self._condition."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        if elapsed > 0:
            self._tokens = min(self._capacity, self._tokens + elapsed * self._refill_rate_per_second)
            self._last_refill = now
