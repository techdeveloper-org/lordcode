"""The heal loop must not end worse than a state it already reached (#64).

Before this, `heal` had a bound and a success condition and nothing in between:
an attempt that increased the error count was carried forward exactly like one
that reduced it, and the next diagnosis started from the worse state.

Measured live on a Spring project, compile errors went 3 -> 1 -> 5. Every fix
was locally reasonable; the sequence was not. The last five came from an attempt
rewriting a service against a constructor signature an *earlier* attempt had
itself changed.

Python never showed this: a single-file generation has no cross-file contract to
break, which is also why every end-to-end check before now missed it.
"""

from __future__ import annotations

from vishwakarma.engine import self_heal as heal_module
from vishwakarma.engine.executor import ExecutionResult
from vishwakarma.engine.generate import FileSpec, GeneratedArtifact
from vishwakarma.languages import get_adapter


def _javac_errors(*sites: str) -> str:
    """Render javac output naming one error per site, echoed as Maven does."""
    lines = [f"[ERROR] /p/src/main/java/{site} cannot find symbol" for site in sites]
    return "\n".join(lines + lines)


def _result(output: str, passed: bool = False) -> ExecutionResult:
    return ExecutionResult(passed=passed, stdout=output, stderr="", returncode=0 if passed else 1)


class TestTheFailureCountIsAUsableProgressSignal:
    """Rollback is only as good as the number it compares."""

    def test_maven_echoes_each_error_so_sites_are_counted_once(self):
        """Maven prints every compiler error twice -- once from the compiler,
        once in its own failure summary. Counting lines would double it."""
        adapter = get_adapter("java")
        output = _javac_errors("A.java:[1,2]", "A.java:[3,4]", "B.java:[5,6]")

        assert adapter.failure_count(output, "") == 3

    def test_a_compiling_project_falls_through_to_failing_tests(self):
        adapter = get_adapter("java")

        assert adapter.failure_count("Tests run: 7, Failures: 2, Errors: 1, Skipped: 0", "") == 3

    def test_a_green_run_scores_zero_not_unknown(self):
        """Zero and "cannot tell" must stay distinct, or a perfect state gets
        overwritten by a worse one."""
        assert get_adapter("java").failure_count("Tests run: 7, Failures: 0, Errors: 0", "") == 0
        assert get_adapter("python").failure_count("6 passed in 0.1s", "") == 0

    def test_unparseable_output_is_none_rather_than_zero(self):
        assert get_adapter("java").failure_count("", "") is None
        assert get_adapter("python").failure_count("", "") is None


class TestARegressingAttemptIsRolledBack:
    """The defect, reproduced as the live run produced it."""

    def _run(self, monkeypatch, tmp_path, sequence):
        """Drive heal with a scripted series of post-fix failure outputs."""
        written: list[list[str]] = []
        outputs = iter(sequence)

        monkeypatch.setattr(heal_module, "_diagnose", lambda *a, **k: "fix it")
        monkeypatch.setattr(
            heal_module,
            "request_files_from_coder",
            lambda *a, **k: GeneratedArtifact(
                files=[FileSpec(path="src/main/java/Service.java", content=f"v{len(written)}")]
            ),
        )
        monkeypatch.setattr(
            heal_module,
            "write_files",
            lambda workdir, files: written.append([f.content for f in files]),
        )
        monkeypatch.setattr(heal_module, "run_tests", lambda workdir, language: _result(next(outputs)))

        start = _result(_javac_errors("A.java:[1,1]", "A.java:[2,2]", "A.java:[3,3]"))
        return (
            heal_module.heal(
                task="t",
                language="java",
                workdir=tmp_path,
                files=[FileSpec(path="src/main/java/Service.java", content="v0")],
                result=start,
                router=None,
                client=None,
                max_attempts=2,
                timeout_seconds=60,
            ),
            written,
        )

    def test_the_loop_does_not_end_worse_than_it_started(self, monkeypatch, tmp_path):
        """3 errors -> attempt makes it 5 -> the worse state must not be kept."""
        events = []
        sequence = [
            _javac_errors(*[f"S.java:[{i},1]" for i in range(5)]),  # attempt 1: worse
            _javac_errors(*[f"S.java:[{i},1]" for i in range(5)]),  # the rollback re-run
            _javac_errors(*[f"S.java:[{i},1]" for i in range(5)]),  # attempt 2
            _javac_errors(*[f"S.java:[{i},1]" for i in range(5)]),
            _javac_errors(*[f"S.java:[{i},1]" for i in range(5)]),
        ]
        result, written = self._run(monkeypatch, tmp_path, sequence)

        assert not result.passed
        assert result.final_files[0].content == "v0", (
            "the original 3-error state was better than the 5-error one the "
            "attempt produced, so it must be what the loop hands back"
        )

    def test_an_improving_attempt_is_kept(self, monkeypatch, tmp_path):
        """Rollback must not fire on progress, or the loop can never converge."""
        sequence = [
            _javac_errors("A.java:[1,1]"),  # attempt 1: 3 -> 1, better
            _javac_errors("A.java:[1,1]"),  # attempt 2: unchanged
            _javac_errors("A.java:[1,1]"),
            _javac_errors("A.java:[1,1]"),
        ]
        result, _ = self._run(monkeypatch, tmp_path, sequence)

        assert result.final_files[0].content != "v0", "an improvement must be carried forward"

    def test_a_regression_is_reported_as_an_event(self, monkeypatch, tmp_path):
        """Silent rollback would hide the very behaviour this fixes."""
        events: list[dict] = []
        outputs = iter(
            [_javac_errors(*[f"S.java:[{i},1]" for i in range(5)])] * 6
        )
        monkeypatch.setattr(heal_module, "_diagnose", lambda *a, **k: "fix")
        monkeypatch.setattr(
            heal_module,
            "request_files_from_coder",
            lambda *a, **k: GeneratedArtifact(files=[FileSpec(path="S.java", content="worse")]),
        )
        monkeypatch.setattr(heal_module, "write_files", lambda workdir, files: None)
        monkeypatch.setattr(heal_module, "run_tests", lambda workdir, language: _result(next(outputs)))

        heal_module.heal(
            task="t",
            language="java",
            workdir=tmp_path,
            files=[FileSpec(path="S.java", content="original")],
            result=_result(_javac_errors("A.java:[1,1]")),
            router=None,
            client=None,
            max_attempts=1,
            timeout_seconds=60,
            on_event=events.append,
        )

        regressions = [e for e in events if e.get("type") == "heal_attempt_regressed"]
        assert regressions, "a rejected attempt must be visible in the event stream"
        assert regressions[0]["failures"] > regressions[0]["best"]
