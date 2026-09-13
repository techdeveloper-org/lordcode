"""One place that decides whether a persona may be applied to a model role.

Issue #2 item 3. Every persona in claude-global-library declares no `role:`
field, and the loader used to default that to "primary_coder". The effect was
not a missing feature but an active mis-application: the roughly twenty
reviewer, auditor and consensus personas were injected as the persona that
WRITES code, which is the opposite of their purpose.

SubAgent.role is now None when undeclared (see plugins.SubAgent), and this
module is the single gate every call site consults. An undeclared role is
refused, loudly, rather than guessed.

Refusing is a deliberate interim regression: until a role classifier exists,
NO library persona is applied to any role. That is strictly better than
applying every one of them to the wrong role, and it is logged each time so
the gap is visible rather than silent.
"""

from __future__ import annotations

import logging

from vishwakarma.engine.calling import OnEvent, noop_event
from vishwakarma.plugins import SubAgent

logger = logging.getLogger(__name__)


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
