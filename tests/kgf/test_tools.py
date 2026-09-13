"""Tests for tool grants, the sandbox, and the tool runtime.

The escape tests are written PER TOOL rather than once. Asserting confinement a
single time against `read()` is exactly what let `glob()` and `grep()` ship an
exploitable hole: `read()` called `Sandbox.resolve()` and they did not, so one
assertion passed while two tools walked out of the sandbox and `grep` returned
the contents of files outside it.
"""

from __future__ import annotations

import http.server
import os
import threading

import pytest

from kgf.closure import build_closure
from kgf.tools import (
    ALL_TOOLS,
    BASH_ENV_ALLOWLIST,
    DEFAULT_SEARCH_ENDPOINT,
    SANDBOXED_PATH_TOOLS,
    SEARCH_ENDPOINT_ENV,
    TIER_TOOLSETS,
    Decision,
    DenialReason,
    Sandbox,
    SandboxConfigError,
    SandboxViolation,
    Tool,
    ToolGrant,
    ToolRuntime,
    address_is_permitted,
    _build_opener,
    grant_distribution,
    grant_for,
)

FULL = frozenset(ALL_TOOLS)


@pytest.fixture
def work(tmp_path):
    """A sandbox root with a secret placed OUTSIDE it."""
    (tmp_path / "SECRET.txt").write_text("API_KEY=sk-must-never-leak", encoding="utf-8")
    root = tmp_path / "work"
    root.mkdir()
    (root / "inside.txt").write_text("benign API_KEY=inside", encoding="utf-8")
    return root


def runtime(root, tools=FULL, **sandbox_kwargs) -> ToolRuntime:
    """A runtime granting `tools`, over a sandbox at `root`."""
    grant = ToolGrant(agent="agent:test", tools=frozenset(tools), ceiling=frozenset(tools))
    return ToolRuntime(grant, Sandbox(root=root, **sandbox_kwargs))


# --------------------------------------------------------------------------
# Sandbox confinement, asserted per tool
# --------------------------------------------------------------------------


def test_read_refuses_traversal(work):
    with pytest.raises(SandboxViolation):
        runtime(work).read("../SECRET.txt")


def test_write_refuses_traversal(work):
    with pytest.raises(SandboxViolation):
        runtime(work).write("../escaped.txt", "x")


def test_edit_refuses_traversal(work):
    with pytest.raises(SandboxViolation):
        runtime(work).edit("../SECRET.txt", "API_KEY", "nope")


def test_glob_refuses_traversal(work):
    """The hole. Granted to 528/528 agents and present in all three tiers."""
    result = runtime(work).glob("../**/*.txt")
    assert "SECRET" not in result.output
    assert "traverses outside" in result.error


def test_grep_refuses_traversal_and_leaks_nothing(work):
    """The worst case: grep returned the CONTENTS of files outside the sandbox."""
    result = runtime(work).grep("API_KEY", "../*.txt")
    assert "sk-must-never-leak" not in result.output
    assert "traverses outside" in result.error


def test_a_symlink_pointing_out_is_refused(work, tmp_path):
    """Rejecting `..` is not enough on its own; resolution catches the rest."""
    link = work / "sneaky.txt"
    try:
        link.symlink_to(tmp_path / "SECRET.txt")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted in this environment")

    with pytest.raises(SandboxViolation):
        runtime(work).read("sneaky.txt")

    leaked = runtime(work).grep("API_KEY", "*.txt")
    assert "sk-must-never-leak" not in leaked.output


def test_every_sandboxed_tool_is_covered_by_a_traversal_test():
    """Guards the shape of this file, not the code.

    If a path-taking tool is added to SANDBOXED_PATH_TOOLS without a matching
    refusal test, this fails -- which is the check that was missing when Glob and
    Grep were added.
    """
    tested = {"Read", "Write", "Edit", "Glob", "Grep"}
    assert SANDBOXED_PATH_TOOLS == tested, (
        "a sandboxed tool gained or lost coverage; add its own traversal test"
    )
    assert Tool.BASH.value not in SANDBOXED_PATH_TOOLS, (
        "Bash is deliberately not in this set: cwd is not a jail, which is why it needs opt-in"
    )


