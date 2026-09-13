"""Where the MCP surface's posture comes from, and where it deliberately does not.

Posture is `~/.kgf/mcp.json` and nothing else. Not the environment, and never a
call argument. Both exclusions are deliberate and neither is obvious, so both
are recorded here.

Never a call argument. M4 gives every denial a distinct reason, one of which is
"granted by the graph, but Bash requires explicit opt-in". If `allow_bash` were
a tool parameter, that sentence would be escalation instructions: a model reads
the denial and retries with the flag set. A denial has to be safe to show the
party it is denying.

Never the environment. This is the subtler one, and the first draft of the plan
got it wrong. In stdio MCP the CLIENT SPAWNS THE SERVER and supplies its
environment outright -- `StdioServerParameters(..., env=env)`, with `env` a
plain caller parameter. A server reading `KGF_MCP_ALLOW_BASH` would therefore
be reading a value its own launcher chose, and calling that a boundary would be
false.

So the honest scope of these flags is stated rather than implied: they are NOT
a boundary against the process that launches the server. Nothing server-side
can be, since the launcher picks the interpreter, the arguments and the
environment. They are a boundary against THE MODEL DRIVING AN ALREADY-OPEN
SESSION, which is the actual untrusted party in the loop. The launcher is the
human's own tool, configured once, in a file they can read.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

SETTINGS_DIRNAME = ".kgf"
SETTINGS_FILENAME = "mcp.json"

SAFE_DEFAULTS = {
    "sandbox_root": None,
    "allow_bash": False,
    "allow_network": False,
}
"""Deny-by-default, because the graph's own grants are too permissive to trust.

M4 measured it: the closure-wide grant model narrows nothing for 277 of 528
agents and hands a mutating tool to 156 of 528. Graded against
cloud-security-core's least-privilege score, a read-only compose uses 3 of the
8 tools the graph grants -- 0.375 against a >0.8 target. The sandbox root and
these two flags are the whole mitigation, so they start closed.
"""

OVERRIDABLE_BY_ENV = ("library_root",)
"""The only key the environment may set, and why it may.

`library_root` selects which library to READ. Pointing a server at a different
copy of claude-global-library changes what it knows, not what it may do, so a
launcher choosing it is a configuration decision rather than a privilege one.
KGF_LIBRARY_PATH already governs this everywhere else in kgf; honouring it here
keeps one answer to "which library" instead of two.
"""


class McpSettingsError(Exception):
    """Raised when the settings file exists but cannot be used.

    Distinct from a missing file, which is not an error: an absent file means a
    first run and is created with SAFE_DEFAULTS. A malformed one is a
    configuration fault the user must see, because silently falling back to
    defaults would hide a posture they believe they set.
    """


@dataclass(frozen=True)
class McpSettings:
    """One resolved posture for the MCP surface."""

    sandbox_root: Path | None = None
    allow_bash: bool = False
    allow_network: bool = False
    library_root: Path | None = None
    source_path: Path | None = None

    @property
    def has_sandbox(self) -> bool:
        """Whether any tool that touches the filesystem can run at all."""
        return self.sandbox_root is not None

    def describe(self) -> str:
        """One line per setting, for `kgf mcp list`."""
        root = str(self.sandbox_root) if self.sandbox_root else "(none -- filesystem tools unusable)"
        library = str(self.library_root) if self.library_root else "(default: sibling directory)"
        return "\n".join(
            [
                f"  settings file  {self.source_path or '(defaults, no file)'}",
                f"  sandbox root   {root}",
                f"  allow_bash     {self.allow_bash}",
                f"  allow_network  {self.allow_network}",
                f"  library root   {library}",
            ]
        )


def settings_path() -> Path:
    """Where the posture file lives: `~/.kgf/mcp.json`.

    `Path.home()` rather than an env var, because an env var naming the
    location of the file that holds the posture would reintroduce exactly the
    hole the module docstring describes -- a launcher could point the server at
    a file it wrote itself.
    """
    return Path.home() / SETTINGS_DIRNAME / SETTINGS_FILENAME


def write_default_settings(path: Path | None = None) -> Path:
    """Create the settings file with the safe defaults, if it does not exist.

    Returns the path either way. Creating it rather than failing on a missing
    file means a first run works and leaves the user something to edit; the
    defaults deny everything, so the convenience costs no safety.
    """
    target = Path(path) if path is not None else settings_path()
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "$comment": [
            "kgf's own MCP posture. Not read from the environment and not settable",
            "per call: in stdio MCP the client spawns the server and supplies its",
            "environment, so an env var would be a value the launcher chose.",
            "sandbox_root: absolute path the filesystem tools are confined to. Must",
            "  not contain the library. null leaves those tools unusable.",
            "allow_bash: Bash is not confined by the sandbox at all -- cwd is a",
            "  starting directory, not a jail -- so this opt-in is its only control.",
            "allow_network: WebFetch and WebSearch reach the real internet.",
        ],
        **SAFE_DEFAULTS,
    }
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return target


def load_settings(path: Path | None = None, *, create: bool = True) -> McpSettings:
    """Resolve the posture for a server about to start.

    Args:
        path: Override the settings location. For tests; a real server uses
            `settings_path()` so the location cannot be chosen by a launcher.
        create: Write the safe defaults when the file is absent.

    Raises:
        McpSettingsError: if the file exists but is not a JSON object, or a flag
            is not a boolean, or the sandbox root is not absolute. Each of those
            is a posture the user believes they set and does not have.
    """
    target = Path(path) if path is not None else settings_path()
    if not target.exists():
        if create:
            target = write_default_settings(target)
        else:
            return McpSettings(library_root=_library_from_env())

    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise McpSettingsError(f"{target} is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise McpSettingsError(f"{target} holds {type(raw).__name__}, not a settings object")

    for flag in ("allow_bash", "allow_network"):
        if flag in raw and not isinstance(raw[flag], bool):
            raise McpSettingsError(
                f"{target}: {flag} must be true or false, not {raw[flag]!r} -- "
                "a string here would be truthy and would silently grant the opt-in"
            )

    sandbox_root = None
    if raw.get("sandbox_root"):
        sandbox_root = Path(str(raw["sandbox_root"])).expanduser()
        if not sandbox_root.is_absolute():
            raise McpSettingsError(
                f"{target}: sandbox_root must be absolute, got {raw['sandbox_root']!r} -- "
                "a relative path would resolve against whatever directory the launcher used"
            )

    library_root = None
    if raw.get("library_root"):
        library_root = Path(str(raw["library_root"])).expanduser()
    else:
        library_root = _library_from_env()

    return McpSettings(
        sandbox_root=sandbox_root,
        allow_bash=bool(raw.get("allow_bash", False)),
        allow_network=bool(raw.get("allow_network", False)),
        library_root=library_root,
        source_path=target,
    )


def _library_from_env() -> Path | None:
    """KGF_LIBRARY_PATH, if set. The one key the environment may supply."""
    value = os.environ.get("KGF_LIBRARY_PATH")
    return Path(value).expanduser() if value else None
