# DESIGN — `trust`: Autonomous AI Code Trust System

> **Implementation status.** This file records the target architecture, not
> a list of completed features. The working prototype currently includes base
> resolution, four assumption classes, a provenance graph for our guided #2283
> reproduction, SQLite recall, an exploratory comparison, and a #2297 repro.
> Fingerprinting, autonomous experiment routing, MCP, a general CLI, and a
> decision dashboard remain proposals. See [CONCEPT_CARD.md](CONCEPT_CARD.md)
> and [TWO_MINUTE_DEMO.md](TWO_MINUTE_DEMO.md) for the challenge deliverable.

**Challenge:** How can AI review code made by AI so that humans can trust it?
**Target:** `junction26-messagepack-csharp`, four agentic branches sharing base
`32258fdb` ("Bump PolySharp from 1.14.1 to 1.15.0").
**Backlog:** `sprints.md` (unchanged; this doc is the architecture that delivers it).

> **What is under review.** The library is HUMAN code (first commit 2017-02-13,
> 3,536 commits). The challenge input is the four **AI-made patches** — one
> commit per branch. The system reviews the patch; the human base is the oracle
> that makes assumption checks decidable ("did this belief exist before the
> agent arrived?"). Agent attribution from style alone is explicitly out of
> scope: the four commits carry no agent provenance, and naming an agent from
> unlabeled samples would violate the trust contract. See §5.1 for the
> re-enactment that measures what recorded context is worth.

> **Base-commit note.** `origin/develop` does not exist in this fork, so
> `git merge-base <branch> origin/develop` fails and a naive fallback to
> `master` yields `524fd55e` — a commit two steps too far back. Diffing from
> there attributes two pre-existing dependency commits to the agents. The
> brief's own file counts (4, 4, 28, 237) are the oracle: they match only
> against `32258fdb`. Base resolution is therefore a recorded, verified
> assumption in this system, never a silent fallback. See §5.0 — this error
> happened to us, and catching it is the demo's opening beat.

---

## 1. The Trust Contract

This is the concept the demo defends. Everything below serves it.

> **The system never asks you to believe it.** Every claim is either (a) a
> reproducible experiment you can re-run with one command, or (b) explicitly
> labeled an unverified hypothesis. There is nothing in between.

Three enforced properties:

1. **Proposer / verifier separation.** The LLM proposes hypotheses and *writes*
   experiments. Only *executed code* produces verdicts. An LLM has no code path
   by which it can promote a hypothesis to a finding.
2. **Provenance on every fact.** Every assertion carries an evidence ID that
   resolves to a git object, a `file:line`, an issue URL, or an execution log.
   No unsourced claims enter a report.
3. **Falsifiable output.** Findings ship as standalone runnable tests. The
   human's trust check is `dotnet test`, not reading prose.
4. **Assumptions are reviewed, not just output.** A hallucination is an
   assumption that was never checked. The author's assumptions are captured as
   explicit propositions and each one is attacked against the repo. An
   assumption that survives is a documented warrant; one that falls is a
   hidden defect that no test in the repo covers.

The reviewer produces evidence for a human decision. A compile probe can
falsify a compatibility premise, but it does not by itself prove every emitted
consumer configuration or authorize a requirement change. When original author
context is unavailable, the system can check implications visible in code and
documentation without claiming to know the author's reasoning.

---

## 2. Stack (decided)

| Layer | Choice | Why |
|---|---|---|
| Orchestrator | Python 3.11+ | Fastest to build; official MCP SDK; LLM SDKs |
| C# parsing | `tree-sitter-c-sharp` | Real ASTs without needing .NET; pip-installable |
| Build/execute | `dotnet` CLI subprocess | .NET 8 SDK (`8.0.4xx`, per `global.json`) |
| Memory | SQLite + FTS5 (stdlib) | Zero deps; full-text evidence retrieval |
| Memory (challenge track) | **MongoDB Atlas** | `trust/tree/mongo_tree.py`: nodes/edges/traversals collections; `$graphLookup` traversal paths, aggregation token ledger. Same JSON out as the offline tree; `MONGO_URI` selects the backend |
| Patterns | YAML | Declarative, shareable, reviewable by humans |
| CLI | Typer | `trust hunt . --base main` |
| LLM | Claude (Opus 5 / Sonnet 5.5) | Hypothesis authoring + experiment synthesis |

Fallback if the tree-sitter grammar won't install: regex heuristics behind the
same `Fingerprinter` interface. The interface is the seam; the parser is not.

**Tooling:** .NET 8 SDK is installed on the demo machine, though `dotnet` may
need its explicit Windows path. The generated repro still depends on a working
test host and should be prechecked before a live presentation.

---

## 3. Pipeline

```
repo + base..target
      |
 [1] ingest ---------> ChangeSet        (hunks, symbols, tests, deps)
      |
 [2] fingerprint ----> Fingerprint[]    (8 dimensions, AST-derived)
      |
 [3] match ----------> Pattern[]        (fingerprint -> bug class -> strategy)
      |
 [4] archaeology ----> Evidence[]       (prior fixes, reverts, churn, fragility)
      |
 [5] plan -----------> Hypothesis[]     (ranked, each citing evidence IDs)
      |
 [6] route ----------> Experiment[]     <== THE HYBRID ROUTER
      |                differential | property | boundary | stateful
      |
 [7] execute --------> Observation[]    (dotnet test, sandboxed, capped)
      |
 [8] verify ---------> Verdict[]        (reproduce xN, shrink, adjudicate)
      |
 [9] report ---------> Finding[]        (+ runnable test artifact)
      |
[10] memory ---------> persisted, retrievable, provenanced
      |
[11] MCP / CLI / dashboard
```

---

## 4. Modules

### `trust.ingest` — sprint #1

Open or clone the repo; resolve `base`/`target` (default: merge-base). Extract
per-file hunks, changed symbol names, the test inventory, and the dependency
manifest diff. Output: `ChangeSet`.

Noise triage lands here: classify each changed file as `source`, `generated`
(`*.g.cs`, `*.verified.*`), `test`, `build-config`, or `doc`. Issue #2297 is
237 files of which 16 are semantically meaningful — the reviewer must not
drown, and the ratio itself is reportable.

### `trust.fingerprint` — sprint #2 (starred)

Per changed symbol, derive the eight dimensions from `sprints.md`:

| Dimension | AST / git signals |
|---|---|
| Structural | recursion, loop nesting depth, branch count, type parameters |
| Memory | `ArrayPool`, `IBufferWriter`, `Rent`/`Return`, `stackalloc`, `ref struct`, `Span<T>` |
| State | mutable fields, statics, caches, `IDisposable` |
| Concurrency | `async`/`Task`, `lock`, `Interlocked`, `volatile` |
| Data handling | serialization entry points, `BitConverter`, encoding, conversions |
| Boundary | index arithmetic, `Length`/`Count` math, narrowing casts, `unchecked` |
| Historical | prior fix density on these lines, revert commits, churn |
| AI provenance | commit author, trailers, model/agent identity when present |

The LLM may *label and explain* a fingerprint. It may not invent a dimension
value that the AST does not support. Fingerprints are claims about code shape,
and they are checkable.

### `trust.patterns` — sprint #3 (starred; seeds #25)

Declarative library mapping fingerprint predicates to bug classes and testing
strategies:

```yaml
- id: buffer-ownership-after-return
  when:
    any_of: [memory.pooling, memory.buffer_writer]
  bug_classes: [use_after_return, double_return, aliasing]
  strategies: [differential, stateful]
  priority: high

- id: narrowing-cast-on-length
  when:
    all_of: [boundary.narrowing_cast, boundary.length_arithmetic]
  bug_classes: [truncation, integer_overflow, off_by_one]
  strategies: [boundary, property]
  priority: high
```

Human-reviewable, repo-independent, and the unit that gets shared in #25.

### `trust.memory` — sprints #4, #5, #6, #22

SQLite. Tables: `evidence`, `hypotheses`, `experiments`, `observations`,
`verdicts`, `findings` — every row carrying `source`, `provenance`, `created_at`.
Retrieval (#6) is FTS5 + symbol-scoped lookup returning **cited snippets**, never
whole conversations: the agent's context window stays small and every retrieved
line keeps its origin. AI conversation ingestion (#5) is an optional adapter
over the same schema, so the pipeline runs identically with or without it.

### `trust.tree` — the context tree, walkable and measured (challenge track)

Arranges everything a review knows about a branch into one tree — issue,
diff files→hunks, the assumption ledger (each assumption with evidence, impact
sites, pre-aimed hypotheses), and the session capsule. Two pass kinds make
traversal observable:

- **lookup** — a question enters at its best node; only the root→entry path is
  counted (tokens included), which is the "pull in only what it needs" walk.
- **propagation** — every FALSIFIED assumption re-enters the tree and its
  whole subtree (sites + hypotheses) is revisited; revisits are counted, which
  is the blast radius expressed as recurring traversal.

Two backends behind one output schema:

- `context_tree.py` — deterministic in-process walk (zero deps; the demo never
  dies on stage without a network).
- `mongo_tree.py` — the same walk on **MongoDB Atlas**: nodes/edges/
  traversals collections, `$graphLookup` for both traversal directions
  (child→parent lookup path; parent→child blast radius, `depthField`
  attached), aggregation pipeline for the per-pass token ledger, and every
  pass persisted as a `traversals` document (the audit trail). `MONGO_URI`
  selects the backend; both emit the same JSON so `render_tree.py`'s
  standalone HTML (tree + visit highlighting + pass ledger + A/B bars vs a
  traditional agent reading the raw diff) is backend-agnostic.

### `trust.capsule` — sprint #15 (PR Intent Capsules)

Attaches the author agent's context to the repo so a reviewer can read it. One
capsule per branch, committed as `.trust/capsules/<branch>.json`, built from
whichever sources exist:

| Source | Yields | Available for the four branches? |
|---|---|---|
| Agent session transcript | prompts, tool trail, decisions, rejected options | only if we instrument the agent (see §5.1) |
| Issue text | stated requirements | yes |
| Commit + diff | changed symbols, scope | yes |
| Git history | the author's implicit base, prior art on these lines | yes |

`trust/session_graph/` already implements the transcript path. It turns a Claude
Code session into a provenanced graph — `PROMPT`, `DECISION` (with the options
the human *rejected*), `TOOL_CALL`, `FILE`, `COMMIT`, `BRANCH` — joined to real
git objects by `inspects` and `parent_of` edges. Extraction is deterministic, so
every capsule field resolves to a transcript `uuid` or a commit SHA.

When no transcript exists, a **retro-capsule** is reconstructed from issue +
commit + diff and labelled `reconstructed: true`. Reconstructed fields are never
presented as the author's actual reasoning.

### `trust.assumptions` — the mechanism that removes hallucinations

The capsule's most valuable content is not what the agent did but what it
*took for granted*. Each assumption becomes a checkable proposition:

```json
{
  "id": "A3",
  "statement": "the branch's base is the merge-base with the default branch",
  "source": {"transcript_uuid": "ecfcfdfb-...", "kind": "implicit_in_tool_call"},
  "check": "git rev-parse <branch>^ == <assumed_base>",
  "verdict": "FALSIFIED",
  "evidence": "branch parent is 32258fdb; assumed base was 524fd55e",
  "consequence": "two pre-existing commits attributed to the agent"
}
```

Verdicts: `SUPPORTED` | `FALSIFIED` | `UNCHECKABLE`. The pipeline:

1. **Harvest** — pull assumptions from the capsule. Explicit ones come from the
   agent's own statements; implicit ones from the shape of its actions (a tool
   call that uses `merge-base` *assumes* the merge-base is the base).
2. **Compile to a check** — each assumption must reduce to a command, a query
   against the graph, or a generated test. An assumption that cannot be reduced
   is `UNCHECKABLE` and is reported as such, not quietly dropped.
3. **Execute** — run it. This is `trust.execute`, reused.
4. **Escalate** — every `FALSIFIED` assumption becomes a hypothesis for the
   bug-hunter, pre-aimed at the code the assumption justified.

This is the join between the two halves of the system: **the capsule aims the
hunter, and the hunter proves what the capsule only suspected.** Context without
execution is just more prose to distrust; execution without context hunts
blindly. The fingerprint says what *kind* of bug is likely; the falsified
assumption says *where the author was already wrong*.

### `trust.planner` — sprint #8

Ranked hypotheses from fingerprints + matched patterns + historical evidence.
Each: failure mode, rationale citing evidence IDs, chosen strategy, **expected
observation** (stated before execution, so the experiment can falsify it).
Rank = pattern priority x historical fragility x blast radius.

### `trust.router` — the hybrid (sprint #3 + #20)

Picks an executor per hypothesis, constrained by what is actually available:

| Strategy | Used when | Oracle |
|---|---|---|
| `differential` | a base build exists | base behavior — no oracle needed |
| `property` | an invariant is stateable | LLM-authored, must survive `verify` |
| `boundary` | index/cast arithmetic detected | derived boundary values |
| `stateful` | mutable/pooled/disposable state | operation-sequence invariants |

`differential` is preferred whenever available: the divergence *is* the
evidence, so nothing in the verdict can be hallucinated. The others widen reach
to absolute bugs — at the cost of an oracle that `verify` must then defend.
Adaptive selection (#20) re-ranks remaining hypotheses from observed results.

### `trust.execute` — sprint #9

Synthesize a standalone xUnit project referencing the target (and for
`differential`, the base) assemblies. Build and run via `dotnet test` in the
scratchpad, never in the repo. Wall-clock timeout, output cap, no network.

### `trust.verify` — sprint #11

The gate that makes findings trustworthy:

1. **Reproduce xN** — anything non-deterministic is `flaky`, not a bug.
2. **Shrink** — reduce to a minimal counterexample.
3. **Adjudicate** — genuine defect vs. intended behavior, checked against
   docs, the issue text, and git history evidence.

Verdict is one of `confirmed` | `intended` | `flaky` | `inconclusive`.
`confirmed` **requires** an attached reproducible artifact. There is no path to
`confirmed` through LLM assertion alone.

### `trust.report` — sprint #12

Every finding carries: suspected cause, minimal triggering input, exact
command, observed vs. expected, evidence chain with provenance, and a
standalone runnable test file. Confirmed findings and unverified hypotheses are
rendered in visually distinct sections and never merged into one score.

### `trust.mcp` / `trust.cli` — sprints #13, #23

MCP tools: `analyze_repo`, `get_fingerprints`, `hunt`, `get_findings`,
`recall_evidence`. CLI: `trust hunt . --base main`.

---

## 5. Demo — "better debuggable, before vs. after"

The implemented comparison is exploratory. Its naive arm and checked arm differ
in both base resolution and available checks, so it cannot isolate the causal
value of an author capsule. Tieto's branches have no original author sessions.

| | Arm A — "before" | Arm B — "after" |
|---|---|---|
| Input | the diff only | diff + Intent Capsule + git archaeology + session graph |
| Represents | code review as practised today | review with the author's reasoning attached |
| Retrieval | read files until you understand | targeted queries against the graph |

### 5.0 Opening beat: it already happened to us (30 seconds)

While analysing these four branches, this project's own AI reviewer produced a
confident, evidence-citing finding that all four agents had re-applied a
dependency bump the maintainers deliberately reverted. It cited a real commit
(`d62699e7` "Rollback package dependency versions for analyzers"). It was
**wrong**: `origin/develop` does not exist in this fork, the `merge-base`
fallback silently used `master`, and the diff therefore started two commits too
early. The agents never touched that file.

One unchecked assumption — "the merge-base is the base" — produced a plausible
false finding. What caught it was not re-reading the diff; it was the
`parent_of` edge in the session graph showing the branch's real parent. This is
the entire thesis in one slide, and it is not synthetic.

### 5.1 Produce genuine agent context

Tieto did not ship the agent conversations, so **the authentic authoring
context for the four challenge branches is unrecoverable** and no tool can
honestly reconstruct it. What exists instead is a controlled re-enactment: an
instrumented session re-implementing issue **#2283** against base `32258fdb`,
capturing the full transcript, then graphed with the same deterministic
pipeline used everywhere else.

Executed 2026-11-14 (see DEMO.md "re-enactment experiment"):

- **Guided reproduction** — the session produced a patch byte-identical to
  Tieto's commit `9df83c3` (branch `ju26-re-2283`, commit `c3791be5`,
  labelled in the commit message: the implementer saw the reference). The
  worktree builds; 19/19 GenericsFormatterTests pass.
- The transcript (a deepcode-harness log) is re-encoded deterministically by
  `trust/session_graph/deepcode_convert.py` — private `reasoning_content` is
  deliberately not copied — and graphed: 365 nodes, 720 edges, decisions with
  rejected options, branch↔commit join.
- `why_lines.py --seed-rev` attributes the patch's lines to the exact edit,
  stated reason and trigger; pre-existing lines are attributed to the L0
  commit layer only. `replay matches disk exactly`.
- The review pipeline on the re-enactment branch reproduces the Tieto-branch
  result (no defect; Arm A's false base finding rejected) and, on the 4-file
  diff, measures recall saving only 23.6% vs 55–96% on the 237-file diff —
  retrieval pays at scale, and the small-diff number is published too.
- **Pending:** a clean-room run (same task, no access to the reference) after
  the Claude usage limit resets, to measure convergence without steering.

The re-enactment is **not Tieto's agent and is never presented as such**. It
measures the mechanism — how much of an author's reasoning is capturable
(L0–L3) and what attaching it changes — under controlled conditions.

For Tieto's four branches, retro-capsules (labelled `reconstructed`) remain
the only honest source.

### 5.2 The measured comparison

The table below records proposed evaluation metrics. The implemented arms do
not run the proposed fingerprint → plan → route pipeline.

| Metric | Why it is the right number |
|---|---|
| Hidden problems surfaced | each with a runnable repro; "hidden" = no existing test fails |
| Assumptions falsified | Arm A cannot score here at all — it has no assumptions to check |
| Localization cost | files/lines read to reach the finding; graph traversal counts it |
| Finding precision | confirmed / (confirmed + rejected). The headline: a reviewer that is often wrong is worse than useless |
| Evidence bytes loaded | measured by instrumentation, not estimated |
| False findings rejected by `verify` | the hallucination rate; Arm A should be higher |

**Correction, measured 2026-11-14.** An earlier draft of this section predicted
Arm B would consume *less* context than Arm A despite knowing more, on the
theory that the capsule replaces broad reading with targeted retrieval. The
harness disproves it: across all four branches Arm B loads 1.08x-2.7x **more**
evidence, because the capsule *adds* records rather than replacing any reading.
`run_ab.py` prints this loss itself. The claim is withdrawn and must not be
presented.

The result that does hold is stronger anyway: **Arm A emits a false finding on
all four branches** - the same base-misresolution artefact that fooled this
project's own reviewer - while Arm B emits none. Precision 0-50% versus 100%.

### 5.3 Hidden-problem walkthrough

Take the highest-value falsified assumption from Arm B, and show the chain end
to end: assumption → compiled check → failed check → pre-aimed hypothesis →
generated experiment → minimal counterexample → runnable test handed to the
audience. The audience runs `dotnet test` themselves. Nothing is taken on
trust.

### 5.4 Fallback and honesty rules

If instrumentation yields no genuine defect in the time available, the
bug-hunter runs against a deliberately injected, clearly-labelled regression in
runtime code (`MessagePackReader` / `MessagePackWriter` boundary or pooling
logic) on branch `ju26-demo-injected`, modelled on a real historical fix found
by archaeology. It is labelled in the branch name, the commit message, the
report header and the narration.

**A synthetic defect is never presented as a discovery in the original code,
and a reconstructed capsule is never presented as the author's real reasoning.**

### 5.5 Collective intelligence close

Re-run 5.3 with the verified pattern in the shared library (#25): the second
investigation reaches the same finding in fewer experiments. Trust compounds.

## 6. Risks

| Risk | Mitigation |
|---|---|
| ~~.NET 8 SDK not installed~~ | **Closed** — SDK installed 2026-11-14 |
| Base-commit misresolution | The bug that bit us. Derive base from `<branch>^`, verify against the brief's file counts, record it as a checked assumption. Never fall back silently |
| Arm A is a strawman | Arm A must be a genuine review (full diff, issue text, free file reads) or the comparison proves nothing. Publish Arm A's prompt verbatim |
| Retro-capsule smuggles hindsight | Build it only from issue + commit + diff, by a process with no access to Arm B's findings. Label `reconstructed` |
| Assumption harvesting becomes LLM vibes | An assumption only counts once compiled to an executable check; `UNCHECKABLE` is reported, not hidden |
| Four engines + router is a lot | Ship `differential` first; others behind one interface |
| Generated test won't compile | Compile-repair loop, capped; failure means `inconclusive`, never silent |
| Injected bug looks like a toy | Model it on a real historical MessagePack fix found by archaeology |
| LLM-authored oracle is wrong | That is `verify`'s job, and a wrong oracle is a *demo asset* |
