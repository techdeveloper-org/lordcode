"""The two router_fast classifiers, tested on what they do with a response.

Both had no test at all. `tests/test_orchestrator.py` monkeypatches
`detect_language` and `classify_complexity` wholesale (:93, :108, :181) to get
at run_task's branching, which is the right call for those tests and leaves the
parsing itself unexercised -- so a reasoning trace could invert an answer and
the suite would stay green.

These call the real functions with a stubbed `call_role`, so the assertion is
on the parse rather than on the model. The cases that matter are the ones where
the wrong answer is returned CONFIDENTLY: both sites fall back silently rather
than raising, so a mis-parse is invisible at runtime (#53).
"""

from __future__ import annotations

import pytest

from vishwakarma.engine import orchestrator


def _answering(response: str, recorder: dict | None = None):
    """Stub call_role with a fixed response, optionally recording its kwargs."""

    def _call_role(role, purpose, messages, router, client, **kwargs):
        if recorder is not None:
            recorder.update(kwargs)
            recorder["role"] = role
        return response

    return _call_role


class TestAThinkTraceCannotInvertTheAnswer:
    """The defect #53 exists for: the trace is discarded before parsing."""

    def test_a_trace_reasoning_about_complexity_does_not_flip_a_simple_verdict(
        self, monkeypatch
    ):
        """The case that was silently wrong.

        `classify_complexity` used to test `"complex" in raw`. A model that
        reasons "this is not complex" and then answers "simple" put the word
        into the discarded trace, so the function returned the exact opposite
        of the model's own conclusion -- with no error.
        """
        monkeypatch.setattr(
            orchestrator,
            "call_role",
            _answering("<think>This is not complex at all, just one function.</think>simple"),
        )

        assert orchestrator.classify_complexity("reverse a linked list", None, None) == "simple"

    def test_a_trace_naming_an_earlier_option_does_not_change_the_target(
        self, monkeypatch
    ):
        """Same shape on the language side, where being wrong costs the most.

        The trace must name an option that sorts EARLIER than the true answer
        in `available_languages()` (`['java', 'python', 'web']`), because the
        parse returns the first option it finds. A trace naming a LATER option
        passes against the old code too, by luck of iteration order, and would
        be a test that cannot fail.

        Verified discriminating: against the pre-fix parse this case returns
        'java'. A wrong language selects the wrong test runner, which cannot
        pass, so self-heal then spends every attempt on a fault no code change
        can reach.
        """
        monkeypatch.setattr(
            orchestrator,
            "call_role",
            _answering("<think>This is not java, despite the enterprise feel.</think>python"),
        )

        assert orchestrator.detect_language("build a FastAPI service", None, None) == "python"

    def test_a_genuinely_complex_verdict_still_survives_a_trace(self, monkeypatch):
        """Stripping the trace must not cost the positive case."""
        monkeypatch.setattr(
            orchestrator,
            "call_role",
            _answering("<think>Several files and real business logic.</think>complex"),
        )

        assert orchestrator.classify_complexity("build an order service", None, None) == "complex"


class TestTheSilentFallbacksStillHold:
    """Degradation is by design here; it must degrade to the documented value."""

    def test_empty_output_falls_back_to_the_default_language(self, monkeypatch):
        monkeypatch.setattr(orchestrator, "call_role", _answering(""))

        assert orchestrator.detect_language("anything", None, None) == orchestrator.DEFAULT_LANGUAGE

    def test_empty_output_falls_back_to_simple(self, monkeypatch):
        """Worth stating plainly: empty means 'simple', which PRUNES phases.

        `orchestrator.py` prunes phase:A and phase:2 on "simple" and gates
        parallel generation on "complex", so an empty response quietly removes
        the architecture and blueprint-validation phases. That is the
        documented behaviour and this test pins it; it is also the reason #53
        treats a mis-parse as a correctness bug rather than a cosmetic one.
        """
        monkeypatch.setattr(orchestrator, "call_role", _answering(""))

        assert orchestrator.classify_complexity("anything", None, None) == "simple"

    def test_an_unrecognised_language_falls_back_rather_than_guessing(self, monkeypatch):
        monkeypatch.setattr(orchestrator, "call_role", _answering("cobol"))

        assert orchestrator.detect_language("anything", None, None) == orchestrator.DEFAULT_LANGUAGE


class TestTheReasoningParameterIsLeftToTheAdapter:
    """#54: the call sites must not set a provider-specific wire parameter."""

    @pytest.mark.parametrize(
        "classify",
        (orchestrator.detect_language, orchestrator.classify_complexity),
        ids=("detect_language", "classify_complexity"),
    )
    def test_neither_site_hardcodes_reasoning_effort(self, classify, monkeypatch):
        """They used to pass reasoning_effort="low" as a literal.

        That reached past `_light_reasoning_effort_for`, which is the one place
        allowed to decide this, and which returns None for any model family it
        does not recognise. The literal made that safe default unreachable.
        """
        recorded: dict = {}
        monkeypatch.setattr(orchestrator, "call_role", _answering("python", recorded))

        classify("anything", None, None)

        assert "reasoning_effort" not in recorded, (
            "the call site must not set reasoning_effort; "
            "_light_reasoning_effort_for is the only place that may"
        )
        assert recorded.get("light_reasoning") is True, (
            "light_reasoning=True is what routes the decision to the adapter"
        )
        assert recorded["role"] == "router_fast"
