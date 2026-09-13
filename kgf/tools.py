"""The tool vocabulary, how grants are derived, and the sandbox that bounds them.

Grants come from the graph, which sounds reassuring until you measure what the
graph actually says: 412 of 528 agents are granted Write and 314 are granted
Bash. That is the library's own data, authored as a capability description
rather than as a security policy. So the honest position is stated up front:

  FOR FILE TOOLS, THE SANDBOX IS THE REAL CONTROL.
  FOR BASH, THE OPT-IN IS THE ONLY CONTROL -- the sandbox does not confine it.

That distinction is not a caveat, it is the design. `cwd=` on a subprocess is a
starting directory, not a jail: a child process writes wherever it likes. Read,
Write, Edit, Glob and Grep all pass through Sandbox.resolve() and are genuinely
confined. Bash passes through nothing, which is why it alone requires an
explicit opt-in.

Grant model -- the agent is the principal, and its `tools` list is a CEILING
  A skill's `allowed_tools` and a HAS_TOOL_ACCESS tier may only NARROW that
  ceiling, never widen it. Narrowing is CLOSURE-WIDE UNION: the union of every
  closure skill that declares `allowed_tools`, intersected with the ceiling.

  Measured consequence of that choice, over all 528 agents using
  Closure.all_skills (mandatory + transitive requires + optional):
    277 (52.5%) receive no narrowing at all -- either no closure skill declares
                allowed_tools, or the union already equals the ceiling
    183 (34.7%) get strictly more than an intersection would have granted
    156 (29.5%) gain a MUTATING tool that way (Write 153, Bash 118, Edit 115)

  So the narrowing mechanism is inert for over half the library, and for nearly
  a third it hands over a mutating tool that a skill in the same closure
  withholds. That is why the sandbox carries the weight rather than the grant.

  465 of 1034 skills declare no allowed_tools at all. Absence means no extra
  narrowing, not an empty grant -- reading it the other way would deny almost
  everything for no stated reason.

Tiers are pinned here, with the library's prose as provenance
  HAS_TOOL_ACCESS targets a TIER and no registry defines what a tier contains.
  The definition appears in prose on only 9 of 94 edges (justification 6,
  note 3) -- too thin to parse at runtime, so the three tiers are pinned below.

  Two measured facts that the first draft of this module got wrong:

  18 of 94 edges name a tool BEYOND the agent's own ceiling (Edit on 17, Bash on
  5, all via tool:implementation, concentrated in security auditors and
  pentesters). An earlier comment here claimed this never happened; it happens
  on 18 agents, so the clamp fires in normal operation rather than never.

  tool:readonly does NOT contradict itself. Every tier-DEFINING bracket reads
  [Read, Glob, Grep, WebFetch, WebSearch]. The one readonly bracket containing
  Write is quoting the AGENT's own declared tools, in a note explaining that the
  KG mapped it to readonly "for uniform validation (VR-006 requires exactly 1
  HAS_TOOL_ACCESS per agent)". So 3 agents that declare Write were tiered
  readonly as schema bookkeeping, not as a capability statement -- reported as
  its own defect class rather than as an inconsistency.
"""

from __future__ import annotations

import ipaddress
import os
import re
import socket
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Iterable

from kgf.closure import Closure
from kgf.graph import KnowledgeGraph


class Tool(str, Enum):
    """The eight tools the library's own frontmatter names."""

    READ = "Read"
    GLOB = "Glob"
    GREP = "Grep"
    BASH = "Bash"
    EDIT = "Edit"
    WRITE = "Write"
    WEB_FETCH = "WebFetch"
    WEB_SEARCH = "WebSearch"


ALL_TOOLS = frozenset(tool.value for tool in Tool)

MUTATING_TOOLS = frozenset({Tool.BASH.value, Tool.EDIT.value, Tool.WRITE.value})
NETWORK_TOOLS = frozenset({Tool.WEB_FETCH.value, Tool.WEB_SEARCH.value})

SANDBOXED_PATH_TOOLS = frozenset(
    {Tool.READ.value, Tool.WRITE.value, Tool.EDIT.value, Tool.GLOB.value, Tool.GREP.value}
)
"""Tools whose every path or pattern passes through Sandbox.resolve().

Bash is deliberately absent: it is not confined. Glob and Grep were absent from
this set in the first draft, which is precisely how they came to escape.
"""

