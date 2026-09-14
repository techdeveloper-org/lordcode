# Vishwakarma

A personal, local-only code-generation + auto-test tool powered entirely by
**Groq's free API** (console.groq.com). Not a git repository -- this is for
your own local use only.

## Setup

1. Get a free Groq key at https://console.groq.com/keys (no card required).
2. Copy `.env.example` to `.env` and fill in your key:
   ```
   GROQ_API_KEY=gsk_...
   ```
   (On Windows PowerShell: `$env:GROQ_API_KEY = "gsk_..."`)
3. Install:
   ```
   pip install -e ".[dev]"
   ```

## Model Stack

Every role is an ORDERED LIST of `{provider, model}` candidates in
`models.yaml` -- not a single hardcoded ID. At startup, and again on any
404/410/403 mid-session, the router walks each role's list and settles on
the first candidate whose model is still live on Groq's catalog. Add a
candidate, reorder preference, or edit the pins entirely by editing
`models.yaml` -- never the Python code.

| Role | Candidate chain | Purpose |
|---|---|---|
| Primary coder | `openai/gpt-oss-120b` → `openai/gpt-oss-20b` | Writes code AND its own tests in one call |
| Fast router | `openai/gpt-oss-20b` → `openai/gpt-oss-120b` | Language-detection + simple/complex classification only |
| Reasoner | `qwen/qwen3.6-27b` → `openai/gpt-oss-120b` | Implementation planning (complex tasks) + self-heal failure diagnosis |
| Fallback | `openai/gpt-oss-120b` → `openai/gpt-oss-20b` | Long-context backup |

Every candidate above was live-tested with a real chat completion call
(not just checked against `/v1/models`) and confirmed working -- `gpt-oss-120b`
answered in ~1.2s with clean, correct code; `gpt-oss-20b` in ~0.3s.
`llama-3.1-8b-instant` and `llama-3.3-70b-versatile`, though documented on
Groq's docs site, are NOT in this account's live catalog and were dropped
rather than left as dead candidates. If a pinned model ever disappears,
Vishwakarma falls to the role's next candidate automatically, and only
fails with a clear `ConfigError` (naming the role and how to fix
`models.yaml`) if every candidate for that role is gone.

**Other providers.** `models.yaml` also defines `ollama`, `openai`, `gemini` and
an `anthropic-compatible` block. None is wired to a role, so they cost nothing at
startup -- the router only walks providers a role actually names -- and pointing
a role at one is a config edit rather than a code change.

Two of them need their base URL read carefully, because getting it wrong fails on
the *request shape* rather than on the key, which is a confusing way to fail.
`gemini` points at `/v1beta/openai/` -- Google's OpenAI-compatible layer, not its
native `/v1beta` API -- and `anthropic-compatible` points at a local proxy rather
than at `api.anthropic.com` directly.

Neither `gemini`, `openai` nor `anthropic-compatible` has been live-tested from
this account. That caveat is not boilerplate: this configuration's own history is
two providers (NVIDIA NIM, Cerebras) whose advertised free tiers turned out not to
be entitled.

Ollama is the reason `api_key_required: false` exists. Availability was decided
purely by whether an API key env var was set, so a local Ollama -- which has no
key at all -- was unselectable no matter how it was configured, and "any LLM is
just configuration" was false for exactly the provider that runs without spend.
A keyless provider omits `api_key_env` entirely rather than naming a variable
that means nothing.

None of the three has been live-tested from this account, and that matters here:
this repo's history records two providers whose advertised free tiers turned out
not to be entitled (NVIDIA NIM and Cerebras, both documented in `models.yaml`).
Treat them as correct starting points, not as verified access.

