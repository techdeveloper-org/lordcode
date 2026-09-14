"""Three independent fixes the Round 11 review freed from the Java work's queue.

R1a (#56 partial) -- the inter-chunk timeout was 120s, so one chunk every 119
seconds read as healthy. The router advances only on exceptions and a slow
stream raises none, so such a call had no timeout, no error and no failover.

R5 (#57) -- validate_startup memoised catalogue successes but not failures, so a
dead provider was re-probed once per role naming it, at 13.8s each.

R6 (#58) -- strip_reasoning_trace promised the LAST closing tag and used
`.search()`, which finds the first, leaving a whole second trace inside what it
called the answer.
"""

from __future__ import annotations

import openai
import pytest

from vishwakarma.config import ModelConfig, RoleCandidate
from vishwakarma.engine.reasoning_utils import strip_reasoning_trace
from vishwakarma.llm_client import REQUEST_TIMEOUT_SECONDS
from vishwakarma.router import Router


class TestTheInterChunkTimeoutIsTight:
    """R1a. The constant is the whole fix, so the constant is the assertion."""

    def test_a_stalled_stream_is_killed_in_tens_of_seconds_not_minutes(self):
        """120s meant a provider emitting one token every 119s looked healthy."""
        assert REQUEST_TIMEOUT_SECONDS <= 30.0, (
            "this is the max gap BETWEEN CHUNKS, not the max total response; a "
            "loose value here is indistinguishable from a hang because the router "
            "only fails over on exceptions"
        )
        assert REQUEST_TIMEOUT_SECONDS >= 15.0, (
            "it must still exceed any inter-chunk gap a working provider shows, "
            "or a healthy slow generation gets killed -- which is the property "
            "this timeout exists to protect"
        )


class TestADeadProviderIsProbedOnce:
    """R5. The cost was linear in the number of roles naming it."""

    def _router(self, probes: list[str]):
        """Every role lists the dead provider FIRST and a live one second.

        The live fallback is what makes this test able to fail. With only the
        dead candidate, `validate_startup` raises on the first role and never
        reaches the other three -- so exactly one probe happens whether or not
        failures are cached, and the assertion holds vacuously. Startup has to
        SUCCEED for the per-role cost to be observable at all.
        """

        class _Client:
            def is_available(self, provider, api_key_env=None):
                return True

            def list_model_ids(self, provider, api_key_env=None):
                probes.append(provider)
                if provider == "dead":
                    raise openai.APIConnectionError(request=None)
                return {"live-model"}

        models = ModelConfig(
            roles={
                name: [
                    RoleCandidate(provider="dead", model="m"),
                    RoleCandidate(provider="live", model="live-model"),
                ]
                for name in ("primary_coder", "router_fast", "reasoner", "fallback_long_context")
            },
            max_heal_attempts=3,
            heal_timeout_seconds=300,
        )
        return Router(models, _Client())

    def test_four_roles_naming_one_dead_provider_probe_it_once(self):
        probes: list[str] = []
        router = self._router(probes)

        router.validate_startup()

        assert probes.count("dead") == 1, (
            f"probed the dead provider {probes.count('dead')} times; it is down for "
            "every role, and each probe cost 13.8s of startup before this fix"
        )

    def test_the_live_fallback_is_still_selected_for_every_role(self):
        """Caching a failure must not cost the failover it exists alongside."""
        probes: list[str] = []
        router = self._router(probes)

        router.validate_startup()

        for role in ("primary_coder", "router_fast", "reasoner", "fallback_long_context"):
            assert router.resolve(role).provider == "live"


class TestTheLastTraceWins:
    """R6. First-match left a whole second trace inside 'the answer'."""

    def test_two_traces_yield_the_text_after_the_last(self):
        raw = "<think>first</think>middle<think>second, and complex</think>simple"

        assert strip_reasoning_trace(raw) == "simple"

    def test_a_single_trace_is_unchanged_by_the_fix(self):
        """The common case must be untouched, or this is a behaviour change."""
        assert strip_reasoning_trace("<think>reasoning here</think>answer") == "answer"

    def test_text_with_no_trace_is_returned_stripped(self):
        assert strip_reasoning_trace("  plain answer  ") == "plain answer"

    def test_the_inversion_this_protects_against(self):
        """Why last-match matters: both classifiers parse by substring.

        A surviving second trace containing "complex" makes classify_complexity
        return "complex" no matter what the model actually concluded -- the
        exact inversion #53 removed, reachable again through a repeated trace.
        """
        raw = "<think>a</think>noise<think>this is not complex</think>simple"

        assert "complex" not in strip_reasoning_trace(raw)

    def test_an_answer_containing_the_literal_tag_is_truncated(self):
        """The accepted cost, pinned so it is a decision rather than a surprise.

        Recorded rather than fixed because `generate.py` does not import this
        function, so the coder's JSON path -- the one place large verbatim
        content flows -- never reaches it.
        """
        assert strip_reasoning_trace("<think>t</think>see </think> here") == "here"