def test_tools_still_work_inside_the_sandbox(work):
    """Confinement must not break the normal path."""
    tool = runtime(work)
    assert "inside.txt" in tool.glob("*.txt").output
    assert "inside.txt:1:" in tool.grep("API_KEY").output
    assert tool.read("inside.txt").output.startswith("benign")
    assert tool.write("sub/new.txt", "data").ok
    assert tool.read("sub/new.txt").output == "data"
    assert tool.edit("sub/new.txt", "data", "changed").ok
    assert tool.read("sub/new.txt").output == "changed"


def test_edit_requires_a_unique_match(work):
    tool = runtime(work)
    tool.write("dup.txt", "aa")
    assert "must be unique" in tool.edit("dup.txt", "a", "b").error
    assert "not found" in tool.edit("dup.txt", "zzz", "b").error


# --------------------------------------------------------------------------
# Sandbox construction
# --------------------------------------------------------------------------


def test_a_missing_root_is_a_config_error_not_a_violation(tmp_path):
    """SandboxViolation must mean "someone tried to escape", nothing else.

    A caller catching it to detect probing must not also catch its own
    misconfiguration.
    """
    with pytest.raises(SandboxConfigError):
        Sandbox(root=tmp_path / "does-not-exist")


def test_a_sandbox_overlapping_the_library_is_refused(tmp_path):
    """kgf reads and validates the knowledge base; it must not be able to write it."""
    library = tmp_path / "lib"
    library.mkdir()
    inner = library / "work"
    inner.mkdir()

    with pytest.raises(SandboxConfigError, match="overlaps the library"):
        Sandbox(root=inner, library_root=library)
    with pytest.raises(SandboxConfigError, match="overlaps the library"):
        Sandbox(root=library, library_root=library)

    sibling = tmp_path / "elsewhere"
    sibling.mkdir()
    assert Sandbox(root=sibling, library_root=library).root == sibling.resolve()


def test_both_capability_flags_default_to_denied(work):
    sandbox = Sandbox(root=work)
    assert sandbox.allow_bash is False
    assert sandbox.allow_network is False
    assert sandbox.allow_private_addresses is False


# --------------------------------------------------------------------------
# The three denial classes
# --------------------------------------------------------------------------


def test_an_ungranted_tool_is_denied_as_not_granted(work):
    result = runtime(work, tools={"Read"}).write("x.txt", "y")
    assert result.decision is Decision.DENIED
    assert DenialReason.NOT_GRANTED.value in result.reason


def test_bash_is_denied_as_opt_in_required_even_when_granted(work):
    result = runtime(work).bash(["python", "-c", "print(1)"])
    assert result.decision is Decision.DENIED
    assert result.reason == DenialReason.BASH_OPT_IN_REQUIRED.value


def test_network_is_denied_as_disabled_even_when_granted(work):
    result = runtime(work).web_fetch("https://example.com")
    assert result.decision is Decision.DENIED
    assert result.reason == DenialReason.NETWORK_DISABLED.value


def test_the_three_denial_reasons_are_distinguishable(work):
    """An operator can flip an opt-in; a persona cannot un-deny a grant.

    Collapsing these would make that difference invisible.
    """
    reasons = {
        runtime(work, tools={"Read"}).write("x", "y").reason,
        runtime(work).bash(["true"]).reason,
        runtime(work).web_fetch("https://example.com").reason,
    }
    assert len(reasons) == 3


def test_a_denial_is_a_result_not_an_exception(work):
    """A permission answer is recoverable; a caller must be able to read it."""
    result = runtime(work, tools=set()).read("inside.txt")
    assert result.decision is Decision.DENIED
    assert not result.allowed


# --------------------------------------------------------------------------
# Bash
# --------------------------------------------------------------------------


def test_bash_runs_with_opt_in(work):
    result = runtime(work, allow_bash=True).bash(["python", "-c", "print('ran')"])
    assert result.ok
    assert "ran" in result.output
    assert result.exit_code == 0