TIER_TOOLSETS: dict[str, frozenset[str]] = {
    "tool:readonly": frozenset({"Read", "Glob", "Grep", "WebFetch", "WebSearch"}),
    "tool:web_write": frozenset({"Read", "Glob", "Grep", "Write", "WebFetch", "WebSearch"}),
    "tool:implementation": frozenset(ALL_TOOLS),
}
"""What each HAS_TOOL_ACCESS tier contains, quoted from the edges' own prose:

  readonly       "uses readonly tier tools [Read,Glob,Grep,WebFetch,WebSearch]
                 -- reads context and references; never writes"
  web_write      "uses web-write tier tools [Read,Glob,Grep,Write,WebFetch,
                 WebSearch] -- writes orchestration plans; no Bash/Edit"
  implementation "uses implementation tier tools [Read,Glob,Grep,Bash,Edit,
                 Write,WebFetch,WebSearch] -- executes test suites"

Note the id spelling: schema.json declares ^tool:(readonly|web-write|
implementation)$ with a HYPHEN, while 29 edges target the UNDERSCORE form. kgf
follows the edges, because resolving them is the point.
"""


class Decision(str, Enum):
    """Whether a tool call was permitted."""

    ALLOWED = "allowed"
    DENIED = "denied"


class DenialReason(str, Enum):
    """Why a call was denied. Three classes, because they are three answers.

    NOT_GRANTED is about the graph; the other two are about the sandbox, and a
    caller can act on that difference -- an operator can flip an opt-in, whereas
    a persona that was never granted a tool must choose a different approach.
    """

    NOT_GRANTED = "not granted by the graph"
    BASH_OPT_IN_REQUIRED = "granted by the graph, but Bash requires explicit opt-in"
    NETWORK_DISABLED = "granted by the graph, but network is disabled for this sandbox"


@dataclass(frozen=True)
class ToolGrant:
    """The effective tool set for one agent, and how it was derived."""

    agent: str
    tools: frozenset[str]
    ceiling: frozenset[str]
    tiers: tuple[str, ...] = ()
    narrowed_by: tuple[str, ...] = ()
    defects: tuple[str, ...] = ()

    def permits(self, tool: str) -> bool:
        """Whether this grant includes a tool."""
        return tool in self.tools

    def sorted_tools(self) -> tuple[str, ...]:
        """Granted tools in a stable order, for display and replay."""
        return tuple(sorted(self.tools))


@dataclass(frozen=True)
class ToolResult:
    """The outcome of one tool call, whether or not it ran.

    A denial is a RESULT, not an exception. A persona that asked for something it
    may not have needs to read that and choose differently; raising would turn a
    recoverable permission answer into a failed run. Genuine faults -- a missing
    library, a broken graph -- still raise, and so does a sandbox escape.
    """

    tool: str
    decision: Decision
    output: str = ""
    error: str = ""
    reason: str = ""
    exit_code: int | None = None

    @property
    def allowed(self) -> bool:
        """Whether the call was permitted."""
        return self.decision is Decision.ALLOWED

    @property
    def ok(self) -> bool:
        """Whether the call was permitted AND succeeded."""
        return self.allowed and not self.error


class SandboxViolation(Exception):
    """Raised when a path resolves outside the sandbox root.

    Deliberately an exception rather than a denial result, and deliberately used
    for NOTHING ELSE. A denial says "you may not use this tool", which a caller
    can reasonably work around. This says the caller tried to leave its own
    workdir, and returning a soft failure would let a retry loop keep probing.

    Configuration faults raise SandboxConfigError instead, so a caller catching
    this to detect probing does not also catch its own misconfiguration.
    """


class SandboxConfigError(Exception):
    """Raised when a sandbox cannot be constructed as asked."""


def _normalise_tools(values: object) -> frozenset[str]:
    """Read a tool list from either shape, keeping only known tool names.

    74 of the 569 skills declaring allowed_tools write it as a comma-separated
    string rather than a list, so both forms parse. Unknown names are dropped
    rather than trusted: a typo must not become a capability. (Measured: zero
    unknown names in the live library, so this is defensive, not load-bearing.)
    """
    if values is None:
        return frozenset()
    if isinstance(values, str):
        candidates = [part.strip() for part in values.split(",")]
    elif isinstance(values, (list, tuple, set, frozenset)):
        candidates = [str(item).strip() for item in values]
    else:
        return frozenset()
    return frozenset(name for name in candidates if name in ALL_TOOLS)


