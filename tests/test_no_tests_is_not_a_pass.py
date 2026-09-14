"""A generation that wrote no tests must fail, not report "All tests passed" (#59).

Found by running the tool rather than reading it. `vishwakarma run "add a REST
endpoint for creating an order" --lang java` wrote seven Java sources, zero test
files, and printed "All tests passed" -- because `executor.run_tests` decided
success from the exit code alone, and `mvn test` prints "No tests to run." and
exits 0.

That falsifies the product's headline claim (it writes the code AND its own
tests) in the direction that looks like success, and it corrupts self-heal: the
cheapest way to make the runner exit 0 is to write no tests at all, so the
repair loop is rewarded for dropping them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vishwakarma.engine.executor import run_tests
from vishwakarma.languages import get_adapter


def _write(workdir: Path, relative: str, body: str = "x = 1\n") -> None:
    target = workdir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


class TestASourceOnlyGenerationIsAFailure:
    """The exact shape of the live run that exposed this."""

    def test_java_sources_with_no_test_file_do_not_pass(self, tmp_path):
        """Seven sources and no tests was reported as a pass by mvn's exit 0."""
        _write(tmp_path, "pom.xml", "<project/>\n")
        _write(tmp_path, "src/main/java/com/example/controller/OrderServlet.java", "class A {}\n")
        _write(tmp_path, "src/main/java/com/example/model/Order.java", "class B {}\n")

        result = run_tests(tmp_path, "java")

        assert not result.passed
        assert "No test files were generated" in result.stderr
        assert not result.runner_missing, "this is a generation fault, not a missing runner"

    def test_python_sources_with_no_test_file_do_not_pass(self, tmp_path):
        _write(tmp_path, "reverse_linked_list.py")

        result = run_tests(tmp_path, "python")

        assert not result.passed
        assert "No test files were generated" in result.stderr

    def test_web_sources_with_no_test_file_do_not_pass(self, tmp_path):
        _write(tmp_path, "package.json", '{"name":"t"}\n')
        _write(tmp_path, "index.js", "module.exports = {};\n")

        result = run_tests(tmp_path, "web")

        assert not result.passed
        assert "No test files were generated" in result.stderr

    def test_the_check_runs_before_the_runner_is_even_resolved(self, tmp_path):
        """No subprocess is spawned, so the answer does not depend on a toolchain.

        Deliberate: the fault is that the model wrote no tests, and that is
        knowable without Maven, npm or pytest being installed at all. It also
        keeps this test meaningful on a machine with no JDK.
        """
        _write(tmp_path, "src/main/java/com/example/App.java", "class A {}\n")

        result = run_tests(tmp_path, "java")

        assert result.returncode == -1, "never ran a process"
        assert not result.passed


class TestAGenuineTestSuiteStillPasses:
    """The fix must not make a correct generation look broken."""

    def test_a_real_passing_python_suite_is_still_a_pass(self, tmp_path):
        _write(tmp_path, "mod.py", "def add(a, b):\n    return a + b\n")
        _write(
            tmp_path,
            "test_mod.py",
            "from mod import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
        )

        result = run_tests(tmp_path, "python")

        assert result.passed, result.stderr

    def test_a_real_failing_python_suite_is_still_a_failure(self, tmp_path):
        """A failing suite must stay distinguishable from an absent one."""
        _write(tmp_path, "mod.py", "def add(a, b):\n    return a - b\n")
        _write(
            tmp_path,
            "test_mod.py",
            "from mod import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
        )

        result = run_tests(tmp_path, "python")

        assert not result.passed
        assert "No test files were generated" not in result.stderr, (
            "a failing suite is a different fault from a missing one, and self-heal "
            "needs to be told which"
        )


class TestEachAdapterDeclaresItsOwnConvention:
    """The adapter owns the judgement, because the conventions genuinely differ."""

    @pytest.mark.parametrize("language", ("python", "java", "web"))
    def test_every_adapter_declares_test_file_patterns(self, language):
        patterns = get_adapter(language).test_file_patterns()

        assert patterns, f"{language} must declare how its tests are recognised"
        assert all(isinstance(pattern, str) for pattern in patterns)

    def test_pytest_is_the_only_runner_honest_about_an_empty_collection(self):
        """Measured, and the reason the Python path never showed this bug.

        pytest exits 5 (EXIT_NOTESTSCOLLECTED); `mvn test` and `node --test`
        both exit 0. So the file check is the primary signal and this is a
        second, independent one where the runner happens to cooperate.
        """
        assert get_adapter("python").reports_no_tests_collected(5)
        assert not get_adapter("python").reports_no_tests_collected(0)
        assert not get_adapter("java").reports_no_tests_collected(0)
        assert not get_adapter("web").reports_no_tests_collected(0)

    def test_a_java_test_in_the_standard_layout_is_recognised(self, tmp_path):
        """The positive case for the pattern that matters most on the failing run."""
        _write(tmp_path, "pom.xml", "<project/>\n")
        _write(tmp_path, "src/main/java/com/example/App.java", "class A {}\n")
        _write(tmp_path, "src/test/java/com/example/AppTest.java", "class AppTest {}\n")

        result = run_tests(tmp_path, "java")

        assert "No test files were generated" not in result.stderr, (
            "a correctly-placed Maven test must be recognised, or the fix would "
            "make every Java run fail instead of every Java run pass"
        )
