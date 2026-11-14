# session_graph

Turns a Claude Code session transcript into a provenanced knowledge graph,
fused with the git history that session touched.

This is `trust.capsule`'s transcript path (DESIGN.md §4) — the mechanism for
attaching an author agent's context to a repo so a reviewer can check what the
author *believed*, not just what it wrote.

## Why extraction is deterministic

The cookbook pattern for knowledge graphs asks an LLM to emit entities and
relations from prose. That is right for Wikipedia articles and wrong here: a
provenance graph whose nodes are an LLM's reading of a transcript cannot be used
to audit an LLM. So every node and edge in the default pipeline is derived from
transcript structure or from a real git object:

- a `COMMIT` node exists only if `git cat-file -t <sha>` says `commit`
- a `BRANCH` node exists only if `git rev-parse` resolves the ref
- a `DECISION` node carries the question, the chosen option **and the options
  the human rejected**, all read from the `AskUserQuestion` record
- every node's `provenance` holds a transcript `uuid`, a path, or a SHA, and
  `COMMIT`/`BRANCH` nodes carry a `verify` command you can paste into a shell

`--enrich` adds a cookbook-style LLM pass for semantic nodes (`FINDING`,
`REQUIREMENT`, `HYPOTHESIS`). Those are tagged `inferred: true`, drawn with
dashed outlines, and hideable with one click. Observed and inferred facts are
never merged.

## Usage

```bash
# this session, joined to the repo under review
python build_graph.py --latest --repo ../../repo \
    --out session_graph.json --html session_graph.html

# a specific session
python build_graph.py --session <session-id> --repo ../../repo --html g.html

# add LLM-inferred claims (needs ANTHROPIC_API_KEY + anthropic + pydantic)
python build_graph.py --latest --repo ../../repo --enrich
```

Transcripts are discovered under `~/.claude/projects/*/*.jsonl`. No arguments
beyond `--latest` are needed if you just want the current session.

## Ontology

| Node | Meaning |
|---|---|
| `PROMPT` | a human turn |
| `DECISION` | an explicit human choice, with rejected alternatives |
| `TOOL_CALL` | an action the agent took, with ok/error status |
| `FILE` / `ARTIFACT` | read, or written by this session |
| `COMMIT` / `BRANCH` | real git objects, resolved |
| `SKILL` / `AGENT` | capabilities invoked |
| `EXTERNAL` | a URL consulted |
| `FINDING` / `REQUIREMENT` / `HYPOTHESIS` | inferred, `--enrich` only |

| Edge | Meaning |
|---|---|
| `follows` | temporal order between prompts |
| `caused` | prompt → the tool call it led to (via `parentUuid`) |
| `invokes` | tool call → skill or subagent |
| `reads` / `writes` | tool call → file |
| `inspects` | **tool call → commit/branch — the conversation↔git join** |
| `parent_of` / `tip_of` | real git topology |
| `answers` | decision → the question it resolved |
| `cites` | inferred claim → the observed evidence it rests on |

The `inspects` + `parent_of` edges are the point of the whole thing: they make
one graph out of two histories, so you can ask "which commit was this decision
actually looking at?" — and get an answer you can verify.

## Viewer

`session_graph.html` is standalone: inlined data, no CDN, no build step, a
~120-line force layout in vanilla JS. Open it with `file://`.

- click the legend to filter node types
- **Fuse view** shows only the conversation↔git join
- **Replay** scrubs the session forward in time
- click any node for its full provenance
- drag to pin, double-click to release

## `why_lines.py` — per-line provenance

Answers "why does this line exist?" for any file the instrumented agent wrote,
by replaying the session's edit operations and attributing each surviving line
to the operation that introduced it.

```bash
python why_lines.py --list                              # files this session wrote
python why_lines.py --file build_graph.py --line 200     # one line, full chain
python why_lines.py --file ../../DESIGN.md --all         # attribution by region
python why_lines.py --file build_graph.py --line 200 --json

# files the session edited but did not create: seed the replay with the
# pre-edit content from git, so untouched lines are attributed to the L0
# commit layer instead of being guessed at
python why_lines.py --file ../re2283/src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs \
    --line 1442 --session ../../.trust/capsules/re2283-session.claude.jsonl --seed-rev 32258fdb
```

The answer is **layered, and each layer is labelled** rather than blended into
one confident story:

| Layer | Source | Reliability |
|---|---|---|
| `L0 COMMIT` | `git blame` → commit → message → issue | always available once committed; coarse |
| `L1 EDIT` | the exact tool call that wrote the line | **exact**, when a transcript exists |
| `L2 STATED` | the agent's narration around that call | the author's *claim*; flagged `[batch]` when one narration covers several edits |
| `L3 TRIGGER` | the prompt / decision / tool result that preceded it | structural, from `parentUuid` |
| `L4 PRIVATE` | the agent's internal reasoning | **unavailable** |

**L4 is a hard limit.** Claude Code stores `thinking` blocks with empty text and
a signature only — verified in this repo's own session: 36 blocks, 0 characters.
Any tool claiming to recover an agent's private chain of thought from a
transcript is not doing that.

So the question this answers is *"what reason was recorded for this line, and
does it hold up against the code?"* — not *"what truly caused this line?"* The
first is auditable and falsifiable; the second is unknowable. A recorded reason
that the code contradicts is exactly the hidden-defect signal we hunt.

**Integrity checks.** The tool replays tracked operations and compares the
result to the file on disk. If they differ — because a shell redirect or an
external editor also touched the file — it says so and scopes its claims to
tracked operations instead of guessing. Lines it cannot attribute are reported
as untracked, never silently assigned.

## Known limitations

- Path extraction is heuristic: it reads paths out of shell commands and tool
  output, so a `FILE` node means "this path appeared in this session", not "this
  file was definitely opened". `writes` edges are stricter (explicit
  `file_path`, or a redirect target).
- The viewer's JS syntax and inlined JSON are validated, but it has not been
  smoke-tested in a browser in this environment.
- Repulsion is O(n²) per frame. Fine into the low thousands of nodes; beyond
  that it needs a quadtree.

## Other harnesses

`deepcode_convert.py` deterministically re-encodes a deepcode-harness session
log (OpenAI-style records) into this tooling's transcript format, preserving
every uuid/tool_use_id as provenance. It deliberately does **not** copy the
model's `reasoning_content`: the capsule contains what the agent recorded, not
what it privately reasoned.