def _declared_allowed_tools(graph: KnowledgeGraph, skill_id: str) -> frozenset[str]:
    """A skill's allowed_tools, or empty when it declares none."""
    skill = graph.skills.get(skill_id)
    if skill is None:
        return frozenset()
    return _normalise_tools(skill.raw.get("allowed_tools"))


def grant_for(
    graph: KnowledgeGraph,
    agent_ref: str,
    *,
    closure: Closure | None = None,
) -> ToolGrant | None:
    """Derive the effective tool grant for an agent.

    Args:
        graph: The loaded graph.
        agent_ref: Any reference to the agent, which is the principal.
        closure: The agent's closure. Its skills' `allowed_tools` are UNIONED
            and then intersected with the ceiling. Omit it for the unnarrowed
            ceiling-and-tier grant.

    Returns:
        The ToolGrant, or None if the agent does not exist.
    """
    agent = graph.agent(agent_ref)
    if agent is None:
        return None

    ceiling = _normalise_tools(agent.raw.get("tools"))
    effective = set(ceiling)
    narrowed: list[str] = []
    defects: list[str] = []

    # Intersect EVERY tier edge, not the first. Four agents carry more than one
    # HAS_TOOL_ACCESS edge and post_quantum_security_engineer carries two
    # CONFLICTING tiers (readonly and implementation), so taking the first would
    # let JSON array order decide the grant -- non-deterministic under a library
    # rebuild, and capable of picking the LOOSER tier, which contradicts the rule
    # that a tier may only narrow.
    tiers = tuple(sorted({edge.target for edge in graph.out_edges(agent.id, "HAS_TOOL_ACCESS")}))
    if len(tiers) > 1:
        defects.append(
            f"agent carries conflicting tiers {list(tiers)}; intersecting all of them. "
            f"The library's own VR-006 requires exactly one HAS_TOOL_ACCESS edge per agent"
        )

    for tier in tiers:
        tier_tools = TIER_TOOLSETS.get(tier)
        if tier_tools is None:
            defects.append(f"unknown tool tier {tier}; ignored rather than allowed to widen")
            continue

        widening = tier_tools - ceiling
        if widening:
            # Fires on 18 of 94 edges in the live library -- Edit on 17, Bash on
            # 5, all via tool:implementation, mostly security auditors and
            # pentesters. An earlier version of this comment claimed it never
            # happened. Clamping costs those agents a tool the graph grants them;
            # the agent's own record is the more specific statement and wins.
            defects.append(
                f"tier {tier} names {sorted(widening)} beyond the agent's ceiling; clamped"
            )

        narrowing = ceiling - tier_tools
        if narrowing:
            defects.append(
                f"tier {tier} narrows the ceiling by {sorted(narrowing)}. Note that 3 agents "
                f"were tiered readonly despite declaring Write, recorded by the library as "
                f"'for uniform validation (VR-006)' -- schema bookkeeping, not a capability "
                f"statement, so this narrowing may not reflect intent"
            )

        before = set(effective)
        effective &= tier_tools
        if effective != before:
            narrowed.append(f"tier {tier}")

    if closure is not None:
        declaring = [
            _declared_allowed_tools(graph, skill_id)
            for skill_id in closure.all_skills
            if _declared_allowed_tools(graph, skill_id)
        ]
        if declaring:
            union: set[str] = set()
            for allowed in declaring:
                union |= allowed
            before = set(effective)
            effective &= union
            if effective != before:
                narrowed.append(f"closure union of {len(declaring)} declaring skill(s)")

    return ToolGrant(
        agent=agent.id,
        tools=frozenset(effective),
        ceiling=ceiling,
        tiers=tiers,
        narrowed_by=tuple(narrowed),
        defects=tuple(defects),
    )


