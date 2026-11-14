# trust — proof-carrying review of AI-made code (Junction 26)

**Challenge question:** How can AI review code made by AI so that humans can
trust it?

**Answer implemented here:** the reviewer is structurally incapable of
asserting a defect it has not demonstrated. Every finding carries a claim, a
rule, a checker, a witness, and re-runnable evidence — and the human decision
stays pending until a named person makes it.

Two challenge tracks are integrated:

- **Entire** — Sessions (session → provenanced graph, capsules), Graph
  (context tree, lookup + propagation traversal), Brain (persistent rules and
  lessons), Trails (live Trail #1 carrying the #2297 review), with measured
  token efficiency.
- **MongoDB Atlas** — the same tree in `nodes`/`edges`/`traversals`
  collections with `$graphLookup` traversal and aggregation token ledgers
  (`trust/tree/mongo_tree.py`, `MONGO_URI` selects the backend).

## Run it

```bash
python demo.py            # full pipeline beats 0-6 (+3b tree), ends with a
                          # failing dotnet test that the audience re-runs
python present.py         # builds the interactive stage deck (runs the
                          # pipeline + toy review if artifacts are missing)
python toy/review.py      # the small four-PR toy sandbox, alone
python -m pytest          # 205 tests
```

Open `demo/presentation.html` (arrow keys navigate; click claim cards; click
a command line to copy it).

## What was done — the PRs

The review targets four AI-made patches in
`te-industry-tech-office/junction26-messagepack-csharp` (cloned locally at
`./repo`, gitignored; never our writable remote):

| Branch | Patch | Status |
|---|---|---|
| `origin/ju26-issue-2283` | closed generic struct from referenced assembly crashes generator/analyzer (4 files) | our guided re-enactment `ju26-re-2283` is byte-identical, tests 19/19 |
| `origin/ju26-issue-2234` | analyzer + `SuppressSourceGeneration` (4 files) | reviewed, honest null result |
| `origin/ju26-issue-2129` | formatter for types in referenced assemblies (28 files) | reviewed, honest null result |
| `origin/ju26-issue-2297` | ExcludeFromCodeCoverage on generated code (237 files) | **REFUTED** — see below |

On Entire these live as `review/2297` (the patch) and `base/2297` (its true
parent `32258fdb`) in the private repo `et/earned-trust-review/trust`; the
Trail is https://entire.com/et/earned-trust-review/-/trails/1 with two
findings (HIGH guard, MEDIUM false README claim) and a pending human decision.

The **toy PRs** are a four-commit shop built locally by `toy/build_repo.py`
(PR #1 prices → PR #2 coupons → PR #3 checkout/tests → PR #4 the AI patch
"cap every discount at 50%"). PR #4 is wrong in three progressively deeper
ways: in the diff, in an earlier PR's promise, and in code that merely calls
the changed function. `python toy/review.py` re-derives every verdict.

## The #2297 finding, formally

Obligation: *for every supported target framework, every generated code
declaration carries ExcludeFromCodeCoverage.*

```
#if !NETSTANDARD2_0 && !NETFRAMEWORK          <- changed line
Claims: C-2297-1 "all generated declarations carry the attribute"
Rule:   R-2297 "check every supported target framework"
Result: REFUTED
Witness: net472 (and netstandard2.0) -> generated declaration without the attribute
Evidence: python trust/proof/proof_review.py ... | commit a0aa5ab2
          + compile probes in .trust/probes (attribute compiles UNGUARDED on both)
```

Verdict vocabulary (never anything else):

| Label | Meaning |
|---|---|
| `Proved within scope` | a checker established a precisely stated property under listed assumptions |
| `Refuted` | the checker found a counterexample |
| `Tested` | executed examples passed; other cases may remain |
| `Unknown` | not checked, or the checker could not decide |

## The agent context used to make this — and how a fresh agent uses it

The re-enactment of #2283 (branch `ju26-re-2283`, commit `c3791be5`) was
authored by an instrumented agent session. Its recorded context is stored in
`demo/capsules/`:

- `re2283-session.claude.jsonl` — the session transcript, converted
  deterministically from the harness log (`trust/session_graph/
  deepcode_convert.py`). Contains the agent's recorded prompts, tool calls,
  edits and results. It deliberately does **not** contain private reasoning
  (`reasoning_content` is not copied; L4 is unavailable).
- `re2283-capsule.json` / `.html` — the provenanced graph built from that
  transcript: 365 nodes, 720 edges, decisions with rejected options, the
  branch↔commit join.
- `demo/capsules/README.md` — what each file is and what it is cleared for.

How a fresh agent consumes it:

1. **Locally:** `python trust/session_graph/why_lines.py --session
   demo/capsules/re2283-session.claude.jsonl --seed-rev 32258fdb --file
   <path> --line <n>` answers "why does this line exist?" with the exact edit,
   the stated reason, the trigger, and the commit.
2. **With Entire:** `entire session attach` links a session transcript to a
   commit as a checkpoint, so the next agent resumes with zero context loss;
   the context tree (`trust/tree/`) makes each question a measured walk and
   the falsification propagation re-traversal is the "problems nobody asked
   about" mechanism.

The pipeline runs identically with or without a transcript: without one, the
capsule is labelled `reconstructed` and is never presented as the author's
reasoning.

## Honesty rules

1. The "before" false finding (wrong merge-base) is ours; we lead with it.
2. The #2297 agent did most of the job well (6 templates, 222 snapshots).
3. The finding is a feature gap plus a false README sentence — not a crash.
4. Three of four Tieto branches yield nothing real; that is an honest result.
5. Private reasoning is not recoverable; we recover what was recorded.
6. Confirmed findings and hypotheses are never merged into one score.

## Repository map

```
demo/               interactive deck, review receipt, capsule handoff
toy/                the four-PR runnable sandbox (logic + checkers + review page)
trust/
  ab/               measured A/B arms + LLM token arms
  assumptions/      assumption ledger, blast radius, TFM-guard falsification
  ingest/           base resolution as a checked assumption
  memory/           SQLite+FTS5 evidence store, cited retrieval
  present/          the stage deck builder (data-driven, no invented numbers)
  proof/            proof-carrying review (claims, rules, verdicts, witnesses)
  repro/            standalone failing xUnit repro the audience runs
  review/           the review receipt + stage packaging
  session_graph/    transcript -> provenanced graph, per-line provenance
  tree/             context tree + Mongo/Atlas backend + HTML viewer
  tests/            205 tests
.trust/             evidence artifacts: bases, findings, ab runs, tree, probes
```