**Why Groq, not NVIDIA**: this project originally ran on NVIDIA's free NIM
API, but hit two unresolved platform-side issues there: a `403
"Authorization failed"` bug on Personal-org accounts (listing models worked,
chat completions didn't), and most of the catalog returning `404 "Function
not found for account"` (listed but never actually entitled). Groq's free
tier is an ongoing rate-limited tier (~30 RPM configured / 8K TPM measured / ~14.4K RPD), not a
burnable dollar credit, with no card required -- and every candidate above
was live-tested and confirmed working before being pinned here.

## How a task runs

1. `router_fast` **detects the target language** from the task text itself
   (python/java/web) -- there's no language dropdown; just say "in Java" or
   "a React component" if you want to be explicit.
2. The knowledge graph **selects an agent** for the engineered prompt and
   assembles a budgeted context from its skill closure -- see below.
3. `router_fast` classifies the task as simple or complex (one cheap call).
   That answer no longer picks a code path: it **prunes a phase graph**. A
   complex task runs `phase:A` (architecture) and `phase:2` (joint blueprint
   validation) before implementation; a simple one prunes both, and the
   remaining phases are rewired onto what survives rather than left dangling.
4. `primary_coder` generates the code and its tests together, in one call,
   steered by the selected agent's persona when the graph is confident enough
   in the match.
5. The tests run in a subprocess appropriate to the target language.
6. On failure, the self-heal loop asks `reasoner` to diagnose the failure
   (given the actual test file and the history of prior failed attempts, so
   it won't repeat a fix that already didn't work), then asks
   `primary_coder` to apply the fix. This repeats up to `--max-attempts`
   (default 3) or 5 minutes wall-clock, whichever comes first.

Every model call, provider fallback, and self-heal attempt is logged
(`VISHWAKARMA_LOG_LEVEL=DEBUG` for more detail) and streamed live to the CLI
console and the web UI's Activity panel, so you always see which
provider/model handled which step.

## Skills and Agents (selected from claude-global-library's knowledge graph)

All knowledge comes from **claude-global-library**, read through `kgf`, the
knowledge-graph framework in this repo. Set `KGF_LIBRARY_PATH` to point at a
different library location, or leave it unset to use the sibling
`../claude-global-library` directory automatically.

Selection is graph-driven, not keyword-driven:

- An agent is **ranked** over the whole catalogue (1034 skills, 528 agents,
  9146 edges), with a confidence and the edge path that justified it. A run
  prints both, so a surprising choice can be traced instead of guessed at.
- Its **skill closure** is expanded from the graph -- mandatory skills, their
  transitive requirements, math delegation, coordinating agents and
  regulations. The median agent needs 4 mandatory skills, not one.
- Context is assembled **section by section within a token budget**, and the
  run records which sections were included and which were dropped. This
  replaced a position-blind 800-character head cut of a single document: on
  `java-spring-boot-microservices` that window ended at offset 796 while the
  coding guidelines began at 8476, so the part that mattered was never sent.
- A persona is applied only when the graph is **confident** in the match. A
  low-confidence match still contributes its context, but does not steer the
  coder -- it is recorded and reported instead.

There is no local skill/agent loader any more. Dropping a
`skills/{name}/SKILL.md` into this repo does nothing; the directories it used
to read never existed in practice, and everything now comes from the graph.
To bias a run toward a particular skill, force it with `--skill NAME`, which
puts that skill at the **front** of the closure so it is first to earn context
budget.

Inspect the graph directly with the `kgf` CLI -- every command is offline, with
no API key and no model call:

```
kgf stats                                   # counts, edge types, load time
kgf route "add a REST endpoint" --limit 3    # who would be selected, and why
kgf closure --agent spring-boot-microservices
kgf context "..." --budget 2000 --intent implement
kgf topology --validate                      # the 44-phase graph vs the library
kgf validate                                 # 0 FATAL, plus every DEFECT found
```

A handful of library files with pre-existing YAML quirks are reported as
defects rather than crashing the loader, and a selected document that cannot be
parsed is dropped from the closure with a recorded defect so the run continues.

List everything available:
```
vishwakarma skills
vishwakarma agents
```

## Usage

CLI (language is auto-detected -- `--lang` only if you want to force it):
```
vishwakarma run "write a function that reverses a linked list"
vishwakarma run "add a REST endpoint for creating an order" --skill spring-boot-api
vishwakarma run "build a login form component" --agent strict-tester
```

Flags: `--lang NAME` (force a stack instead of auto-detecting), `--workdir PATH`,
`--no-heal`, `--max-attempts N`, `--rag --project-dir PATH` (search an
existing project for lightweight keyword-based context), `--skill NAME` (put a
library skill at the front of the closure), `--agent NAME` (skip ranking).

### Recording and replaying a decision

`kgf route` and `kgf context` can write a run manifest: the library version and
per-registry content hashes, the agent selected with its confidence and edge
path, the skill closure, and every context section included or dropped with its
token count.

```
kgf context "add a REST endpoint for creating an order" --budget 2000 --manifest run.json
kgf replay run.json
```

Replay re-derives all of it from the library as it stands now and reports what
changed -- a released version, an unreleased local edit (caught by content hash,
which a version number cannot see), a different selected agent, a smaller
context. It makes **no model call**, so it is cheap enough to run as a drift
gate: exit 0 when nothing changed, 1 when something did, 2 when the manifest
itself cannot be read.

Web app (shares the same engine as the CLI, Tailwind UI with a live
Code / Preview / Tests workspace and a real-time Activity log):
```
uvicorn vishwakarma.webapp.server:app --reload
```
Then open http://127.0.0.1:8000 in a browser.

## Tests

```
pytest tests/
```
Runs fully offline against a mocked LLM client -- no API keys required, no
quota consumed.

## Notes

- No git repository is created or expected for this project.
- The free Groq tier is for personal/prototype use, not production traffic.
- RAG here is a lightweight keyword/file-tree scan, not a vector database --
  appropriate for a personal-sized codebase. Revisit only if the project
  grows large enough that keyword matching starts missing relevant files.
