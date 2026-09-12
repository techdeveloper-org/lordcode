"""Milestone 8: split a complex task's file generation across multiple
parallel coder calls, instead of one single call bounded by
generate.MAX_CODER_TOKENS.

Real motivation, not a speculative optimization: generate.py's own code
comment already documents that Groq's gpt-oss models spend part of their
completion budget on an internal reasoning pass before emitting the
structured JSON payload, and request_files_from_coder's own error message
says "if this looks truncated, the task may need to be split into smaller
pieces" -- a complex task whose total file content exceeds one 8000-token
completion fails with a truncated-JSON GenerationError today. Splitting the
coder's work across scoped calls, each with its own fresh token budget, is
a correctness fix.

No wall-clock speedup is claimed: AgentCoordinator's dispatcher thread still
serializes every spawned process's call_role through the one shared 30rpm
RateLimiter (see engine/agent_runtime.py). The benefit is enabling
generation of file sets that would not fit in a single completion.

Simple tasks are entirely unaffected -- this module is only ever invoked
for complexity == "complex" tasks whose manifest is large enough to be
worth splitting; the single-call generate() path is untouched.

Milestone 9 (dependency-aware parallel generation) extends this module
with two additions, both grounded in the manifest's own existing `path`/
`responsibility` fields -- no new LLM call, no AST parsing, no Jira-style
dependency graph:

1. Dependency-aware grouping -- `_partition_manifest` keeps a file with its
   naming-convention-implied counterpart (e.g. `test_models.py` with
   `models.py`) in the same group, via union-find clustering, instead of
   splitting them apart by pure sequential position.
2. Sequential content-passing for cross-group dependencies -- when one
   cluster is too large to fit in a single group, it is split at internal
   dependency-tier boundaries (never mid-tier), and `generate_parallel` runs
   in waves: a group depending on an earlier-wave group receives that
   group's actual generated file content in its own prompt, not just the
   manifest's one-line description.

A zero-dependency manifest (the common case) produces exactly Milestone 8's
original behavior: one wave, fully simultaneous, no dependency content.
"""

from __future__ import annotations

from vishwakarma.engine.agent_runtime import AgentCoordinator, AgentSpec, RemoteLLM
from vishwakarma.engine.calling import OnEvent, noop_event
from vishwakarma.engine.generate import (
    FileSpec,
    GeneratedArtifact,
    GenerationError,
    MAX_CODER_TOKENS,
    _build_system_prompt,
    _extract_json,
    _parse_files_json,
)
from vishwakarma.engine.reasoning_utils import strip_reasoning_trace
from vishwakarma.engine.self_heal import _truncate
from vishwakarma.llm_client import LLMClient
from vishwakarma.plugins import Skill, SubAgent
from vishwakarma.router import Router

PARALLEL_FILE_THRESHOLD = 4
"""Manifest must have more files than this to engage the parallel path;
otherwise the caller falls back to generate.generate()'s single call."""

MAX_FILES_PER_GROUP = 3
MAX_PARALLEL_GROUPS = 4

MAX_DEPENDENCY_CONTENT_CHARS = 2000
"""Per-file cap when including an already-generated dependency's content in
a later-wave group's prompt -- mirrors self_heal.py's
MAX_FILE_CHARS_IN_PROMPT precedent for the same "already-generated file
content in a prompt" risk, so a wave-2+ group depending on several large
files can't blow the coder call's own input budget."""

_MANIFEST_SYSTEM_PROMPT = (
    "You are planning the file structure for ONE coding task before any "
    "content is written. Respond with ONLY a JSON object of the exact shape "
    '{"files": [{"path": "relative/file/path", "responsibility": "one-line description"}]} '
    "-- no prose, no markdown code fences, no explanation outside the JSON. "
    "List every file the implementation genuinely needs, including its tests."
)

_MIN_CROSS_REFERENCE_STEM_LENGTH = 3
"""Basenames shorter than this are never used as the responsibility
cross-reference signal -- too short to trust without producing spurious
matches (e.g. "a.py")."""

_TEST_PREFIX = "test_"
_TEST_SUFFIXES = ("_test", ".test", "test")