@dataclass
class Sandbox:
    """A resolved directory that path-taking tools may not leave.

    Resolution happens once, at construction, and every candidate path is
    resolved and re-checked against it. Resolving matters: a string comparison
    passes `workdir/../../etc/passwd` and follows a symlink straight out, which
    is why the check is on the resolved real path.

    Both capability flags default to False. Deny-by-default is the only
    defensible default for the two controls that exist precisely because the
    graph's own grants are too permissive to rely on.
    """

    root: Path
    allow_bash: bool = False
    allow_network: bool = False
    allow_private_addresses: bool = False
    bash_timeout_seconds: float = 30.0
    max_response_bytes: int = 2 * 1024 * 1024
    max_redirects: int = 3
    fetch_timeout_seconds: float = 15.0
    library_root: Path | None = None
    resolver: Callable[[str], list[str]] | None = None

    def __post_init__(self) -> None:
        root = Path(self.root)
        if not root.is_dir():
            raise SandboxConfigError(f"sandbox root {root} is not a directory")
        self.root = root.resolve()

        if self.library_root is not None:
            library = Path(self.library_root).resolve()
            if self.root == library or library in self.root.parents or self.root in library.parents:
                raise SandboxConfigError(
                    f"sandbox root {self.root} overlaps the library at {library}. kgf reads and "
                    f"validates the knowledge base; a sandbox must never be able to write it"
                )

    def resolve(self, candidate: str | Path) -> Path:
        """Resolve a path and confirm it stays inside the sandbox.

        Raises:
            SandboxViolation: If the resolved path is outside the root. Covers
                `..` traversal and symlinks pointing out, because both are only
                visible after resolution.
        """
        target = Path(candidate)
        combined = target if target.is_absolute() else self.root / target
        resolved = combined.resolve()

        if resolved != self.root and self.root not in resolved.parents:
            raise SandboxViolation(
                f"{candidate!r} resolves to {resolved}, outside the sandbox at {self.root}"
            )
        return resolved

    def contains(self, candidate: Path) -> bool:
        """Whether an already-resolved path lies inside the sandbox."""
        return candidate == self.root or self.root in candidate.parents

    def resolve_host(self, hostname: str) -> list[str]:
        """Resolve a hostname to addresses, through the injectable seam.

        Injectable so the address guard can be tested without real DNS: the case
        that matters is a PUBLIC name whose A record points at an internal
        service, and asserting that against the real resolver would mean
        outbound traffic in the test suite.
        """
        if self.resolver is not None:
            return self.resolver(hostname)
        infos = socket.getaddrinfo(hostname, None)
        return [info[4][0] for info in infos]


NAT64_PREFIX = ipaddress.ip_network("64:ff9b::/96")
"""The well-known NAT64 prefix.

Called out explicitly because NO `ipaddress` property catches it:
`64:ff9b::7f00:1` embeds 127.0.0.1 and reports is_global True. A property-based
check alone therefore lets loopback through by that route.
"""


def address_is_permitted(address: str, *, allow_private: bool = False) -> tuple[bool, str]:
    """Decide whether an IP literal may be connected to.

    Property-based rather than a CIDR list. The literal list first drafted for
    this (127/8, 10/8, 172.16/12, 192.168/16, 169.254/16, ::1, fc00::/7) was
    measured to miss every one of these:

      ::ffff:127.0.0.1   IPv4-mapped loopback
      ::ffff:10.0.0.1    IPv4-mapped private
      fe80::1            link-local -- fc00::/7 is UNIQUE-local, a different thing
      0.0.0.0            reaches localhost on Linux
      100.64.0.1         CGNAT
      64:ff9b::7f00:1    NAT64 to 127.0.0.1, which no property catches

    Args:
        address: An IP literal.
        allow_private: Opt out of the guard, for a caller that genuinely wants
            to reach a local address. Separate from the response caps so the
            cap tests can run against a local server while the guard tests run
            with it on -- the two were mutually exclusive in an earlier draft.

    Returns:
        (permitted, reason). reason is empty when permitted.
    """
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False, f"{address!r} is not a valid IP address"

    if parsed.version == 6:
        mapped = parsed.ipv4_mapped
        if mapped is not None:
            parsed = mapped
        elif parsed in NAT64_PREFIX:
            return False, f"{address} is in the NAT64 prefix {NAT64_PREFIX}, which embeds IPv4"

    if allow_private:
        return True, ""

    # is_global alone is not enough: IPv4 multicast (224.0.0.1) and some reserved
    # ranges report is_global True because Python only excludes the private list
    # there. Neither is a meaningful HTTP target, and allowing them would leave an
    # untested path open for no benefit.
    if parsed.is_multicast or parsed.is_reserved:
        return False, f"{address} is not a valid HTTP target ({_address_character(parsed)})"

    if not parsed.is_global:
        return False, f"{address} is not a global address ({_address_character(parsed)})"
    return True, ""


