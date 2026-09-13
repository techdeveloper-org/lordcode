"""Structural guard against the join-before-drain deadlock (issue #2 item 4).

agent_runtime.py documents why a spawned process's result queue must be
drained BEFORE the process is joined: the child blocks in its Queue feeder
thread once the OS pipe buffer fills, while the parent blocks in join()
waiting for a child that cannot exit until somebody drains. Twenty call sites
had the order inverted.

A runtime test cannot catch this reliably -- the deadlock only appears once a
payload outgrows the pipe buffer, which is exactly why a green suite hid it
for so long. So the guard is structural: walk every function body in the
engine with ast and assert no `.join()` statement is followed by a statement
that reads a result. Parsing with ast rather than grepping also means prose in
docstrings describing the bug cannot trip the check.
"""

from __future__ import annotations

import ast
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent.parent / "vishwakarma" / "engine"


def _is_join_call(node: ast.stmt) -> bool:
    """True if the statement is a bare `<something>.join()` expression."""
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and node.value.func.attr == "join"
    )


def _reads_a_result(node: ast.stmt) -> bool:
    """True if the statement calls await_result / _await_result anywhere in it."""
    return any(
        isinstance(inner, ast.Call)
        and isinstance(inner.func, ast.Attribute)
        and inner.func.attr in {"await_result", "_await_result"}
        for inner in ast.walk(node)
    )


def _offending_sites(tree: ast.AST) -> list[int]:
    """Line numbers where a join() statement is followed by a result read.

    Checks consecutive statements within every statement list in the module,
    including loop and try bodies, since the inverted order appeared in both
    straight-line code and inside `for` loops.
    """
    offenders: list[int] = []
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            statements = getattr(node, field, None)
            if not isinstance(statements, list):
                continue
            for current, following in zip(statements, statements[1:]):
                if _is_join_call(current) and _reads_a_result(following):
                    offenders.append(current.lineno)
    return offenders


def test_no_engine_module_joins_before_draining():
    failures: list[str] = []
    for path in sorted(ENGINE_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for lineno in _offending_sites(tree):
            failures.append(f"{path.name}:{lineno}")

    assert not failures, (
        "process.join() precedes a result read at: "
        + ", ".join(failures)
        + " -- drain the result queue first (use AgentCoordinator.run_agent), "
        "see agent_runtime.run_agents_parallel's docstring"
    )


def test_the_guard_actually_detects_the_bug():
    """A guard that cannot fail is not a guard."""
    bad = ast.parse(
        "def f(coordinator, process, agent_id):\n"
        "    process.join()\n"
        "    return coordinator.await_result(agent_id)\n"
    )
    assert _offending_sites(bad) == [2]

    good = ast.parse(
        "def f(coordinator, process, agent_id):\n"
        "    result = coordinator.await_result(agent_id)\n"
        "    process.join()\n"
        "    return result\n"
    )
    assert _offending_sites(good) == []


def test_guard_ignores_prose_describing_the_bug():
    """agent_runtime's docstrings discuss join() and await_result at length."""
    prose = ast.parse(
        'def f():\n'
        '    """Do not call process.join() before await_result(agent_id)."""\n'
        '    return None\n'
    )
    assert _offending_sites(prose) == []
