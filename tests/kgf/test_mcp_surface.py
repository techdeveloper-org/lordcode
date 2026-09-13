"""Tests for kgf's MCP surface (M13).

The load-bearing tests here are the escalation ones. Everything else checks
that a tool returns what its CLI verb returns, which matters but is ordinary;
the security property is the one that would be a claim rather than a control if
it were not exercised:

    posture is launch-time, so neither a call argument nor a spawn environment
    can raise it.

That second half needs a REAL spawned server, because the whole point is what
happens when a client supplies `env=` -- which cannot be observed in-process.
Those tests are slower and there are only as many as the property needs.

No test makes outbound network traffic: `allow_network` defaults False, and the
one test that enables `allow_bash` runs a command that touches nothing.

Windows-safe: ASCII only.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from kgf import manifest as manifest_module
from kgf.mcp import SERVERS, server_path
from kgf.mcp.registry import registry
from kgf.mcp.responses import MAX_RESPONSE_BYTES, SURFACE_VERSION, TOOLS_WITH_MANIFEST
from kgf.mcp.settings import McpSettings, load_settings, write_default_settings

REPO_ROOT = Path(__file__).resolve().parents[2]


def _settings_file(tmp_path: Path, **overrides) -> Path:
    """Write a posture file for one test, creating the sandbox root it names.

    The directory is created here because a root that does not exist refuses
    the server at launch -- correct behaviour, asserted in TestLaunchRefusals,
    and not what the other tests are trying to exercise.
    """
    payload = {"sandbox_root": None, "allow_bash": False, "allow_network": False}
    payload.update(overrides)
    if payload.get("sandbox_root"):
        Path(payload["sandbox_root"]).mkdir(parents=True, exist_ok=True)
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _safe_env() -> dict[str, str]:
    """The minimum a spawned Python needs, plus nothing else.

    Deliberately not `os.environ`: a spawned server inheriting the parent's
    environment would make the env-escalation test meaningless, since the
    variable it tries to set could arrive by accident.
    """
    keep = (
        "PATH", "SYSTEMROOT", "PATHEXT", "TEMP", "TMP", "COMSPEC",
        # APPDATA and USERPROFILE are not optional on Windows: site.USER_SITE
        # is derived from APPDATA, so stripping it leaves a spawned Python
        # unable to import anything installed per-user -- which surfaced as
        # "No module named 'yaml'" and an exit code of 1 where the test wanted
        # the deliberate exit 2. They carry no posture.
        "APPDATA", "USERPROFILE", "LOCALAPPDATA", "HOME",
    )
    return {name: os.environ[name] for name in keep if name in os.environ}


def _call_over_stdio(server: str, tool: str, arguments: dict, *, settings: Path, env_extra=None):
    """Spawn a real server, call one tool, return the parsed payload."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = _safe_env()
    if env_extra:
        env.update(env_extra)

    params = StdioServerParameters(
        command=sys.executable,
        args=[str(server_path(server)), "--settings", str(settings)],
        env=env,
    )

    async def run():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool, arguments)
                return json.loads(result.content[0].text)

    return asyncio.run(run())


