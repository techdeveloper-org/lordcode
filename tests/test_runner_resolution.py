"""Issue #17: a test runner must be startable, and a missing one must not heal.

Both halves were found in the first live run of the wired pipeline, not by
inspection. Maven was installed and on PATH, and every Java run had still been
failing its tests: `subprocess.run(["mvn", ...], shell=False)` raises WinError 2
because Maven's Windows entry point is `mvn.cmd` and CreateProcess will not
start a batch file from a bare name. Self-heal then spent three
diagnose-and-regenerate attempts on an environment fault no code change could
fix -- real model calls, minutes of pacing each.

Windows-safe: ASCII only.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

from vishwakarma.engine import executor, self_heal
from vishwakarma.engine.executor import ExecutionResult, resolve_runner, run_tests
from vishwakarma.engine.generate import FileSpec
from vishwakarma.languages import available_languages, get_adapter


class TestResolveRunner:
    def test_a_runner_on_path_resolves_to_a_real_file(self):
        """The point of the fix: the resolved name is what CreateProcess needs,
        which on Windows is the .cmd and not the bare stem."""
        resolved = resolve_runner("python")
        assert resolved is not None
        assert Path(resolved).is_file()

    def test_an_absent_runner_resolves_to_none(self):
        assert resolve_runner("definitely-not-a-real-runner-xyz") is None

    def test_an_absolute_path_is_returned_unchanged(self):
        """The Python adapter passes sys.executable, which must not be
        re-resolved into something else."""
        assert resolve_runner(sys.executable) == sys.executable

    def test_an_absolute_path_that_does_not_exist_is_none(self):
        assert resolve_runner(str(Path(sys.executable).parent / "nope.exe")) is None

    @pytest.mark.parametrize("language", sorted(available_languages()))
    def test_every_adapter_s_runner_is_startable_when_installed(self, language, tmp_path):
        """The regression guard. A runner that is absent on this machine is
        skipped rather than failed -- the assertion is about resolution, not
        about which toolchains happen to be installed here."""
        program = get_adapter(language).test_command(tmp_path)[0]
        if shutil.which(program) is None and not Path(program).is_absolute():
            pytest.skip(f"{program} is not installed on this machine")
        resolved = resolve_runner(program)
        assert resolved is not None, f"{language}: {program} is on PATH but did not resolve"
        assert Path(resolved).is_file()


class TestRunTests:
    def test_a_missing_runner_is_reported_as_such_not_as_a_test_failure(
        self, tmp_path, monkeypatch
    ):
        class Absent:
            def test_command(self, workdir):
                return ["definitely-not-a-real-runner-xyz", "test"]

        monkeypatch.setattr(executor, "get_adapter", lambda language: Absent())
        result = run_tests(tmp_path, "python")

        assert result.passed is False
        assert result.runner_missing is True
        assert "not found on PATH" in result.stderr

    def test_the_message_says_regeneration_cannot_help(self, tmp_path, monkeypatch):
        """A caller reading this should not go looking for a code fix."""

        class Absent:
            def test_command(self, workdir):
                return ["definitely-not-a-real-runner-xyz", "test"]

        monkeypatch.setattr(executor, "get_adapter", lambda language: Absent())
        assert "regeneration" in run_tests(tmp_path, "python").stderr

    def test_a_genuine_test_failure_is_not_flagged_as_a_missing_runner(self, tmp_path):
        """The distinction has to cut both ways or it is useless."""
        (tmp_path / "test_fails.py").write_text("def test_x():\n    assert False\n", encoding="utf-8")
        result = run_tests(tmp_path, "python")

        assert result.passed is False
        assert result.runner_missing is False

    def test_a_passing_suite_still_passes(self, tmp_path):
        (tmp_path / "test_ok.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
        result = run_tests(tmp_path, "python")

        assert result.passed is True
        assert result.runner_missing is False


class TestSelfHealRefusesAnEnvironmentFault:
    def _files(self):
        return [FileSpec(path="app.py", content="pass")]

    def test_no_heal_attempt_is_made(self, tmp_path, monkeypatch):
        """The defect: three attempts against an unchanged environment."""
        called = []
        monkeypatch.setattr(self_heal, "_diagnose", lambda *a, **k: called.append(1))

        result = self_heal.heal(
            "task",
            "java",
            tmp_path,
            self._files(),
            ExecutionResult(
                passed=False, stdout="", stderr="runner gone", returncode=-1, runner_missing=True
            ),
            router=None,
            client=None,
            max_attempts=3,
            timeout_seconds=300,
        )

        assert called == []
        assert result.passed is False
        assert len(result.attempts) == 1

    def test_the_refusal_is_reported_rather_than_silent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(self_heal, "_diagnose", lambda *a, **k: None)
        events = []

        self_heal.heal(
            "task",
            "java",
            tmp_path,
            self._files(),
            ExecutionResult(
                passed=False, stdout="", stderr="runner gone", returncode=-1, runner_missing=True
            ),
            router=None,
            client=None,
            max_attempts=3,
            timeout_seconds=300,
            on_event=events.append,
        )

        refusals = [event for event in events if event.get("type") == "heal_refused"]
        assert len(refusals) == 1
        assert "no code change can fix" in refusals[0]["reason"]

    def test_the_original_files_are_returned_untouched(self, tmp_path, monkeypatch):
        monkeypatch.setattr(self_heal, "_diagnose", lambda *a, **k: None)
        files = self._files()

        result = self_heal.heal(
            "task",
            "java",
            tmp_path,
            files,
            ExecutionResult(
                passed=False, stdout="", stderr="runner gone", returncode=-1, runner_missing=True
            ),
            router=None,
            client=None,
            max_attempts=3,
            timeout_seconds=300,
        )

        assert result.final_files == files

    def test_a_normal_failure_still_heals(self, tmp_path, monkeypatch):
        """Guard against over-correcting: an ordinary test failure must still
        reach the loop."""
        called = []

        def fake_diagnose(*args, **kwargs):
            called.append(1)
            raise RuntimeError("stop here, the loop was entered")

        monkeypatch.setattr(self_heal, "_diagnose", fake_diagnose)

        with pytest.raises(RuntimeError, match="loop was entered"):
            self_heal.heal(
                "task",
                "python",
                tmp_path,
                self._files(),
                ExecutionResult(passed=False, stdout="", stderr="assert failed", returncode=1),
                router=None,
                client=None,
                max_attempts=3,
                timeout_seconds=300,
            )

        assert called == [1]