def _address_character(parsed: ipaddress._BaseAddress) -> str:
    """Name why an address is non-global, for the denial message."""
    for attribute in ("is_loopback", "is_link_local", "is_private", "is_multicast", "is_reserved", "is_unspecified"):
        if getattr(parsed, attribute, False):
            return attribute
    return "not globally routable"


class _ValidatingRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Blocks urllib's internal redirect following.

    `urlopen` follows redirects itself, with HTTPRedirectHandler.max_redirections
    = 10, BEFORE caller code sees any hop. So "follow at most 3, re-checking each"
    cannot be implemented by validating before the call: that yields zero per-hop
    checks and a cap of 10, and one open redirect defeats the whole design.

    This handler refuses to follow anything, so the caller loops manually and
    validates every hop itself.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """Never follow automatically; the caller does it with validation."""
        return None


ALLOWED_SCHEMES = frozenset({"http", "https"})
"""Schemes a fetch may use.

The set matters more than it looks. A default urllib opener carries FileHandler,
FTPHandler AND DataHandler, so `file:` and `data:` are both reachable -- and a
scheme check applied only to the INITIAL url does not stop a
`Location: file:///etc/passwd` on a redirect. An earlier draft of this named
`gopher://`, which urllib does not even support, and omitted the two it does.
"""

DEFAULT_SEARCH_ENDPOINT = "https://html.duckduckgo.com/html/?q={query}"
"""Keyless search endpoint, so WebSearch works without credentials.

Named as a third-party dependency rather than hidden: unversioned, ToS-governed
and silently blockable. Override with KGF_SEARCH_ENDPOINT. A 403, CAPTCHA or
shape change is reported as a tool FAILURE, never as an empty result set -- a
search that silently returns nothing is worse than one that errors.
"""

SEARCH_ENDPOINT_ENV = "KGF_SEARCH_ENDPOINT"

_USER_AGENT = "kgf/1.0 (+knowledge-graph framework; no crawling)"


def _build_opener() -> urllib.request.OpenerDirector:
    """An opener carrying only HTTP(S) handlers, and not following redirects.

    Constructed via OpenerDirector directly, NOT via build_opener(). That
    distinction is the whole point: build_opener() appends the default handler
    set to whatever you pass it, so FileHandler, FTPHandler and DataHandler are
    installed even when you explicitly list only HTTP handlers -- verified. Their
    presence is what turns a redirect to `file:///etc/passwd` from a theoretical
    bypass into a live one.

    UnknownHandler is also omitted, so an unexpected scheme raises rather than
    being quietly dispatched.
    """
    opener = urllib.request.OpenerDirector()
    for handler in (
        urllib.request.HTTPHandler(),
        urllib.request.HTTPSHandler(),
        urllib.request.HTTPDefaultErrorHandler(),
        urllib.request.HTTPErrorProcessor(),
        _ValidatingRedirectHandler(),
    ):
        opener.add_handler(handler)
    return opener


def _validate_url(url: str, sandbox: "Sandbox") -> tuple[str, str, str]:
    """Validate one URL and return (host, validated_ip, error).

    The address checked is the address connected to. urllib hands the HOSTNAME
    down to http.client, which resolves it AGAIN -- two independent lookups, so
    validating a name and then fetching by name leaves a real DNS-rebinding gap.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        return "", "", f"scheme {parsed.scheme!r} is not permitted (allowed: http, https)"
    if not parsed.hostname:
        return "", "", f"{url!r} has no host"

    host = parsed.hostname
    literal = None
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        pass

    candidates = [str(literal)] if literal is not None else sandbox.resolve_host(host)
    if not candidates:
        return host, "", f"{host!r} did not resolve"

    for address in candidates:
        permitted, reason = address_is_permitted(
            address, allow_private=sandbox.allow_private_addresses
        )
        if not permitted:
            return host, "", reason
    return host, candidates[0], ""


BASH_ENV_ALLOWLIST = ("PATH", "SYSTEMROOT", "COMSPEC", "TEMP", "TMP", "LANG", "LC_ALL", "TZ")
"""Environment variables a Bash child may inherit.

