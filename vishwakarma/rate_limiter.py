"""Shared rate limiter: a requests-per-minute bucket AND a tokens-per-minute
bucket, behind one 2-tier interactive/background priority queue.

Groq's free tier enforces two separate physical ceilings per API key, shared
across every model call: roughly 30 requests per minute and roughly 6000
tokens per minute (see models.yaml). Only the first was modelled here before;
the second is by far the more binding of the two. At the coder role's
max_tokens of 8000 a SINGLE call already exceeds the whole per-minute token
ceiling, so a limiter that counts only requests admits work the provider will
certainly reject with a 429.

Both buckets are checked before admission, so a caller is held until the
request budget AND the estimated token cost are simultaneously affordable. A
provider with no published token ceiling (a local Ollama, say) passes
tpm_budget=None and the token bucket is disabled for it.

Priority: a burst of self-heal retries ("background") can never make a fresh
CLI/web request ("interactive") wait behind it.
"""

from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger(__name__)

Priority = str

_WAIT_POLL_SECONDS = 0.1


class RateLimiter:
    """Paired RPM + TPM token buckets with priority admission."""

    def __init__(self, rpm_budget: int, tpm_budget: int | None = None):
        """Create a limiter refilling both buckets continuously.

        Args:
            rpm_budget: Requests-per-minute ceiling for the shared API key.
            tpm_budget: Tokens-per-minute ceiling for the same key, or None
                for a provider that publishes no token ceiling (the token
                bucket is then disabled and only requests are limited).
        """
        self._capacity = float(rpm_budget)
        self._tokens = float(rpm_budget)
        self._refill_rate_per_second = rpm_budget / 60.0

        self._token_capacity = float(tpm_budget) if tpm_budget else None
        self._token_tokens = float(tpm_budget) if tpm_budget else 0.0
        self._token_refill_rate_per_second = (tpm_budget / 60.0) if tpm_budget else 0.0

        self._last_refill = time.monotonic()
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._interactive_waiting = 0

    @property
    def tpm_budget(self) -> int | None:
        """The token ceiling this limiter enforces, or None if disabled."""
        return int(self._token_capacity) if self._token_capacity else None

    def acquire(self, priority: Priority = "interactive", estimated_tokens: int = 0) -> None:
        """Block until both budgets can afford this call at this priority.

        Args:
            priority: "interactive" for a fresh user request (always admitted
                ahead of background work), or "background" for a self-heal
                retry, which waits while any interactive request is queued.
            estimated_tokens: Estimated total token cost of the call (prompt
                plus requested completion). Ignored when the provider has no
                token ceiling. A cost exceeding the whole per-minute ceiling
                cannot be made affordable by waiting, so it is clamped to the
                full bucket rather than deadlocking -- see _affordable_locked.
        """
        with self._condition:
            if priority == "interactive":
                self._interactive_waiting += 1
            try:
                while True:
                    self._refill_locked()
                    affordable, token_cost = self._affordable_locked(estimated_tokens)
                    admitted = (
                        self._tokens >= 1.0
                        and affordable
                        and (priority == "interactive" or self._interactive_waiting == 0)
                    )
                    if admitted:
                        self._tokens -= 1.0
                        self._token_tokens -= token_cost
                        return
                    self._condition.wait(timeout=_WAIT_POLL_SECONDS)
            finally:
                if priority == "interactive":
                    self._interactive_waiting -= 1
                    self._condition.notify_all()

    def _affordable_locked(self, estimated_tokens: int) -> tuple[bool, float]:
        """Decide whether estimated_tokens fits the token bucket right now.

        Caller must hold self._condition.

        Returns:
            An (affordable, cost_to_deduct) pair. When the token bucket is
            disabled the call is always affordable at zero cost.

        A single call can legitimately cost more than the entire per-minute
        ceiling (the coder role requests up to 8000 tokens against a ~6000
        TPM budget). Waiting can never make that affordable, so such a call
        is admitted once the bucket is full and charged the full capacity:
        the provider will throttle it across minutes regardless, and M0.2's
        429 handling is what absorbs that. Refusing to admit it instead would
        hang the run forever.
        """
        if self._token_capacity is None:
            return True, 0.0
        cost = float(estimated_tokens)
        if cost > self._token_capacity:
            logger.warning(
                "estimated cost %d tokens exceeds the whole %d TPM ceiling; "
                "admitting at full budget -- this call will be throttled across minutes",
                estimated_tokens,
                int(self._token_capacity),
            )
            return self._token_tokens >= self._token_capacity, self._token_capacity
        return self._token_tokens >= cost, cost

    def _refill_locked(self) -> None:
        """Add tokens to both buckets for elapsed time. Caller must hold self._condition."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        if elapsed > 0:
            self._tokens = min(self._capacity, self._tokens + elapsed * self._refill_rate_per_second)
            if self._token_capacity is not None:
                self._token_tokens = min(
                    self._token_capacity,
                    self._token_tokens + elapsed * self._token_refill_rate_per_second,
                )
            self._last_refill = now
