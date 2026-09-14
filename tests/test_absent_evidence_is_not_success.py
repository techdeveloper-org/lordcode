"""Two regressions in the fixes that shipped hours before them (#66).

Both have the same root shape: a value meaning "cannot tell" was consumed as if
it meant "fine". The adapter docstrings said so explicitly and the callers did
it anyway, which is why these are pinned by name rather than left to review.

R0a -- `executed_test_count` returns None when the runner printed no count.
`if returncode == 0 and executed == 0` skips on None and falls through to
`passed = True`, so #59's lie came back through a second door.

R0b -- `failure_count` returns None for an unscoreable attempt. The heal loop's
`if attempt_count is None or best_count is None` then overwrote the champion
with the unmeasurable state AND made every later iteration take the same branch,
disabling #64's ratchet for the rest of the run.
"""

from __future__ import annotations

from pathlib import Path

from vishwakarma.engine import self_heal as heal_module
from vishwakarma.engine.executor import ExecutionResult, run_tests
from vishwakarma.engine.generate import FileSpec, GeneratedArtifact


class TestAnAbsentTestCountIsNotAPass:
    """R0a, constructed the way it is actually reachable."""

    def test_a_java_test_outside_the_maven_test_root_does_not_pass(self, tmp_path, monkeypatch):
        """The exact reachable path, not a synthetic one.

        `test_file_patterns()` matches `**/*Test.java` ANYWHERE -- deliberately,
        to catch a correctly-named class in the wrong directory. But Maven only
        compiles `src/test/java`, so surefire finds nothing, prints no
        `Tests run:` line, and exits 0. File presence passes, the count is
        absent, and the run used to be reported as successful.
        """
        (tmp_path / "pom.xml").write_text("<project/>\n", encoding="utf-8")
        misplaced = tmp_path / "src" / "main" / "java" / "com" / "example"
        misplaced.mkdir(parents=True)
        (misplaced / "OrderTest.java").write_text("class OrderTest {}\n", encoding="utf-8")

        monkeypatch.setattr(heal_module, "run_tests", run_tests)
        monkeypatch.setattr(
            "vishwakarma.engine.executor.resolve_runner", lambda name: "stub-runner"
        )

        class _Completed:
            returncode = 0
            stdout = "[INFO] No tests to run.\n[INFO] BUILD SUCCESS\n"
            stderr = ""

        monkeypatch.setattr(
            "vishwakarma.engine.executor.subprocess.run", lambda *a, **k: _Completed()
        )

        result = run_tests(tmp_path, "java")

        assert not result.passed, (
            "a run whose runner reported NO test count must not be reported as passing -- "
            "absent evidence is not evidence"
        )
        assert "no test count at all" in result.stderr

    def test_a_reported_zero_still_fails_and_says_so_differently(self, tmp_path, monkeypatch):
        """Zero and absent are both failures, and must be distinguishable.

        They need different remedies: zero means the tests did not execute,
        absent means the runner never looked where they are.
        """
        (tmp_path / "pom.xml").write_text("<project/>\n", encoding="utf-8")
        tests = tmp_path / "src" / "test" / "java"
        tests.mkdir(parents=True)
        (tests / "OrderTest.java").write_text("class OrderTest {}\n", encoding="utf-8")

        monkeypatch.setattr(
            "vishwakarma.engine.executor.resolve_runner", lambda name: "stub-runner"
        )

        class _Completed:
            returncode = 0
            stdout = "Tests run: 0, Failures: 0, Errors: 0, Skipped: 0\n"
            stderr = ""

        monkeypatch.setattr(
            "vishwakarma.engine.executor.subprocess.run", lambda *a, **k: _Completed()
        )

        result = run_tests(tmp_path, "java")

        assert not result.passed
        assert "running 0 tests" in result.stderr

    def test_a_genuine_run_still_passes(self, tmp_path, monkeypatch):
        """The guard must not make every Java run fail instead of every one pass."""
        (tmp_path / "pom.xml").write_text("<project/>\n", encoding="utf-8")
        tests = tmp_path / "src" / "test" / "java"
        tests.mkdir(parents=True)
        (tests / "OrderTest.java").write_text("class OrderTest {}\n", encoding="utf-8")

        monkeypatch.setattr(
            "vishwakarma.engine.executor.resolve_runner", lambda name: "stub-runner"
        )

        class _Completed:
            returncode = 0
            stdout = "Tests run: 4, Failures: 0, Errors: 0, Skipped: 0\n"
            stderr = ""

        monkeypatch.setattr(
            "vishwakarma.engine.executor.subprocess.run", lambda *a, **k: _Completed()
        )

        assert run_tests(tmp_path, "java").passed