def test_bash_inherits_no_secrets(work, monkeypatch):
    """Verified leaking before this: env={**os.environ} handed over every key."""
    monkeypatch.setenv("GROQ_API_KEY", "sk-must-never-leak")
    result = runtime(work, allow_bash=True).bash(
        ["python", "-c", "import os;print(';'.join(sorted(os.environ)))"]
    )
    assert result.ok
    assert "GROQ_API_KEY" not in result.output
    assert all(name not in result.output for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"))
    assert "KGF_SANDBOX" in result.output


def test_bash_env_allowlist_is_narrow():
    assert "PATH" in BASH_ENV_ALLOWLIST
    assert not any("KEY" in name or "TOKEN" in name or "SECRET" in name for name in BASH_ENV_ALLOWLIST)


def test_bash_refuses_a_command_string(work):
    """argv only. A string would let the grant check and the executed command differ."""
    result = runtime(work, allow_bash=True).bash("ls; rm -rf /")
    assert result.error
    assert "argv must be" in result.error


def test_bash_timeout_is_a_failed_result_not_a_hang(work):
    result = runtime(work, allow_bash=True).bash(
        ["python", "-c", "import time;time.sleep(5)"], timeout_seconds=0.5
    )
    assert not result.ok
    assert "exceeded" in result.error
    assert result.exit_code == -1


def test_bash_reports_a_nonzero_exit(work):
    result = runtime(work, allow_bash=True).bash(["python", "-c", "raise SystemExit(3)"])
    assert result.exit_code == 3


# --------------------------------------------------------------------------
# The address guard
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "::1",
        "::ffff:127.0.0.1",
        "::ffff:10.0.0.1",
        "fe80::1",
        "0.0.0.0",
        "100.64.0.1",
        "64:ff9b::7f00:1",
        "10.0.0.5",
        "192.168.1.1",
        "172.16.0.1",
        "169.254.1.1",
        "224.0.0.1",
    ],
)
def test_non_public_addresses_are_refused(address):
    """Every one of these defeated the CIDR list this replaced.

    IPv4-mapped, link-local (fc00::/7 is unique-local, a different thing),
    unspecified, CGNAT, and NAT64 -- which no `ipaddress` property catches.
    """
    permitted, reason = address_is_permitted(address)
    assert not permitted, f"{address} should be refused"
    assert reason


def test_public_addresses_are_permitted():
    assert address_is_permitted("8.8.8.8")[0]
    assert address_is_permitted("2001:4860:4860::8888")[0]


def test_a_malformed_address_is_refused():
    assert not address_is_permitted("not-an-ip")[0]


def test_the_guard_can_be_opted_out_of():
    """Needed so cap tests can reach a local server; see the cap tests below."""
    assert address_is_permitted("127.0.0.1", allow_private=True)[0]


# --------------------------------------------------------------------------
# WebFetch: guard on, with an injected resolver so no DNS and no traffic
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "resolved",
    ["127.0.0.1", "::ffff:127.0.0.1", "fe80::1", "0.0.0.0", "100.64.0.1", "64:ff9b::7f00:1"],
)
def test_a_public_name_resolving_somewhere_internal_is_refused(work, resolved):
    """The case that matters, and the reason the resolver is injectable.

    Asserting this against the real resolver would need outbound DNS.
    """
    tool = runtime(work, allow_network=True, resolver=lambda host: [resolved])
    result = tool.web_fetch("https://totally-public.example/path")
    assert result.error
    assert "refused" in result.error


def test_one_bad_address_among_several_refuses_the_whole_host(work):
    """A multi-record host must not be reachable via its public record alone."""
    tool = runtime(work, allow_network=True, resolver=lambda host: ["8.8.8.8", "10.0.0.1"])
    assert tool.web_fetch("https://mixed.example/x").error


def test_a_host_that_does_not_resolve_is_refused(work):
    tool = runtime(work, allow_network=True, resolver=lambda host: [])
    assert "did not resolve" in tool.web_fetch("https://nowhere.example/x").error


@pytest.mark.parametrize("url", ["file:///etc/passwd", "data:text/plain,hi", "ftp://x.example/f"])
def test_non_http_schemes_are_refused(work, url):
    """`file:` and `data:` are the live ones, because urllib supports both."""
    tool = runtime(work, allow_network=True, resolver=lambda host: ["8.8.8.8"])
    result = tool.web_fetch(url)
    assert "not permitted" in result.error


def test_the_opener_omits_the_dangerous_handlers():
    """build_opener() APPENDS the defaults, so listing HTTP handlers is not enough.

    Verified: passing only HTTP handlers to build_opener still installs
    FileHandler, FTPHandler and DataHandler -- which is what makes a redirect to
    `file:` a live bypass.
    """
    installed = {type(handler).__name__ for handler in _build_opener().handlers}
    assert not installed & {"FileHandler", "FTPHandler", "DataHandler", "UnknownHandler"}
    assert "HTTPSHandler" in installed


