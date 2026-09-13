"""kgf-context: what text to send, and what was left out.

Read-only. Assembling context reads markdown and counts tokens; no model call.

This server **recomputes the closure** from the agent id rather than accepting
one from the caller, and that is a deliberate mitigation rather than
duplicated work. Four stdio servers share no session state, so a compose's
intermediate values travel through the caller -- which is an LLM. A tampered
skill list is therefore ignored here, because this server derives its own.

What it cannot detect is a tampered AGENT id: that is simply a different valid
request, and no amount of recomputation distinguishes "the selector chose this"
from "something else asked for this". The fingerprint in every response, and
the correlation id in every fragment, are what let a caller notice a compose
that has been spliced together from different runs.

The ledger is not decoration. A context block that cannot say what it left out
is impossible to debug when a model ignores a rule -- the first question is
always whether the rule was actually sent.
"""

from __future__ import annotations

from pathlib import Path

from kgf import ids, manifest as manifest_module
from kgf.closure import build_closure
from kgf.context import DEFAULT_TOKEN_BUDGET, Intent, assemble_context
from kgf.documents import parse_document
from kgf.mcp.base import READ_ONLY, ServerContext, annotations, make_server, start
from kgf.mcp.responses import envelope, tool_handler

mcp = make_server(
    "kgf-context",
    instructions=(
        "Assemble budgeted prompt context for an agent's skill closure, with a ledger "
        "of every section included and dropped, and list one document's sections. "
        "No model call."
    ),
)

_context: ServerContext | None = None

MAX_BUDGET = 32_000
"""Ceiling on a requested token budget.

Not a guess: the response cap is 64,000 bytes, and assembled context is the one
payload here that scales with a caller's argument. A budget above this could
produce a response the envelope has to refuse, which would waste the whole
assembly -- so the budget is clamped before the work rather than after.
"""


def _ctx() -> ServerContext:
    """The process's resolved context, built at launch by start()."""
    global _context
    if _context is None:
        _context = ServerContext()
    return _context


def _build(settings_file: Path | None = None) -> ServerContext:
    """Factory for start(), so a launch failure happens before serving."""
    global _context
    _context = ServerContext(settings_file)
    return _context


@mcp.tool(annotations=annotations(**READ_ONLY))
@tool_handler
def kgf_context(
    agent: str,
    intent: str = Intent.IMPLEMENT.value,
    budget_tokens: int = DEFAULT_TOKEN_BUDGET,
    task: str = "",
    include_text: bool = True,
    correlation_id: str = "",
) -> dict:
    """Assemble budgeted context for one agent's closure.

    Args:
        agent: Agent id or slug. Its closure is RECOMPUTED here rather than
            accepted from the caller, so a tampered skill list is ignored.
        intent: implement | design | review. Decides which sections earn their
            tokens: code-writing needs the rules that constrain output, review
            needs the prohibitions.
        budget_tokens: Token ceiling, clamped to MAX_BUDGET.
        task: Recorded in the manifest fragment for replay. Does not affect
            assembly, which is driven by the closure and the intent.
        include_text: Return the assembled text. False returns the ledger only,
            which is what a caller wants when checking what WOULD be sent.
        correlation_id: Ties this call's fragment and logs to one compose.
    """
    context = _ctx()
    closure = build_closure(context.graph, agent)
    if closure is None:
        raise KeyError(f"no agent matching {agent!r}")

    resolved_intent = Intent(intent) if intent in {item.value for item in Intent} else Intent.IMPLEMENT
    budget = min(max(budget_tokens, 1), MAX_BUDGET)

    assembled = assemble_context(
        context.graph, context.source, closure, intent=resolved_intent, budget_tokens=budget
    )

    data = {
        "agent": closure.agent,
        "intent": resolved_intent.value,
        "budget_tokens": assembled.budget_tokens,
        "assembled_context_tokens": assembled.assembled_context_tokens,
        "within_budget": assembled.within_budget,
        "closure_skills": list(closure.all_skills),
        "included": [
            {
                "entity": item.entity,
                "kind": item.kind,
                "heading": item.heading,
                "tokens": item.tokens,
            }
            for item in assembled.included
        ],
        "dropped": [
            {"entity": item.entity, "heading": item.heading, "reason": getattr(item, "reason", "")}
            for item in assembled.dropped
        ],
        "defects": list(assembled.defects),
    }
    if include_text:
        data["text"] = assembled.text

    fragment = manifest_module.build(
        task,
        context.source,
        None,
        closure,
        assembled,
        intent=resolved_intent.value,
        budget_tokens=budget,
        forced_agent=True,
        correlation_id=correlation_id,
    )
    return envelope(
        "kgf_context",
        data,
        library_version=context.library_version,
        fingerprint=context.fingerprint(),
        correlation_id=correlation_id,
        manifest_fragment=fragment.to_dict(),
    )


@mcp.tool(annotations=annotations(**READ_ONLY))
@tool_handler
def kgf_sections(entity: str, correlation_id: str = "") -> dict:
    """List one document's section headings, without their bodies.

    Headings and token counts only. A caller deciding which sections are worth
    a budget should not have to pay for every body to find out -- which is the
    same reasoning the 800-char head cut got wrong by sending the start of one
    document regardless of what was in it.

    Args:
        entity: An agent or skill id or slug.
        correlation_id: Ties this call's logs to one compose.
    """
    context = _ctx()
    record = context.graph.agent(entity) or context.graph.skill(entity)
    if record is None:
        raise KeyError(f"no agent or skill matching {entity!r}")

    is_agent = context.graph.agent(entity) is not None
    slug = ids.slug_of(record.id)
    path = (
        context.source.agents_dir / slug / "agent.md"
        if is_agent
        else context.source.skills_dir / slug / "SKILL.md"
    )
    document = parse_document(context.source, path)

    return envelope(
        "kgf_sections",
        {
            "entity": record.id,
            "kind": "agent" if is_agent else "skill",
            "path": str(path),
            "error": document.error,
            "frontmatter_keys": sorted(document.frontmatter),
            "sections": [
                {"heading": section.title, "key": section.key, "level": section.level, "chars": len(section.body)}
                for section in document.sections
            ],
        },
        library_version=context.library_version,
        fingerprint=context.fingerprint(),
        correlation_id=correlation_id,
    )


if __name__ == "__main__":
    start(_build, mcp)
