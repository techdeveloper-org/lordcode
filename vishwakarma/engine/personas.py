"""The persona types, and the one place that decides where a persona applies.

Issue #2 item 3. Every persona in claude-global-library declares no `role:`
field, and the loader used to default that to "primary_coder". The effect was
not a missing feature but an active mis-application: the roughly twenty
reviewer, auditor and consensus personas were injected as the persona that
WRITES code, which is the opposite of their purpose.

SubAgent.role is None when undeclared, and this module is the single gate
every call site consults. An undeclared role is
refused, loudly, rather than guessed.

Refusing was a deliberate interim regression while no role classifier
existed: no library persona was applied to any role at all, which is strictly
better than applying every one of them to the wrong role. M6a lifted it --
kgf.roles now states a role for every agent, so a persona arrives with one
declared and this gate passes it through. The gate stays because the
alternative is trusting that every future persona source declares a role.

`SubAgent` lives here because M6b deleted plugins.py, which had defined it.
It is persona data, so this is where it belongs; nothing loads it from disk any
more, since selection and context assembly are kgf's job.

plugins.py's `Skill` was deliberately NOT kept. It carried a `prompt_addition`
fragment appended to the system prompt -- a second mechanism for injecting
library knowledge alongside the assembled context, and the weaker one, since
the fragment came from an 800-char head cut. Forcing a skill now puts it at the
front of the kgf closure, where it earns real context budget.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from vishwakarma.engine.calling import OnEvent, noop_event

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SubAgent:
    """A persona system prompt that can replace the default prompt for one role.

    role is None when the source file DECLARED no role, which is the case for
    every persona in claude-global-library: none of its 528 agent.md files
    carries a `role:` field. Defaulting that to "primary_coder" (as this did
    before issue #2) made an undeclared role indistinguishable from one
    explicitly set to the coder role, with the result that reviewer, auditor
    and consensus personas were injected as the persona that WRITES the code
    they exist to critique. A persona is now applied to a role only where the
    role is stated, so an undeclared one is refused rather than guessed.
    """

    name: str
    description: str
    role: str | None = None
    system_prompt: str = ""


def persona_for_role(
    subagent: SubAgent | None,
    role: str,
    on_event: OnEvent = noop_event,
) -> SubAgent | None:
    """Return subagent only if it explicitly declares this role.

    Args:
        subagent: The candidate persona, or None if none was selected.
        role: The model role about to be steered ("primary_coder",
            "reasoner", "router_fast", "fallback_long_context").
        on_event: Progress sink; receives a persona_refused event whenever a
            persona is declined, so the refusal appears in the CLI echo and
            the web UI activity log rather than passing unnoticed.

    Returns:
        The persona when its declared role matches, otherwise None.
    """
    if subagent is None:
        return None

    if subagent.role is None:
        logger.info(
            "persona %r declares no role; refusing to apply it to %s "
            "(see issue #2 -- a persona is never assigned a role by guess)",
            subagent.name,
            role,
        )
        on_event(
            {
                "type": "persona_refused",
                "persona": subagent.name,
                "requested_role": role,
                "reason": "no role declared",
            }
        )
        return None

    if subagent.role != role:
        logger.debug(
            "persona %r declares role %s; not applied to %s",
            subagent.name,
            subagent.role,
            role,
        )
        on_event(
            {
                "type": "persona_refused",
                "persona": subagent.name,
                "requested_role": role,
                "reason": f"declares role {subagent.role}",
            }
        )
        return None

    return subagent
