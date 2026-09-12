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

**Why Groq, not NVIDIA**: this project originally ran on NVIDIA's free NIM
API, but hit two unresolved platform-side issues there: a `403
"Authorization failed"` bug on Personal-org accounts (listing models worked,
chat completions didn't), and most of the catalog returning `404 "Function
not found for account"` (listed but never actually entitled). Groq's free
tier is an ongoing rate-limited tier (~30 RPM / ~6K TPM / ~14.4K RPD), not a
burnable dollar credit, with no card required -- and every candidate above
was live-tested and confirmed working before being pinned here.

## How a task runs

1. `router_fast` **detects the target language** from the task text itself
   (python/java/web) -- there's no language dropdown; just say "in Java" or
   "a React component" if you want to be explicit.
2. `router_fast` classifies the task as simple or complex (one cheap call).
3. If complex, `reasoner` sketches a short implementation plan first.
4. `primary_coder` generates the code and its tests together, in one call
   (optionally steered by a matched **skill** and/or a chosen **agent**
   persona -- see below).
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

## Skills and Agents (pluggable, sourced entirely from claude-global-library)

Vishwakarma has no starter skills/agents of its own (removed 2026-09-11, per
explicit request) -- all matching is sourced from the **claude-global-library**
(its `skills/{name}/SKILL.md` and `agents/{name}/agent.md` directories, same
flat-file convention). Only a short excerpt of a library entry is ever
injected into a prompt -- never the full multi-thousand-line document -- to
keep API calls within budget. Set `VISHWAKARMA_LIBRARY_PATH` to point at a
different library location, or leave unset to use the sibling
`../claude-global-library` directory automatically. A handful of library
files with pre-existing YAML quirks are skipped with a one-line log summary
rather than crashing the loader.

If you want a local, project-specific skill or agent again later, drop a
`skills/{name}/SKILL.md` or `agents/{name}/agent.md` into this repo -- the
loader picks up either directory automatically if it exists, no code
changes needed.

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
existing project for lightweight keyword-based context), `--skill NAME`,
`--agent NAME`.

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
