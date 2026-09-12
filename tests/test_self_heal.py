"""Unit tests for the self-heal diagnose-then-fix loop, using a mocked LLM client.

No real API calls are made and no API keys are required -- run_tests and
write_files are also monkeypatched so no subprocess or filesystem test
execution happens either.
"""

from __future__ import annotations

import json

from vishwakarma.config import ModelConfig, RoleCandidate
from vishwakarma.engine import self_heal
from vishwakarma.engine.executor import ExecutionResult
from vishwakarma.engine.generate import FileSpec
from vishwakarma.router import Router


class FakeClient:
    """Returns a diagnosis on odd calls and a JSON fix on even calls."""

    def __init__(self):
        self.call_log: list[str] = []

    def chat_completion(
        self, provider: str, model: str, messages: list[dict], priority: str = "interactive", **kwargs
    ) -> str:
        self.call_log.append(f"{provider}/{model}")
        if len(self.call_log) % 2 == 1:
            return "Root cause: off-by-one error. Fix: adjust the return value."
        return json.dumps({"files": [{"path": "solution.py", "content": "def f():\n    return 1\n"}]})


def _models() -> ModelConfig:
    return ModelConfig(
        roles={
            "primary_coder": [RoleCandidate(provider="nvidia", model="coder")],
            "router_fast": [RoleCandidate(provider="nvidia", model="fast")],
            "reasoner": [RoleCandidate(provider="nvidia", model="reasoner")],
            "fallback_long_context": [RoleCandidate(provider="nvidia", model="fallback")],
        },
        max_heal_attempts=3,
        heal_timeout_seconds=300,
    )


def test_heal_succeeds_after_one_retry(tmp_path, monkeypatch):
    written_files: list[list[FileSpec]] = []

    def fake_write_files(workdir, files):
        written_files.append(files)

    results = [
        ExecutionResult(passed=False, stdout="", stderr="AssertionError: expected 1", returncode=1),
        ExecutionResult(passed=True, stdout="1 passed", stderr="", returncode=0),
    ]
    call_count = {"n": 0}

    def fake_run_tests(workdir, language):
        result = results[call_count["n"]]
        call_count["n"] += 1
        return result

    monkeypatch.setattr(self_heal, "write_files", fake_write_files)
    monkeypatch.setattr(self_heal, "run_tests", fake_run_tests)

    client = FakeClient()
    router = Router(_models(), client)
    initial_files = [FileSpec(path="solution.py", content="def f():\n    return 0\n")]
    initial_result = ExecutionResult(passed=False, stdout="", stderr="AssertionError: expected 1", returncode=1)

    result = self_heal.heal(
        "implement f() to return 1",
        "python",
        tmp_path,
        initial_files,
        initial_result,
        router,
        client,
        max_attempts=3,
        timeout_seconds=300,
    )

    assert result.passed is True
    assert result.final_files[0].content.strip() == "def f():\n    return 1"
    assert len(written_files) == 2


def test_heal_stops_at_max_attempts_when_never_passing(tmp_path, monkeypatch):
    monkeypatch.setattr(self_heal, "write_files", lambda workdir, files: None)
    always_fails = ExecutionResult(passed=False, stdout="", stderr="still broken", returncode=1)
    monkeypatch.setattr(self_heal, "run_tests", lambda workdir, language: always_fails)

    client = FakeClient()
    router = Router(_models(), client)
    initial_files = [FileSpec(path="solution.py", content="def f():\n    return 0\n")]

    result = self_heal.heal(
        "implement f() to return 1",
        "python",
        tmp_path,
        initial_files,
        always_fails,
        router,
        client,
        max_attempts=2,
        timeout_seconds=300,
    )

    assert result.passed is False
    assert len(result.attempts) <= 3


class _MalformedThenValidClient:
    """Diagnosis calls succeed; the first fix response is malformed JSON,
    the second is a valid fix -- live-discovered bug: a malformed fix
    response used to propagate as an unhandled GenerationError instead of
    being treated as a failed attempt."""

    def __init__(self):
        self.call_log: list[str] = []

    def chat_completion(self, provider, model, messages, priority="interactive", **kwargs):
        self.call_log.append(f"{provider}/{model}")
        call_number = len(self.call_log)
        if call_number % 2 == 1:
            return "Root cause: bug. Fix: do X."
        if call_number == 2:
            return "{not valid json"  # attempt 1's fix response is malformed
        return json.dumps({"files": [{"path": "solution.py", "content": "def f():\n    return 1\n"}]})


def test_heal_treats_malformed_fix_response_as_failed_attempt_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(self_heal, "write_files", lambda workdir, files: None)
    results = [ExecutionResult(passed=True, stdout="1 passed", stderr="", returncode=0)]

    def fake_run_tests(workdir, language):
        return results[0]

    monkeypatch.setattr(self_heal, "run_tests", fake_run_tests)

    client = _MalformedThenValidClient()
    router = Router(_models(), client)
    initial_files = [FileSpec(path="solution.py", content="def f():\n    return 0\n")]
    initial_result = ExecutionResult(passed=False, stdout="", stderr="AssertionError", returncode=1)
    events = []

    result = self_heal.heal(
        "implement f() to return 1",
        "python",
        tmp_path,
        initial_files,
        initial_result,
        router,
        client,
        max_attempts=3,
        timeout_seconds=300,
        on_event=events.append,
    )

    assert any(e["type"] == "heal_attempt_parse_failed" and e["attempt"] == 1 for e in events)
    assert result.passed is True
    assert result.final_files[0].content.strip() == "def f():\n    return 1"
