"""Regression test for executor.py's cwd/path handling.

A prior bug passed workdir's own path as BOTH subprocess.run's cwd AND the
test command's target argument, making pytest look for a nested
"<workdir>/<workdir>" directory that never existed -- every generated
program failed its tests regardless of whether the code was actually
correct. This runs the real pytest subprocess (no mocking) against a
trivial known-good file to catch that regression directly.
"""

from __future__ import annotations

from vishwakarma.engine.executor import run_tests, write_files
from vishwakarma.engine.generate import FileSpec


def test_run_tests_passes_for_correct_python_code(tmp_path):
    files = [
        FileSpec(path="adder.py", content="def add(a, b):\n    return a + b\n"),
        FileSpec(
            path="test_adder.py",
            content="from adder import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        ),
    ]
    write_files(tmp_path, files)

    result = run_tests(tmp_path, "python")

    assert result.passed is True, result.stderr


def test_run_tests_fails_for_incorrect_python_code(tmp_path):
    files = [
        FileSpec(path="adder.py", content="def add(a, b):\n    return a - b\n"),
        FileSpec(
            path="test_adder.py",
            content="from adder import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        ),
    ]
    write_files(tmp_path, files)

    result = run_tests(tmp_path, "python")

    assert result.passed is False
    assert "file or directory not found" not in result.stderr