# --------------------------------------------------------------------------
# WebFetch caps, against a local server with the guard opted out
# --------------------------------------------------------------------------


class _Handler(http.server.BaseHTTPRequestHandler):
    """Serves a redirect loop, a redirect to file:, an oversize body, and a page."""

    def do_GET(self):  # noqa: N802 -- BaseHTTPRequestHandler's required name
        path = self.path.split("?", 1)[0]
        if path.startswith("/loop"):
            hop = int(path.rsplit("/", 1)[-1] or 0)
            self.send_response(302)
            self.send_header("Location", f"/loop/{hop + 1}")
            self.end_headers()
        elif path == "/to-file":
            self.send_response(302)
            self.send_header("Location", "file:///etc/passwd")
            self.end_headers()
        elif path == "/big":
            self._body(b"x" * 5000)
        elif path == "/boom":
            self.send_response(503)
            self.end_headers()
        else:
            self._body(b"hello from the test server")

    def _body(self, payload: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):  # noqa: D102 -- silence the default stderr log
        return


@pytest.fixture
def server():
    """A loopback HTTP server. No outbound traffic in any test."""
    httpd = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def local(work, **kwargs) -> ToolRuntime:
    """A runtime that may reach loopback, for the cap tests.

    The guard and the caps are separately configurable precisely so these tests
    can exist: a local server IS loopback, so a cap test cannot also run with the
    address guard on. An earlier plan drafted both as one flag, which made the
    loopback-refusal test and the cap tests mutually exclusive.
    """
    return runtime(work, allow_network=True, allow_private_addresses=True, **kwargs)


def test_a_plain_fetch_succeeds(work, server):
    result = local(work).web_fetch(f"{server}/ok")
    assert result.ok
    assert "hello from the test server" in result.output


def test_the_redirect_cap_is_enforced(work, server):
    """urllib follows redirects itself at a cap of 10, before caller code sees them.

    So this only works because redirects are followed manually.
    """
    result = local(work, max_redirects=3).web_fetch(f"{server}/loop/0")
    assert "redirect cap of 3" in result.error


def test_every_redirect_hop_is_re_validated(work, server):
    """The check that validate-then-urlopen cannot perform.

    An open redirect to `file:` is the classic bypass, and it must be refused at
    the hop where it appears, not at hop 0.
    """
    result = local(work).web_fetch(f"{server}/to-file")
    assert "not permitted" in result.error
    assert "hop 1" in result.error


def test_the_size_cap_errors_rather_than_truncating(work, server):
    """A document cut short but returned as whole is the same failure class as a
    rule cut in half: the consumer cannot tell anything is missing."""
    result = local(work, max_response_bytes=1000).web_fetch(f"{server}/big")
    assert not result.ok
    assert "byte cap" in result.error
    assert not result.output


def test_a_non_2xx_is_an_error(work, server):
    result = local(work).web_fetch(f"{server}/boom")
    assert "HTTP 503" in result.error


# --------------------------------------------------------------------------
# WebSearch
# --------------------------------------------------------------------------


def test_search_uses_the_configured_endpoint(work, server, monkeypatch):
    monkeypatch.setenv(SEARCH_ENDPOINT_ENV, f"{server}/ok?q={{query}}")
    result = local(work).web_search("spring boot")
    assert result.ok
    assert "hello from the test server" in result.output


def test_a_template_without_a_placeholder_is_a_configuration_error(work, monkeypatch):
    monkeypatch.setenv(SEARCH_ENDPOINT_ENV, "https://example.com/search")
    result = local(work).web_search("anything")
    assert SEARCH_ENDPOINT_ENV in result.error


def test_a_blocked_endpoint_is_a_failure_not_an_empty_result(work, server, monkeypatch):
    """A search that silently returns nothing is worse than one that errors:
    the caller cannot distinguish "no results" from "broken"."""
    monkeypatch.setenv(SEARCH_ENDPOINT_ENV, f"{server}/boom?q={{query}}")
    result = local(work).web_search("anything")
    assert result.error
    assert not result.output


def test_the_default_endpoint_is_keyless_and_named():
    assert "{query}" in DEFAULT_SEARCH_ENDPOINT
    assert DEFAULT_SEARCH_ENDPOINT.startswith("https://")


def test_search_denial_propagates_rather_than_becoming_an_error(work):
    result = runtime(work, tools={"WebSearch"}).web_search("x")
    assert result.decision is Decision.DENIED
    assert result.reason


