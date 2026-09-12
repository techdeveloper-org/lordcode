"""Shared helper for handling reasoning-model output."""

from __future__ import annotations

import re

THINK_CLOSE_TAG = re.compile(r"</think>", re.IGNORECASE)


def strip_reasoning_trace(text: str) -> str:
    """Return only the final answer from a reasoning model's response.

    DeepSeek-R1-style models may emit a leading <think>...</think> block.
    That trace is useful for the user to inspect but should never be fed
    back into a non-reasoning model (it wastes context and can confuse it),
    so downstream callers pass only what this function returns.

    Args:
        text: The raw reasoning-model response.

    Returns:
        Everything after the last </think> tag, or the full stripped text
        if no such tag is present.
    """
    match = THINK_CLOSE_TAG.search(text)
    if match:
        return text[match.end():].strip()
    return text.strip()
