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

    Takes the LAST closing tag, not the first. The two are identical for a
    single well-formed trace and differ on repeated or nested ones, where
    first-match leaves a whole second trace embedded in what it calls "the
    answer". That matters now that this guards the two task classifiers
    (#53), because both parse by substring: a surviving trace containing the
    word "complex" makes classify_complexity return "complex" regardless of
    what the model concluded, which is the exact inversion that fix removed.

    The docstring promised last-match and the implementation used `.search()`,
    which finds the first (#58). Fixed here in the direction the docstring
    already specified, rather than by rewriting the contract to match the code.

    Accepted cost, checked rather than assumed: a response whose real answer
    legitimately contains the literal "</think>" is truncated at that point.
    `generate.py` does not import this function, so the coder's JSON path --
    the one place large verbatim content flows -- is untouched.

    Args:
        text: The raw reasoning-model response.

    Returns:
        Everything after the last </think> tag, or the full stripped text
        if no such tag is present.
    """
    matches = list(THINK_CLOSE_TAG.finditer(text))
    if matches:
        return text[matches[-1].end():].strip()
    return text.strip()
