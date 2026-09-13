"""Enforce kgf's one-way dependency, rather than merely intending it.

kgf must import nothing from vishwakarma, nothing from claude-workflow-engine
and nothing from Claude Code. Living in the same repository as its consumer
makes the wrong import trivially easy to write and invisible in review -- the
module would work perfectly in every test, because the consumer is always
importable there.

So the check runs in a subprocess with the consumer package made
unimportable. If kgf ever reaches back, this fails immediately instead of at
the point somebody tries to extract kgf into its own repository.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
KGF_DIR = REPO_ROOT / "kgf"

FORBIDDEN_ROOTS = ("vishwakarma", "langgraph_engine", "claude_workflow_engine")

_SUBPROCESS_PROGRAM = """
import sys

class _Blocker:
    def __init__(self, blocked):
        self.blocked = blocked

    def find_module(self, name, path=None):
        return self.find_spec(name, path)

    def find_spec(self, name, path=None, target=None):
        root = name.split(".")[0]
        if root in self.blocked:
            raise ImportError("blocked by the kgf boundary test: " + name)
        return None

sys.meta_path.insert(0, _Blocker({blocked!r}))

import importlib
import pkgutil

import kgf

modules = ["kgf"]
for info in pkgutil.iter_modules(kgf.__path__, "kgf."):
    modules.append(info.name)

for name in modules:
    importlib.import_module(name)

print("OK " + str(len(modules)))
"""


def test_kgf_imports_cleanly_without_its_consumer_on_the_path():
    program = _SUBPROCESS_PROGRAM.format(blocked=set(FORBIDDEN_ROOTS))
    completed = subprocess.run(
        [sys.executable, "-c", program],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert completed.returncode == 0, (
        "kgf failed to import with its consumer blocked:\n"
        f"stdout: {completed.stdout}\nstderr: {completed.stderr}"
    )
    assert completed.stdout.startswith("OK ")


def test_no_kgf_module_names_a_forbidden_import_statically():
    """Belt to the subprocess test's braces.

    A lazily-imported dependency inside a rarely-taken branch would pass the
    runtime check while still coupling the package, so the import statements
    are also read directly.
    """
    offenders: list[str] = []
    for path in sorted(KGF_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                if name.split(".")[0] in FORBIDDEN_ROOTS:
                    offenders.append(f"{path.name}:{node.lineno} imports {name}")

    assert not offenders, "kgf must not import its consumer: " + "; ".join(offenders)


def test_the_boundary_check_actually_detects_a_violation(tmp_path):
    """A guard that cannot fail is not a guard."""
    module = tmp_path / "violating.py"
    module.write_text("from vishwakarma.router import Router\n", encoding="utf-8")

    tree = ast.parse(module.read_text(encoding="utf-8"))
    found = [
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and (node.module or "").split(".")[0] in FORBIDDEN_ROOTS
    ]
    assert found == ["vishwakarma.router"]