# --------------------------------------------------------------------------
# Grants, against the real graph
# --------------------------------------------------------------------------


def test_an_unknown_agent_has_no_grant(graph):
    assert grant_for(graph, "no-such-agent-at-all") is None


def test_no_grant_ever_exceeds_its_ceiling(graph):
    """The ceiling rule, asserted over every agent rather than a fixture."""
    for agent_id in graph.agents:
        grant = grant_for(graph, agent_id)
        assert grant.tools <= grant.ceiling, agent_id


def test_the_tier_clamp_fires_on_the_measured_number_of_agents(graph, at_pinned_version):
    """18 of 94 edges name a tool beyond the agent's ceiling.

    An earlier version of this module asserted in a comment that it never
    happened. Pinned so the figure cannot rot back to a guess.
    """
    clamped = [
        agent_id
        for agent_id in graph.agents
        if any("clamped" in defect for defect in grant_for(graph, agent_id).defects)
    ]
    if at_pinned_version:
        assert len(clamped) == 18
    else:
        assert clamped


def test_conflicting_tiers_are_intersected_deterministically(graph):
    """One agent carries both readonly and implementation.

    Taking the first edge would let JSON array order decide the grant -- and
    could pick the LOOSER tier, contradicting "a tier may only narrow".
    """
    grant = grant_for(graph, "post-quantum-security-engineer")
    if grant is None or len(grant.tiers) < 2:
        pytest.skip("the library no longer has a multi-tier agent")

    assert len(grant.tiers) == 2
    assert grant.tools == frozenset(
        TIER_TOOLSETS[grant.tiers[0]] & TIER_TOOLSETS[grant.tiers[1]] & grant.ceiling
    )
    assert any("conflicting tiers" in defect for defect in grant.defects)
    assert grant_for(graph, "post-quantum-security-engineer").tools == grant.tools


def test_closure_narrowing_is_a_union_capped_by_the_ceiling(graph):
    """Decision 1. A union can only reduce the ceiling, never exceed it."""
    agent = "spring-boot-microservices"
    bare = grant_for(graph, agent)
    narrowed = grant_for(graph, agent, closure=build_closure(graph, agent))

    assert narrowed.tools <= bare.ceiling
    assert narrowed.narrowed_by


def test_a_closure_with_no_declaring_skill_does_not_narrow(graph):
    """465 of 1034 skills declare no allowed_tools.

    Absence must mean "no extra narrowing", not an empty grant.
    """
    for agent_id in list(graph.agents)[:80]:
        closure = build_closure(graph, agent_id)
        declaring = [
            skill_id
            for skill_id in closure.all_skills
            if (graph.skills.get(skill_id) or {}) and graph.skills[skill_id].raw.get("allowed_tools")
        ]
        if declaring:
            continue
        bare = grant_for(graph, agent_id)
        narrowed = grant_for(graph, agent_id, closure=closure)
        assert narrowed.tools == bare.tools
        return
    pytest.skip("every sampled agent had a declaring skill")


def test_grant_distribution_matches_the_documented_posture(graph, at_pinned_version):
    """The numbers that are the argument for the sandbox."""
    counts = grant_distribution(graph)
    if at_pinned_version:
        assert counts["Read"] == 528
        assert counts["Write"] == 412
        assert counts["Bash"] == 314
        assert counts["Edit"] == 306
    assert counts["Bash"] > len(graph.agents) * 0.5, (
        "a majority of agents carry Bash by the library's own data; if that changes, "
        "the sandbox rationale in tools.py should be revisited"
    )


def test_unknown_tool_names_are_not_granted(graph):
    """A typo in the library must not become a capability."""
    for agent_id in list(graph.agents)[:100]:
        assert grant_for(graph, agent_id).ceiling <= ALL_TOOLS


def test_tier_toolsets_are_narrowing_by_construction():
    """readonly may not contain a mutating tool, whatever the prose says."""
    assert not TIER_TOOLSETS["tool:readonly"] & {"Bash", "Edit", "Write"}
    assert "Write" in TIER_TOOLSETS["tool:web_write"]
    assert not TIER_TOOLSETS["tool:web_write"] & {"Bash", "Edit"}
    assert TIER_TOOLSETS["tool:implementation"] == frozenset(ALL_TOOLS)