class TestAnUnscoreableAttemptDoesNotDisableTheRatchet:
    """R0b, including the bootstrap half where the one-word slip lives."""

    def _drive(self, monkeypatch, tmp_path, outputs):
        written: list[list[FileSpec]] = []
        stream = iter(outputs)

        monkeypatch.setattr(heal_module, "_diagnose", lambda *a, **k: "fix")
        monkeypatch.setattr(
            heal_module,
            "request_files_from_coder",
            lambda *a, **k: GeneratedArtifact(
                files=[FileSpec(path="S.java", content=f"attempt{len(written)}")]
            ),
        )
        monkeypatch.setattr(heal_module, "write_files", lambda w, f: written.append(list(f)))
        monkeypatch.setattr(
            heal_module,
            "run_tests",
            lambda w, lang: ExecutionResult(
                passed=False, stdout=next(stream), stderr="", returncode=1
            ),
        )
        return written

    def test_an_unscoreable_attempt_keeps_the_champion(self, monkeypatch, tmp_path):
        """A dependency failure mid-loop must not discard a known-good state.

        Attempt 1 improves to 1 error. Attempt 2's output is unscoreable. The
        loop must still be holding attempt 1's files, not attempt 2's.
        """
        errors_1 = "[ERROR] /p/A.java:[1,1] cannot find symbol"
        unscoreable = "Could not resolve dependencies for project orders"
        self._drive(monkeypatch, tmp_path, [errors_1, unscoreable, unscoreable, unscoreable])

        start = ExecutionResult(
            passed=False,
            stdout="[ERROR] /p/A.java:[1,1] x\n[ERROR] /p/A.java:[2,2] y\n[ERROR] /p/A.java:[3,3] z",
            stderr="",
            returncode=1,
        )
        result = heal_module.heal(
            task="t",
            language="java",
            workdir=tmp_path,
            files=[FileSpec(path="S.java", content="original")],
            result=start,
            router=None,
            client=None,
            max_attempts=2,
            timeout_seconds=60,
        )

        assert result.final_files[0].content == "attempt0", (
            "attempt 1 reached 1 error; an unscoreable attempt 2 must not replace it"
        )

    def test_the_first_scoreable_attempt_still_initialises_the_champion(
        self, monkeypatch, tmp_path
    ):
        """The bootstrap half -- the branch must key on best_count, not attempt_count.

        If the STARTING result is unscoreable, best_count begins as None. The
        first attempt that can be scored has to establish the baseline; keying
        the skip on attempt_count alone would mean it never does, and the loop
        would return the original broken files forever.
        """
        self._drive(
            monkeypatch,
            tmp_path,
            ["[ERROR] /p/A.java:[1,1] cannot find symbol"] * 4,
        )

        start = ExecutionResult(
            passed=False, stdout="Could not resolve dependencies", stderr="", returncode=1
        )
        result = heal_module.heal(
            task="t",
            language="java",
            workdir=tmp_path,
            files=[FileSpec(path="S.java", content="original")],
            result=start,
            router=None,
            client=None,
            max_attempts=1,
            timeout_seconds=60,
        )

        assert result.final_files[0].content == "attempt0", (
            "with an unscoreable STARTING state, the first scoreable attempt must "
            "become the champion rather than being skipped forever"
        )

    def test_an_unscored_attempt_is_visible(self, monkeypatch, tmp_path):
        events: list[dict] = []
        self._drive(monkeypatch, tmp_path, ["Could not resolve dependencies"] * 4)

        heal_module.heal(
            task="t",
            language="java",
            workdir=tmp_path,
            files=[FileSpec(path="S.java", content="original")],
            result=ExecutionResult(
                passed=False, stdout="[ERROR] /p/A.java:[1,1] x", stderr="", returncode=1
            ),
            router=None,
            client=None,
            max_attempts=1,
            timeout_seconds=60,
            on_event=events.append,
        )

        assert any(e.get("type") == "heal_attempt_unscored" for e in events), (
            "skipping an attempt silently would hide the condition that disabled the ratchet"
        )