def _list_over_stdio(server: str, *, settings: Path):
    """Spawn a real server and return its tool listing."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=sys.executable,
        args=[str(server_path(server)), "--settings", str(settings)],
        env=_safe_env(),
    )

    async def run():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listing = await session.list_tools()
                return [(tool.name, tool.annotations) for tool in listing.tools]

    return asyncio.run(run())


class TestPostureCannotBeRaised:
    """The security property, exercised rather than asserted in prose."""

    def test_bash_is_denied_under_the_default_posture(self, tmp_path):
        payload = _call_over_stdio(
            "kgf-tools",
            "kgf_tool_call",
            {"agent": "api-security-auditor", "tool": "Bash", "arguments": {"argv": ["echo", "hi"]}},
            settings=_settings_file(tmp_path, sandbox_root=str(tmp_path / "work")),
        )
        assert payload["ok"] is False or payload["data"]["decision"] == "denied"

    def test_a_call_argument_cannot_enable_bash(self, tmp_path):
        """M4's denial reason names the opt-in. If the opt-in were a call
        argument, that reason would be escalation instructions."""
        payload = _call_over_stdio(
            "kgf-tools",
            "kgf_tool_call",
            {
                "agent": "api-security-auditor",
                "tool": "Bash",
                "arguments": {"argv": ["echo", "hi"], "allow_bash": True},
            },
            settings=_settings_file(tmp_path, sandbox_root=str(tmp_path / "work")),
        )
        assert payload["ok"] is False
        assert "cannot be set per call" in payload["error"]

    def test_the_spawn_environment_cannot_enable_bash(self, tmp_path):
        """The defect the plan's first draft had. In stdio MCP the client
        supplies `env=`, so a server reading KGF_MCP_ALLOW_BASH would be
        reading what its own launcher chose."""
        payload = _call_over_stdio(
            "kgf-tools",
            "kgf_tool_call",
            {"agent": "api-security-auditor", "tool": "Bash", "arguments": {"argv": ["echo", "hi"]}},
            settings=_settings_file(tmp_path, sandbox_root=str(tmp_path / "work")),
            env_extra={"KGF_MCP_ALLOW_BASH": "1", "KGF_MCP_ALLOW_NETWORK": "1"},
        )
        assert payload["ok"] is False or payload["data"]["decision"] == "denied"

    def test_a_sandbox_root_cannot_be_set_per_call(self, tmp_path):
        payload = _call_over_stdio(
            "kgf-tools",
            "kgf_tool_call",
            {
                "agent": "api-security-auditor",
                "tool": "Read",
                "arguments": {"path": "x.txt", "sandbox_root": str(REPO_ROOT)},
            },
            settings=_settings_file(tmp_path, sandbox_root=str(tmp_path / "work")),
        )
        assert payload["ok"] is False
        assert "cannot be set per call" in payload["error"]

    def test_bash_is_permitted_when_the_settings_file_enables_it(self, tmp_path):
        """The deny-by-default must be a DEFAULT, not the only behaviour -- a
        control that cannot be turned on has not been shown to be a control.

        It must run OVER THE WIRE and the output must be required back, which is
        the regression this asserts (#24): the in-process call returned 'ok\\n'
        while the same call through a server returned nothing, because the child
        inherited the server's stdin -- the client's own request pipe -- and
        blocked against the SDK's pending read on it until the timeout. Checking
        exit_code and error as well as output is deliberate: a 30-second hang
        surfaces as a successful ALLOWED result carrying empty output, so an
        assertion on the decision alone would have passed on a tool that never
        ran a single command.
        """
        work = tmp_path / "work"
        payload = _call_over_stdio(
            "kgf-tools",
            "kgf_tool_call",
            {
                "agent": "api-security-auditor",
                "tool": "Bash",
                "arguments": {"argv": [sys.executable, "-c", "print('ok')"]},
            },
            settings=_settings_file(tmp_path, sandbox_root=str(work), allow_bash=True),
        )
        assert payload["ok"] is True
        assert payload["data"]["decision"] == "allowed"
        assert "ok" in payload["data"]["output"]
        assert payload["data"]["exit_code"] == 0
        assert payload["data"]["error"] == ""


class TestLaunchRefusals:
    """A bad posture stops the SERVER, not the first call."""

    def _launch(self, server: str, settings: Path):
        return subprocess.run(
            [sys.executable, str(server_path(server)), "--settings", str(settings)],
            capture_output=True,
            text=True,
            timeout=120,
            env=_safe_env(),
            stdin=subprocess.DEVNULL,
        )

    def test_a_sandbox_root_containing_the_library_is_refused_at_launch(self, tmp_path):
        """M4's own constructor check, reused so the MCP surface cannot be
        laxer than the in-process runtime."""
        from kgf.source import locate_library

        library = locate_library(None)
        settings = _settings_file(tmp_path, sandbox_root=str(library.root.parent))
        result = self._launch("kgf-tools", settings)

        assert result.returncode == 2
        assert "cannot start" in result.stderr

    def test_a_malformed_settings_file_is_refused_at_launch(self, tmp_path):
        settings = tmp_path / "mcp.json"
        settings.write_text("{not json", encoding="utf-8")
        result = self._launch("kgf-graph", settings)

        assert result.returncode == 2
        assert "cannot start" in result.stderr

    def test_a_truthy_string_flag_is_refused_at_launch(self, tmp_path):
        """A string is truthy and would silently grant the opt-in."""
        settings = _settings_file(tmp_path, allow_bash="yes")
        result = self._launch("kgf-tools", settings)

        assert result.returncode == 2


class TestTheSurfaceMatchesItsRegistry:
    def test_every_registry_server_has_an_entry_point(self):
        for name in registry()["servers"]:
            assert server_path(name).is_file(), name

    def test_the_registry_and_the_package_agree_on_the_server_set(self):
        assert set(registry()["servers"]) == set(SERVERS)

    def test_only_kgf_tools_is_mutating(self):
        mutating = [name for name, spec in registry()["servers"].items() if not spec["read_only"]]
        assert mutating == ["kgf-tools"]

    @pytest.mark.parametrize("server", sorted(registry()["servers"]))
    def test_the_live_tool_list_matches_the_registry(self, server, tmp_path):
        listed = dict(_list_over_stdio(server, settings=_settings_file(tmp_path)))
        assert sorted(listed) == sorted(registry()["servers"][server]["tools"])

    def test_read_only_servers_annotate_every_tool_read_only(self, tmp_path):
        """The MCP spec's per-hint defaults all point at the more dangerous
        value, so an unannotated tool is indistinguishable from an explicit
        worst case and a host may refuse to auto-approve it."""
        for server, spec in registry()["servers"].items():
            if not spec["read_only"]:
                continue
            for name, annotations in _list_over_stdio(server, settings=_settings_file(tmp_path)):
                assert annotations is not None, f"{server}.{name} is unannotated"
                assert annotations.readOnlyHint is True, f"{server}.{name}"

    def test_kgf_tool_call_is_annotated_mutating(self, tmp_path):
        listed = dict(_list_over_stdio("kgf-tools", settings=_settings_file(tmp_path)))
        assert listed["kgf_tool_call"].readOnlyHint is False
        assert listed["kgf_grant"].readOnlyHint is True


class TestToolsAgreeWithTheirCliVerbs:
    """The CLI stays the reference; a tool must not grow a second behaviour."""

    def test_kgf_route_over_the_wire_equals_kgf_route_in_process(self, tmp_path):
        from kgf.loader import load_graph
        from kgf.select import Selector
        from kgf.source import locate_library

        task = "build a spring boot REST service with JPA"
        source = locate_library(None)
        graph, _log = load_graph(None)
        expected = Selector(graph, source).select(task, limit=3)

        payload = _call_over_stdio(
            "kgf-selection", "kgf_route", {"task": task, "limit": 3},
            settings=_settings_file(tmp_path),
        )

        assert payload["ok"] is True
        assert payload["data"]["outcome"] == expected.outcome.value
        assert [m["agent"] for m in payload["data"]["matches"]] == [m.agent for m in expected.matches]

    def test_kgf_stats_over_the_wire_equals_the_graph(self, tmp_path):
        from kgf.loader import load_graph

        graph, _log = load_graph(None)
        payload = _call_over_stdio("kgf-graph", "kgf_stats", {}, settings=_settings_file(tmp_path))

        assert payload["data"]["agents"] == len(graph.agents)
        assert payload["data"]["edges"] == graph.edge_count


class TestTheEnvelope:
    def test_every_response_carries_the_surface_version(self, tmp_path):
        payload = _call_over_stdio("kgf-graph", "kgf_stats", {}, settings=_settings_file(tmp_path))
        assert payload["surface_version"] == SURFACE_VERSION

    def test_a_correlation_id_is_echoed(self, tmp_path):
        payload = _call_over_stdio(
            "kgf-graph", "kgf_stats", {"correlation_id": "req-77"}, settings=_settings_file(tmp_path)
        )
        assert payload["correlation_id"] == "req-77"

    def test_the_fingerprint_is_content_based(self, tmp_path):
        """Per-registry sha256, not mtime -- which is what makes it comparable
        across the four processes of one compose and across machines."""
        payload = _call_over_stdio("kgf-graph", "kgf_fingerprint", {}, settings=_settings_file(tmp_path))
        digests = payload["data"]["registry_digests"]
        assert len(digests) == 5
        assert all(len(digest) == 64 for _name, digest in digests)

    def test_only_the_four_deciding_tools_carry_a_manifest_fragment(self, tmp_path):
        """13 of 15 tools have no decision to record, and a key that is empty
        most of the time teaches a caller to ignore it."""
        stats = _call_over_stdio("kgf-graph", "kgf_stats", {}, settings=_settings_file(tmp_path))
        assert "manifest_fragment" not in stats

        route = _call_over_stdio(
            "kgf-selection", "kgf_route", {"task": "a REST endpoint"}, settings=_settings_file(tmp_path)
        )
        assert "manifest_fragment" in route
        assert "kgf_route" in TOOLS_WITH_MANIFEST

    def test_a_missing_agent_is_a_failure_response_not_a_dead_session(self, tmp_path):
        payload = _call_over_stdio(
            "kgf-graph", "kgf_agent", {"name": "no-such-agent-xyz"}, settings=_settings_file(tmp_path)
        )
        assert payload["ok"] is False
        assert "no-such-agent-xyz" in payload["error"]


class TestOutputIsBounded:
    def test_validate_returns_counts_not_every_defect(self, tmp_path):
        """M1 catalogues 6,696 EdgeID failures alone; inline they would evict
        the very context M3 exists to budget."""
        payload = _call_over_stdio("kgf-graph", "kgf_validate", {}, settings=_settings_file(tmp_path))

        assert payload["ok"] is True
        assert "defect_counts" in payload["data"]
        assert "detail" not in payload["data"]
        assert len(json.dumps(payload).encode("utf-8")) < MAX_RESPONSE_BYTES

    def test_detail_for_one_class_is_capped(self, tmp_path):
        payload = _call_over_stdio(
            "kgf-graph",
            "kgf_validate",
            {"defect_class": "EDGE_ID_PATTERN", "limit": 5},
            settings=_settings_file(tmp_path),
        )
        detail = payload["data"].get("detail")
        if detail and detail["total"]:
            assert len(detail["returned"]) <= 5
            assert detail["truncated"] is (detail["total"] > 5)

    def test_a_context_budget_is_clamped(self, tmp_path):
        payload = _call_over_stdio(
            "kgf-context",
            "kgf_context",
            {"agent": "spring-boot-microservices", "budget_tokens": 10_000_000, "include_text": False},
            settings=_settings_file(tmp_path),
        )
        assert payload["ok"] is True
        assert payload["data"]["budget_tokens"] <= 32_000


class TestAComposeAcrossAllFourServers:
    def test_one_correlation_id_and_one_fingerprint_thread_through(self, tmp_path):
        """Four processes, one request. Without the correlation id this is four
        unrelated log streams and nothing ties the fragments together."""
        settings = _settings_file(tmp_path, sandbox_root=str(tmp_path / "work"))
        cid = "compose-abc"

        route = _call_over_stdio(
            "kgf-selection", "kgf_route", {"task": "a spring boot REST service", "correlation_id": cid},
            settings=settings,
        )
        agent = route["data"]["matches"][0]["agent"]

        closure = _call_over_stdio(
            "kgf-selection", "kgf_closure", {"agent": agent, "correlation_id": cid}, settings=settings
        )
        context = _call_over_stdio(
            "kgf-context",
            "kgf_context",
            {"agent": agent, "include_text": False, "correlation_id": cid},
            settings=settings,
        )
        grant = _call_over_stdio(
            "kgf-tools", "kgf_grant", {"agent": agent, "correlation_id": cid}, settings=settings
        )

        stages = [route, closure, context, grant]
        assert all(stage["ok"] for stage in stages)
        assert {stage["correlation_id"] for stage in stages} == {cid}
        assert len({json.dumps(stage["fingerprint"]) for stage in stages}) == 1

    def test_the_fragments_merge_into_one_replayable_manifest(self, tmp_path):
        settings = _settings_file(tmp_path)
        cid = "compose-def"
        route = _call_over_stdio(
            "kgf-selection", "kgf_route", {"task": "a spring boot REST service", "correlation_id": cid},
            settings=settings,
        )
        agent = route["data"]["matches"][0]["agent"]
        context = _call_over_stdio(
            "kgf-context",
            "kgf_context",
            {"agent": agent, "include_text": False, "correlation_id": cid},
            settings=settings,
        )

        fragments = [
            manifest_module.from_dict(route["manifest_fragment"]),
            manifest_module.from_dict(context["manifest_fragment"]),
        ]
        merged = manifest_module.merge(fragments)

        assert merged.correlation_id == cid
        assert merged.agent
        assert merged.context_sha256
        assert manifest_module.replay(merged).matches

    def test_the_context_server_recomputes_the_closure(self, tmp_path):
        """A tampered skill list is ignored, because this server derives its
        own. A tampered AGENT id is a different valid request and cannot be
        detected -- which the docstring says rather than implying otherwise."""
        settings = _settings_file(tmp_path)
        payload = _call_over_stdio(
            "kgf-context",
            "kgf_context",
            {"agent": "spring-boot-microservices", "include_text": False},
            settings=settings,
        )
        from kgf.closure import build_closure
        from kgf.loader import load_graph

        graph, _log = load_graph(None)
        expected = build_closure(graph, "spring-boot-microservices")
        assert payload["data"]["closure_skills"] == list(expected.all_skills)


class TestMergeRefusals:
    """Unit-level, because the cross-compose case is the one digests miss."""

    def _fragment(self, correlation_id: str, **overrides):
        from kgf.source import locate_library

        source = locate_library(None)
        return manifest_module.build("t", source, correlation_id=correlation_id, **overrides)

    def test_fragments_from_different_composes_are_refused(self):
        first = self._fragment("one")
        second = self._fragment("two")
        with pytest.raises(ValueError, match="different composes"):
            manifest_module.merge([first, second])

    def test_the_refusal_explains_why_digests_were_not_enough(self):
        with pytest.raises(ValueError, match="same library"):
            manifest_module.merge([self._fragment("one"), self._fragment("two")])

    def test_fragments_from_different_libraries_are_refused(self):
        import dataclasses

        first = self._fragment("same")
        second = dataclasses.replace(first, registry_digests=(("agents_all.json", "0" * 64),))
        with pytest.raises(ValueError, match="different libraries"):
            manifest_module.merge([first, second])

    def test_an_empty_set_is_refused(self):
        with pytest.raises(ValueError, match="no fragments"):
            manifest_module.merge([])

    def test_one_fragment_merges_to_itself(self):
        only = self._fragment("solo")
        assert manifest_module.merge([only]) == only

    def test_differing_stamps_are_not_a_conflict_and_the_earliest_wins(self):
        """created_at describes the FRAGMENT, not the run. Four servers stamp
        four times for one compose, so treating that as a conflict refuses every
        real merge -- which is how this was found."""
        import dataclasses

        base = self._fragment("same")
        first = dataclasses.replace(base, created_at="2026-09-13T15:27:18+00:00")
        second = dataclasses.replace(base, created_at="2026-09-13T15:27:14+00:00")
        assert manifest_module.merge([first, second]).created_at == "2026-09-13T15:27:14+00:00"

    def test_a_fragment_without_an_outcome_cannot_declare_the_run_forced(self):
        """`False` is indistinguishable from unset for a bool, so the empty-field
        rule would let any fragment claiming True override a selection that
        genuinely ranked -- and a manifest saying forced makes replay SKIP
        re-ranking, retiring the check replay exists to perform."""
        import dataclasses

        base = self._fragment("same")
        ranked = dataclasses.replace(
            base, outcome="selected", agent="agent:x", forced_agent=False
        )
        opinionless = dataclasses.replace(base, outcome="", agent="", forced_agent=True)
        assert manifest_module.merge([ranked, opinionless]).forced_agent is False

    def test_a_genuinely_forced_selection_survives_the_merge(self):
        """The guard above must not flatten the real case to False."""
        import dataclasses

        base = self._fragment("same")
        forced = dataclasses.replace(
            base, outcome="selected", agent="agent:x", forced_agent=True
        )
        context_only = dataclasses.replace(base, outcome="", agent="", forced_agent=False)
        assert manifest_module.merge([forced, context_only]).forced_agent is True


class TestTheCliVerbs:
    def _run(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "kgf.cli", "mcp", *args],
            capture_output=True,
            text=True,
            timeout=180,
            cwd=REPO_ROOT,
        )

    def test_list_shows_the_flag_state(self):
        result = self._run("list")
        assert result.returncode == 0
        assert "allow_bash" in result.stdout
        assert "MUTATING" in result.stdout

    def test_config_emits_no_flag_names(self):
        """A config example is the first thing anyone copies, so emitting
        `env: {KGF_MCP_ALLOW_BASH: "0"}` would hand every reader the exact
        string that flips the control."""
        result = self._run("config")
        assert result.returncode == 0
        for flag in ("allow_bash", "allow_network", "sandbox_root"):
            assert flag not in json.dumps(json.loads(result.stdout.split("\n\n")[0]))

    def test_config_writes_nothing(self, tmp_path):
        settings = write_default_settings(tmp_path / "mcp.json")
        before = settings.stat().st_mtime_ns
        self._run("config")
        assert settings.stat().st_mtime_ns == before

    def test_config_refuses_an_unknown_server(self):
        result = self._run("config", "kgf-nonexistent")
        assert result.returncode == 2
        assert "unknown server" in result.stderr


class TestSettingsModule:
    def test_an_absent_file_is_created_with_everything_denied(self, tmp_path):
        settings = load_settings(tmp_path / "mcp.json")
        assert settings.allow_bash is False
        assert settings.allow_network is False
        assert settings.has_sandbox is False
        assert (tmp_path / "mcp.json").is_file()

    def test_the_environment_cannot_set_a_flag(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KGF_MCP_ALLOW_BASH", "1")
        monkeypatch.setenv("KGF_MCP_ALLOW_NETWORK", "1")
        settings = load_settings(_settings_file(tmp_path))
        assert settings.allow_bash is False
        assert settings.allow_network is False

    def test_the_library_root_is_the_one_key_the_environment_may_set(self, tmp_path, monkeypatch):
        """It selects what a server KNOWS, not what it may do, so a launcher
        choosing it is a configuration decision rather than a privilege one."""
        monkeypatch.setenv("KGF_LIBRARY_PATH", str(tmp_path / "elsewhere"))
        settings = load_settings(_settings_file(tmp_path))
        assert settings.library_root == tmp_path / "elsewhere"

    def test_describe_names_the_source_file(self, tmp_path):
        path = _settings_file(tmp_path)
        assert str(path) in load_settings(path).describe()