An allowlist, not a filter. Inheriting os.environ hands the child every API key
in the process -- verified: a Bash call printed a secret from the parent. And the
consumer's own is_available() gates on exactly those variables, so they are
certainly present.
"""


class ToolRuntime:
    """Executes tool calls under a grant and a sandbox.

    Order is always grant first, sandbox second, so an ungranted tool never
    reaches path handling at all.
    """

    def __init__(self, grant: ToolGrant, sandbox: Sandbox):
        self._grant = grant
        self._sandbox = sandbox

    @property
    def grant(self) -> ToolGrant:
        """The grant this runtime enforces."""
        return self._grant

    @property
    def sandbox(self) -> Sandbox:
        """The sandbox this runtime is confined to."""
        return self._sandbox

    def _deny(self, tool: Tool, reason: DenialReason) -> ToolResult:
        """Build a denial result carrying which of the three classes applied."""
        detail = reason.value
        if reason is DenialReason.NOT_GRANTED:
            granted = ", ".join(self._grant.sorted_tools()) or "empty"
            detail = f"{detail} (effective grant: {granted})"
        return ToolResult(tool=tool.value, decision=Decision.DENIED, reason=detail)

    def _check(self, tool: Tool) -> ToolResult | None:
        """Return a denial if the tool may not run, else None."""
        if not self._grant.permits(tool.value):
            return self._deny(tool, DenialReason.NOT_GRANTED)
        if tool is Tool.BASH and not self._sandbox.allow_bash:
            return self._deny(tool, DenialReason.BASH_OPT_IN_REQUIRED)
        if tool.value in NETWORK_TOOLS and not self._sandbox.allow_network:
            return self._deny(tool, DenialReason.NETWORK_DISABLED)
        return None

    def read(self, path: str) -> ToolResult:
        """Read a file inside the sandbox."""
        denial = self._check(Tool.READ)
        if denial is not None:
            return denial
        resolved = self._sandbox.resolve(path)
        if not resolved.is_file():
            return ToolResult(
                tool=Tool.READ.value, decision=Decision.ALLOWED, error=f"not a file: {path}"
            )
        return ToolResult(
            tool=Tool.READ.value,
            decision=Decision.ALLOWED,
            output=resolved.read_text(encoding="utf-8", errors="replace"),
        )

    def write(self, path: str, content: str) -> ToolResult:
        """Write a file inside the sandbox, creating parent directories."""
        denial = self._check(Tool.WRITE)
        if denial is not None:
            return denial
        resolved = self._sandbox.resolve(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
        return ToolResult(tool=Tool.WRITE.value, decision=Decision.ALLOWED, output=str(resolved))

    def edit(self, path: str, old: str, new: str) -> ToolResult:
        """Replace an exact, unique string in a file inside the sandbox."""
        denial = self._check(Tool.EDIT)
        if denial is not None:
            return denial
        resolved = self._sandbox.resolve(path)
        if not resolved.is_file():
            return ToolResult(
                tool=Tool.EDIT.value, decision=Decision.ALLOWED, error=f"not a file: {path}"
            )

        text = resolved.read_text(encoding="utf-8")
        occurrences = text.count(old)
        if occurrences == 0:
            return ToolResult(
                tool=Tool.EDIT.value, decision=Decision.ALLOWED, error="old text not found"
            )
        if occurrences > 1:
            return ToolResult(
                tool=Tool.EDIT.value,
                decision=Decision.ALLOWED,
                error=f"old text occurs {occurrences} times; it must be unique",
            )
        resolved.write_text(text.replace(old, new), encoding="utf-8")
        return ToolResult(tool=Tool.EDIT.value, decision=Decision.ALLOWED, output=str(resolved))

    def _sandboxed_matches(self, pattern: str) -> tuple[list[Path], str]:
        """Expand a glob pattern and keep only hits inside the sandbox.

        THE fix for this module's worst defect. The first version passed the
        caller's pattern straight to root.glob() and never resolved the hits, so
        glob("../**/*.txt") walked out of the sandbox and grep returned the
        CONTENTS of files outside it -- verified leaking an API key. Because Glob
        and Grep are granted to 528 of 528 agents and appear in all three tiers,
        no narrowing path could have removed that.

        Two layers, deliberately: reject a traversing pattern up front so the
        intent is refused loudly, and resolve every hit anyway so a symlink
        inside the tree cannot smuggle one out.

        Returns:
            (matches, error). error is non-empty when the pattern was refused.
        """
        if ".." in Path(pattern).parts:
            return [], f"pattern {pattern!r} traverses outside the sandbox"

        kept: list[Path] = []
        for candidate in self._sandbox.root.glob(pattern):
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            if resolved.is_file() and self._sandbox.contains(resolved):
                kept.append(resolved)
        return sorted(kept), ""

    def glob(self, pattern: str) -> ToolResult:
        """List files matching a pattern, confined to the sandbox."""
        denial = self._check(Tool.GLOB)
        if denial is not None:
            return denial
        matches, error = self._sandboxed_matches(pattern)
        if error:
            return ToolResult(tool=Tool.GLOB.value, decision=Decision.ALLOWED, error=error)
        listing = "\n".join(str(path.relative_to(self._sandbox.root)) for path in matches)
        return ToolResult(tool=Tool.GLOB.value, decision=Decision.ALLOWED, output=listing)

    def grep(self, pattern: str, glob_pattern: str = "**/*") -> ToolResult:
        """Search file contents for a regular expression, confined to the sandbox."""
        denial = self._check(Tool.GREP)
        if denial is not None:
            return denial
        try:
            expression = re.compile(pattern)
        except re.error as exc:
            return ToolResult(
                tool=Tool.GREP.value, decision=Decision.ALLOWED, error=f"bad pattern: {exc}"
            )

        matches, error = self._sandboxed_matches(glob_pattern)
        if error:
            return ToolResult(tool=Tool.GREP.value, decision=Decision.ALLOWED, error=error)

        hits: list[str] = []
        for path in matches:
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for number, line in enumerate(lines, start=1):
                if expression.search(line):
                    relative = path.relative_to(self._sandbox.root)
                    hits.append(f"{relative}:{number}:{line.strip()}")
        return ToolResult(tool=Tool.GREP.value, decision=Decision.ALLOWED, output="\n".join(hits))

    def bash(self, argv: list[str], timeout_seconds: float | None = None) -> ToolResult:
        """Run a command, argv only, with a minimal environment.

        NOT sandbox-confined. cwd sets a starting directory, not a jail, so a
        child writes wherever it likes -- which is exactly why this tool requires
        an explicit opt-in that the others do not.

        argv only, never a command string, and shell=False always. A string would
        mean the grant controls whether Bash may run while the string controls
        what actually runs, so "ls; rm -rf ~" would pass a check aimed at "ls".

        The child gets NO stdin. Inheriting it is wrong twice over. Under kgf's
        MCP surface the server's stdin is the client's request pipe, so an
        inherited handle would let a granted command read the protocol traffic
        and consume requests the server was meant to answer; and measured on
        Windows the child did not merely see that pipe but blocked during
        interpreter startup against the SDK's pending read on it, so every
        command timed out having never run its first statement. No tool here
        takes stdin input, and a command that waits for input should end rather
        than stall until the timeout.
        """
        denial = self._check(Tool.BASH)
        if denial is not None:
            return denial
        if isinstance(argv, (str, bytes)) or not argv or not all(
            isinstance(item, str) for item in argv
        ):
            return ToolResult(
                tool=Tool.BASH.value,
                decision=Decision.ALLOWED,
                error="argv must be a non-empty list of strings, not a command string",
            )

        bound = (
            timeout_seconds if timeout_seconds is not None else self._sandbox.bash_timeout_seconds
        )
        environment = {name: os.environ[name] for name in BASH_ENV_ALLOWLIST if name in os.environ}
        environment["KGF_SANDBOX"] = str(self._sandbox.root)

        try:
            completed = subprocess.run(
                argv,
                cwd=self._sandbox.root,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=bound,
                shell=False,
                env=environment,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                tool=Tool.BASH.value,
                decision=Decision.ALLOWED,
                error=f"command exceeded {bound}s",
                exit_code=-1,
            )
        except (OSError, ValueError) as exc:
            return ToolResult(
                tool=Tool.BASH.value, decision=Decision.ALLOWED, error=str(exc), exit_code=-1
            )

        return ToolResult(
            tool=Tool.BASH.value,
            decision=Decision.ALLOWED,
            output=completed.stdout,
            error=completed.stderr if completed.returncode != 0 else "",
            exit_code=completed.returncode,
        )

    def web_fetch(self, url: str) -> ToolResult:
        """Fetch a URL over HTTP(S), with the SSRF guard applied to every hop.

        Redirects are followed manually because urllib follows them internally at
        a cap of 10 and before caller code sees any hop -- so validating once and
        calling urlopen would give zero per-hop checks.
        """
        denial = self._check(Tool.WEB_FETCH)
        if denial is not None:
            return denial

        opener = _build_opener()
        current = url
        for hop in range(self._sandbox.max_redirects + 1):
            host, _address, error = _validate_url(current, self._sandbox)
            if error:
                return ToolResult(
                    tool=Tool.WEB_FETCH.value,
                    decision=Decision.ALLOWED,
                    error=f"refused {current!r} at hop {hop}: {error}",
                )

            request = urllib.request.Request(current, headers={"User-Agent": _USER_AGENT})
            try:
                response = opener.open(request, timeout=self._sandbox.fetch_timeout_seconds)
            except urllib.error.HTTPError as exc:
                location = exc.headers.get("Location") if exc.headers else None
                if exc.code in (301, 302, 303, 307, 308) and location:
                    if hop >= self._sandbox.max_redirects:
                        return ToolResult(
                            tool=Tool.WEB_FETCH.value,
                            decision=Decision.ALLOWED,
                            error=f"exceeded the redirect cap of {self._sandbox.max_redirects}",
                        )
                    current = urllib.parse.urljoin(current, location)
                    continue
                return ToolResult(
                    tool=Tool.WEB_FETCH.value,
                    decision=Decision.ALLOWED,
                    error=f"HTTP {exc.code} for {current}",
                )
            except (urllib.error.URLError, OSError, ValueError) as exc:
                return ToolResult(
                    tool=Tool.WEB_FETCH.value,
                    decision=Decision.ALLOWED,
                    error=f"fetch failed: {exc}",
                )

            with response:
                limit = self._sandbox.max_response_bytes
                body = response.read(limit + 1)
            if len(body) > limit:
                # An error, not a truncation. A document cut short but returned
                # as if whole is the same failure class as a rule cut in half:
                # the consumer cannot tell anything is missing.
                return ToolResult(
                    tool=Tool.WEB_FETCH.value,
                    decision=Decision.ALLOWED,
                    error=f"response exceeded the {limit} byte cap",
                )
            return ToolResult(
                tool=Tool.WEB_FETCH.value,
                decision=Decision.ALLOWED,
                output=body.decode("utf-8", errors="replace"),
            )

        return ToolResult(
            tool=Tool.WEB_FETCH.value,
            decision=Decision.ALLOWED,
            error=f"exceeded the redirect cap of {self._sandbox.max_redirects}",
        )

    def web_search(self, query: str) -> ToolResult:
        """Search via the configured endpoint, returning its raw response.

        A blocked, rate-limited or reshaped endpoint is a FAILURE, never an empty
        result set: a search that silently returns nothing is worse than one that
        errors, because the caller cannot distinguish "no results" from "broken".
        """
        denial = self._check(Tool.WEB_SEARCH)
        if denial is not None:
            return denial

        template = os.environ.get(SEARCH_ENDPOINT_ENV, DEFAULT_SEARCH_ENDPOINT)
        if "{query}" not in template:
            return ToolResult(
                tool=Tool.WEB_SEARCH.value,
                decision=Decision.ALLOWED,
                error=(
                    f"{SEARCH_ENDPOINT_ENV} must contain a placeholder for the query; "
                    f"got {template!r}"
                ),
            )

        target = template.replace("{query}", urllib.parse.quote_plus(query))
        result = self.web_fetch(target)
        if not result.allowed:
            return ToolResult(
                tool=Tool.WEB_SEARCH.value, decision=result.decision, reason=result.reason
            )
        if result.error:
            return ToolResult(
                tool=Tool.WEB_SEARCH.value,
                decision=Decision.ALLOWED,
                error=f"search endpoint failed: {result.error}",
            )
        return ToolResult(
            tool=Tool.WEB_SEARCH.value, decision=Decision.ALLOWED, output=result.output
        )


def grant_distribution(graph: KnowledgeGraph) -> dict[str, int]:
    """How many agents' ceilings include each tool.

    Reported because the numbers are the argument for the sandbox: Write 412 of
    528 and Bash 314 of 528 means a majority of selectable personas can reach a
    mutating tool by the library's own data.
    """
    counts = {tool: 0 for tool in sorted(ALL_TOOLS)}
    for agent in graph.agents.values():
        for tool in _normalise_tools(agent.raw.get("tools")):
            counts[tool] += 1
    return counts