def _persona_plan_file_manifest(remote_llm: RemoteLLM, task: str, language: str, context: str | None) -> str:
    """Spawned-agent persona that plans a structured file manifest.

    Takes the same context (which already folds in the architect's own
    blueprint for complex tasks) that generate_parallel()/generate() are
    themselves scoped against, so the manifest and the blueprint can't
    independently disagree on what files exist.
    """
    user_content = f"Task: {task}\n\nTarget language/stack: {language}."
    if context:
        user_content += f"\n\nApproved context/blueprint:\n{context}"
    messages = [
        {"role": "system", "content": _MANIFEST_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    raw = remote_llm.call_role(
        "fallback_long_context", "plan file manifest", messages,
        light_reasoning=True, temperature=0.2, max_tokens=1000,
    )
    return strip_reasoning_trace(raw)


def _parse_file_manifest(raw: str) -> list[dict]:
    """Validate and parse the manifest persona's JSON output.

    Raises:
        GenerationError: If the result isn't a non-empty list of dicts each
            with string "path"/"responsibility" keys.
    """
    try:
        parsed = _extract_json(raw)
    except GenerationError:
        parsed = None

    valid = (
        isinstance(parsed, dict)
        and isinstance(parsed.get("files"), list)
        and len(parsed["files"]) > 0
        and all(
            isinstance(item, dict)
            and isinstance(item.get("path"), str)
            and isinstance(item.get("responsibility"), str)
            for item in parsed["files"]
        )
    )
    if not valid:
        raise GenerationError("File manifest planning did not produce a valid JSON list")
    return parsed["files"]


def plan_file_manifest(
    task: str,
    language: str,
    context: str | None,
    router: Router,
    client: LLMClient,
    on_event: OnEvent = noop_event,
) -> list[dict]:
    """Plan a structured file manifest for a complex task.

    Raises:
        GenerationError: If the manifest persona's output can't be parsed
            into a valid, non-empty manifest.
    """
    coordinator = AgentCoordinator(router, client, on_event=on_event)
    try:
        process, agent_id = coordinator.spawn_agent(_persona_plan_file_manifest, (task, language, context))
        process.join()
        raw = coordinator.await_result(agent_id)
    finally:
        coordinator.stop()

    manifest = _parse_file_manifest(raw)
    on_event({"type": "file_manifest_planned", "file_count": len(manifest)})
    return manifest


def _stem_and_kind(path: str) -> tuple[str, bool]:
    """Return (normalized_stem, is_test) for a file path.

    Only the basename matters (a leading directory segment like `tests/` is
    ignored for stem comparison). Strips a small fixed set of test markers:
    a leading `test_`, or a trailing `_test`/`.test`/`Test` suffix on the
    stem. Case is deliberately preserved (not lowercased) -- two genuinely
    different classes that differ only by case are a real, if rare,
    possibility, accepted as a known limitation rather than silently
    "fixed" by lowercasing away a real distinction.
    """
    basename = path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    stem = basename.rsplit(".", 1)[0] if "." in basename else basename

    if stem.startswith(_TEST_PREFIX):
        return stem[len(_TEST_PREFIX):], True
    for suffix in _TEST_SUFFIXES:
        if stem.lower().endswith(suffix) and len(stem) > len(suffix):
            return stem[: -len(suffix)], True
    return stem, False


def _slug_appears_in_text(slug: str, text: str) -> bool:
    """Word-boundary-guarded substring check.

    Mirrors this codebase's own knowledge-graph rule set
    (`kg-validation-integrity.md`'s `_slug_appears_in_text` fix): a plain
    substring test alone would spuriously fire on a short basename like
    `cart` appearing inside unrelated prose such as "the shopping_cart_utils
    helper" -- a match only counts if the character immediately before and
    after its position in `text` (if any) is not alphanumeric.
    """
    start = text.find(slug)
    if start == -1:
        return False
    end = start + len(slug)
    before_ok = start == 0 or not text[start - 1].isalnum()
    after_ok = end == len(text) or not text[end].isalnum()
    return before_ok and after_ok


def _extract_manifest_dependencies(manifest: list[dict]) -> dict[str, set[str]]:
    """Build a {path: {paths it depends on}} graph from cheap, existing signals.

    Two signals only, both computed from the manifest's existing `path`/
    `responsibility` fields -- no new LLM call, no AST parsing (the files
    don't exist yet at manifest-planning time):

    1. Naming convention: a test file (per `_stem_and_kind`) depends on its
       same-stem implementation file, never the reverse.
    2. Responsibility cross-reference: file A depends on file B if B's
       basename (word-boundary-guarded, at least 3 chars) appears in A's
       responsibility text.

    Returns an empty dict for a manifest where neither signal fires (the
    common case) -- this must reduce to exactly Milestone 8's behavior.
    """
    dependencies: dict[str, set[str]] = {}

    def add_edge(a: str, b: str) -> None:
        if a == b:
            return
        dependencies.setdefault(a, set()).add(b)

    stem_groups: dict[str, list[tuple[str, bool]]] = {}
    for item in manifest:
        path = item["path"]
        stem, is_test = _stem_and_kind(path)
        stem_groups.setdefault(stem, []).append((path, is_test))

    for members in stem_groups.values():
        impls = [p for p, is_test in members if not is_test]
        tests = [p for p, is_test in members if is_test]
        for test_path in tests:
            for impl_path in impls:
                add_edge(test_path, impl_path)

    basenames: dict[str, str] = {}
    for item in manifest:
        path = item["path"]
        basename = path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        stem = basename.rsplit(".", 1)[0] if "." in basename else basename
        if len(stem) >= _MIN_CROSS_REFERENCE_STEM_LENGTH:
            basenames[path] = stem

    for item in manifest:
        a_path = item["path"]
        responsibility = item.get("responsibility", "")
        for b_path, b_stem in basenames.items():
            if b_path == a_path:
                continue
            if _slug_appears_in_text(b_stem, responsibility):
                add_edge(a_path, b_path)

    return dependencies


class _DisjointSet:
    """Minimal union-find over a fixed set of items."""

    def __init__(self, items: list[str]):
        self._parent = {item: item for item in items}

    def find(self, x: str) -> str:
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[ra] = rb


def _tarjan_scc(nodes: list[str], edges: dict[str, set[str]]) -> list[list[str]]:
    """Iterative Tarjan's SCC algorithm restricted to `nodes`.

    Only edges between two members of `nodes` are followed -- edges to
    files outside this set (e.g. a different cluster) are ignored, since
    this is always called on one cluster's own internal subgraph.
    """
    node_set = set(nodes)
    index_counter = [0]
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    result: list[list[str]] = []

    def neighbors(n: str) -> list[str]:
        return [d for d in edges.get(n, ()) if d in node_set]

    for start in nodes:
        if start in indices:
            continue
        work: list[tuple[str, int]] = [(start, 0)]
        indices[start] = lowlink[start] = index_counter[0]
        index_counter[0] += 1
        stack.append(start)
        on_stack.add(start)

        while work:
            node, i = work[-1]
            succ = neighbors(node)
            if i < len(succ):
                work[-1] = (node, i + 1)
                nxt = succ[i]
                if nxt not in indices:
                    indices[nxt] = lowlink[nxt] = index_counter[0]
                    index_counter[0] += 1
                    stack.append(nxt)
                    on_stack.add(nxt)
                    work.append((nxt, 0))
                elif nxt in on_stack:
                    lowlink[node] = min(lowlink[node], indices[nxt])
            else:
                work.pop()
                if work:
                    parent = work[-1][0]
                    lowlink[parent] = min(lowlink[parent], lowlink[node])
                if lowlink[node] == indices[node]:
                    component: list[str] = []
                    while True:
                        w = stack.pop()
                        on_stack.discard(w)
                        component.append(w)
                        if w == node:
                            break
                    result.append(component)
    return result


def _depth_tiers(cluster_paths: list[str], dependencies: dict[str, set[str]]) -> list[list[str]]:
    """Split one oversized cluster into ordered dependency-depth tiers.

    Computes strongly connected components (SCCs) of the cluster's own
    internal dependency edges first -- any cycle among the responsibility-
    cross-reference heuristic's free-text-derived edges (a real
    possibility, since that signal isn't provably acyclic the way the
    naming-convention signal is) collapses into one SCC, generalizing the
    existing 2-node mutual-dependency tie rule to an SCC of any size. Depth
    is then computed over the SCC condensation graph, which is always
    acyclic by construction, so it always terminates regardless of how
    many or how large the cycles in the original per-file graph were.

    Returns tiers in ascending depth order; files within a tier keep their
    manifest (cluster) order.
    """
    sccs = _tarjan_scc(cluster_paths, dependencies)
    file_to_scc = {f: i for i, comp in enumerate(sccs) for f in comp}

    cluster_set = set(cluster_paths)
    scc_deps: list[set[int]] = [set() for _ in sccs]
    for f in cluster_paths:
        for dep in dependencies.get(f, ()):
            if dep in cluster_set:
                si, sj = file_to_scc[f], file_to_scc[dep]
                if si != sj:
                    scc_deps[si].add(sj)

    depth_cache: dict[int, int] = {}

    def depth(i: int) -> int:
        if i in depth_cache:
            return depth_cache[i]
        deps = scc_deps[i]
        d = 0 if not deps else 1 + max(depth(j) for j in deps)
        depth_cache[i] = d
        return d

    for i in range(len(sccs)):
        depth(i)

    max_depth = max(depth_cache.values()) if depth_cache else 0
    tiers: list[list[str]] = [[] for _ in range(max_depth + 1)]
    for f in cluster_paths:
        tiers[depth_cache[file_to_scc[f]]].append(f)
    return [tier for tier in tiers if tier]


def _partition_manifest(manifest: list[dict]) -> list[list[str]]:
    """Chunk a manifest's file paths into groups for parallel generation.

    Dependency-aware: files connected by a detected dependency edge (see
    _extract_manifest_dependencies) are clustered together via union-find
    and packed as one unit whenever the cluster fits within the target
    group size. A cluster too large to fit is split at internal
    dependency-tier boundaries (see _depth_tiers) -- never mid-tier -- so a
    genuine cross-group dependency can still arise and be sequenced by
    _compute_group_waves/generate_parallel's wave logic.

    For a manifest with no detected dependencies (the common case), this
    produces byte-for-byte the same groups as Milestone 8's original
    sequential chunking.
    """
    paths = [item["path"] for item in manifest]
    dependencies = _extract_manifest_dependencies(manifest)

    dsu = _DisjointSet(paths)
    for a, deps in dependencies.items():
        for b in deps:
            dsu.union(a, b)

    cluster_of: dict[str, list[str]] = {}
    cluster_order: list[str] = []
    for p in paths:
        root = dsu.find(p)
        if root not in cluster_of:
            cluster_of[root] = []
            cluster_order.append(root)
        cluster_of[root].append(p)

    group_size = max(MAX_FILES_PER_GROUP, -(-len(paths) // MAX_PARALLEL_GROUPS))

    packing_units: list[list[str]] = []
    for root in cluster_order:
        cluster_paths = cluster_of[root]
        if len(cluster_paths) <= group_size:
            packing_units.append(cluster_paths)
        else:
            packing_units.extend(_depth_tiers(cluster_paths, dependencies))

    groups: list[list[str]] = []
    for unit in packing_units:
        if groups and len(groups[-1]) + len(unit) <= group_size:
            groups[-1].extend(unit)
        else:
            groups.append(list(unit))
    return groups


def _compute_group_waves(
    groups: list[list[str]],
    dependencies: dict[str, set[str]],
    on_event: OnEvent = noop_event,
) -> list[list[int]]:
    """Assign each group to a wave, based on cross-group dependency edges.

    A group's wave is 1 + max(wave of every OTHER group it depends on), or
    0 if it depends on no other group. A cross-group cycle is structurally
    unreachable given _partition_manifest's clustering (any edge-connected
    pair is always merged into one cluster, so a cross-group edge can only
    point at an earlier-completed dependency, never a mutual one) -- but is
    defensively detected and falls back to putting every group in wave 0
    rather than recursing forever, logged via on_event.
    """
    n = len(groups)
    group_of: dict[str, int] = {p: gi for gi, paths in enumerate(groups) for p in paths}

    group_deps: list[set[int]] = [set() for _ in range(n)]
    for gi, paths in enumerate(groups):
        for p in paths:
            for dep in dependencies.get(p, ()):
                gj = group_of.get(dep)
                if gj is not None and gj != gi:
                    group_deps[gi].add(gj)

    wave_of: dict[int, int] = {}
    visiting: set[int] = set()
    cycle_detected = False

    def wave(gi: int) -> int:
        nonlocal cycle_detected
        if gi in wave_of:
            return wave_of[gi]
        if gi in visiting:
            cycle_detected = True
            return 0
        visiting.add(gi)
        deps = group_deps[gi]
        w = 0 if not deps else 1 + max(wave(gj) for gj in deps)
        visiting.discard(gi)
        wave_of[gi] = w
        return w

    for gi in range(n):
        wave(gi)

    if cycle_detected:
        on_event({"type": "dependency_cycle_fallback", "group_count": n})
        wave_of = {gi: 0 for gi in range(n)}

    max_wave = max(wave_of.values()) if wave_of else 0
    waves: list[list[int]] = [[] for _ in range(max_wave + 1)]
    for gi in range(n):
        waves[wave_of[gi]].append(gi)
    return waves


def _persona_generate_subset(
    remote_llm: RemoteLLM,
    task: str,
    language: str,
    manifest: list[dict],
    file_paths: list[str],
    context: str | None,
    skill: Skill | None,
    subagent: SubAgent | None,
    dependency_content: dict[str, str] | None = None,
) -> str:
    """Spawned-agent persona that generates content for one subset of files.

    Reuses generate._build_system_prompt unchanged, so skill/subagent
    overrides are honored identically to the single-call path. Returns the
    raw, unstripped response text -- matching generate.request_files_from_coder's
    own primary_coder-role convention (generate.py has no reasoning_utils
    import at all), not other personas' fallback_long_context-role
    convention of stripping reasoning traces.

    When dependency_content is None/empty (every wave-0 group, and every
    group in a manifest with no detected dependencies), the prompt is
    byte-for-byte identical to Milestone 8's original.
    """
    system_prompt = _build_system_prompt(language, skill, subagent)
    manifest_block = "\n".join(f"- {item['path']}: {item['responsibility']}" for item in manifest)
    user_content = (
        f"{task}\n\nFull project file manifest:\n{manifest_block}\n\n"
        f"Generate content for ONLY these files: {', '.join(file_paths)} -- "
        "reference the other manifest entries for cross-file consistency "
        "(shared imports/interfaces) but do not emit their content."
    )
    if context:
        user_content += f"\n\nRelevant existing project context:\n{context}"
    if dependency_content:
        dep_block = "\n\n".join(
            f"--- {path} ---\n{_truncate(content, MAX_DEPENDENCY_CONTENT_CHARS)}"
            for path, content in dependency_content.items()
        )
        user_content += (
            "\n\nThe following files this subset depends on have ALREADY been "
            "generated -- use their real content for cross-file consistency "
            "(actual class/function names, actual imports), not the one-line "
            f"manifest description:\n{dep_block}"
        )

    return remote_llm.call_role(
        "primary_coder", "generate code subset (Milestone 8)",
        [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}],
        temperature=0.2, max_tokens=MAX_CODER_TOKENS,
    )


def generate_parallel(
    task: str,
    language: str,
    manifest: list[dict],
    groups: list[list[str]],
    router: Router,
    client: LLMClient,
    context: str | None = None,
    skill: Skill | None = None,
    subagent: SubAgent | None = None,
    on_event: OnEvent = noop_event,
) -> GeneratedArtifact:
    """Generate a complex task's files across N parallel coder calls, in waves.

    Raises:
        GenerationError: If any group's coder response can't be parsed, or
            if two groups (in the same or different waves) produce a
            duplicate file path.
    """
    dependencies = _extract_manifest_dependencies(manifest)
    on_event({"type": "dependency_graph_computed", "edge_count": sum(len(v) for v in dependencies.values())})

    paths = [item["path"] for item in manifest]
    group_size = max(MAX_FILES_PER_GROUP, -(-len(paths) // MAX_PARALLEL_GROUPS))
    for group in groups:
        if len(group) > group_size:
            on_event({"type": "dependency_cluster_exceeds_group_size", "cluster_size": len(group), "paths": group})
    if len(groups) > MAX_PARALLEL_GROUPS:
        on_event(
            {"type": "parallel_group_count_exceeded_target", "group_count": len(groups), "max_parallel_groups": MAX_PARALLEL_GROUPS}
        )

    waves = _compute_group_waves(groups, dependencies, on_event=on_event)

    coordinator = AgentCoordinator(router, client, on_event=on_event)
    accumulated_files: dict[str, FileSpec] = {}
    seen_paths: dict[str, str] = {}
    try:
        for wave_index, wave in enumerate(waves):
            specs = []
            for gi in wave:
                group_paths = groups[gi]
                deps_needed = {
                    dep
                    for p in group_paths
                    for dep in dependencies.get(p, ())
                    if dep not in group_paths and dep in accumulated_files
                }
                dependency_content = (
                    {dep: accumulated_files[dep].content for dep in deps_needed} if deps_needed else None
                )
                specs.append(
                    AgentSpec(
                        label=f"group-{gi}",
                        persona_fn=_persona_generate_subset,
                        args=(task, language, manifest, group_paths, context, skill, subagent, dependency_content),
                    )
                )

            raw_by_label = coordinator.run_agents_parallel(specs)
            for label, raw in raw_by_label.items():
                group_files = _parse_files_json(raw)
                for file_spec in group_files:
                    if file_spec.path in seen_paths:
                        raise GenerationError(
                            f"Duplicate file path '{file_spec.path}' produced by both "
                            f"{seen_paths[file_spec.path]} and {label}"
                        )
                    seen_paths[file_spec.path] = label
                    accumulated_files[file_spec.path] = file_spec
                on_event({"type": "parallel_generation_group_completed", "label": label, "file_count": len(group_files)})
            on_event({"type": "generation_wave_completed", "wave": wave_index, "group_count": len(wave)})
    finally:
        coordinator.stop()

    return GeneratedArtifact(files=list(accumulated_files.values()))
