# demo/capsules — agent context handoff

These files are the recorded context of the instrumented agent session that
authored the #2283 re-enactment (branch `ju26-re-2283`, commit `c3791be5`,
labelled guided reproduction).

| File | What it is | Use |
|---|---|---|
| `re2283-session.claude.jsonl` | session transcript, deterministically re-encoded from the harness log by `trust/session_graph/deepcode_convert.py` | `why_lines.py --session <this> ...`, or `entire session attach` to create a checkpoint |
| `re2283-capsule.json` | the provenanced graph built from the transcript (365 nodes, 720 edges) | `recall.py --graph`, the tree viewer, or any consumer of the graph schema |
| `re2283-capsule.html` | standalone graph viewer | open in a browser |

Scope and clearance:

- Contains: the agent's recorded prompts, tool calls, edits, results, and the
  human decisions (with rejected options).
- Does NOT contain: private model reasoning (`reasoning_content` is never
  copied; L4 private is unavailable by design).
- Disclosure review: this capsule was authored for this project and contains
  no credentials or third-party data beyond the public MessagePack-CSharp
  issue text. It was cleared for storage in this repository on 2026-11-14 by
  the project owner.

A fresh agent uses this as the "Sessions" input: it resumes the reasoning
that produced commit `c3791be5` without re-reading the whole conversation —
`why_lines` answers per line, `recall` answers per question, and Entire turns
it into a checkpoint tied to the commit.
