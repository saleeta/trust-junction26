# DEMO — technical backup walkthrough

For the two-minute presentation, use [TWO_MINUTE_DEMO.md](TWO_MINUTE_DEMO.md)
and the generated review receipt. This document is an extended technical
walkthrough. Saved measurements below came from particular environments; rerun
before quoting numbers. `--dry-run` measures context size, not finding quality.

Every command below has been run on this machine. One command runs it all:

```bash
python demo.py            # beats 0-6, ends with `dotnet test` failing (expected)
python demo.py --quick    # skip the generated repro build and test
```

Prerequisites: Python 3.11+, .NET 8 SDK, the target repo cloned at `./repo`.
Note: on this machine `dotnet` is not on PATH in Git Bash; the tools fall back
to `C:\Program Files\dotnet\dotnet.exe`. Add it to PATH before the audience
runs `dotnet test`.

The review target is not "a repository written by AI". MessagePack-CSharp is a
human codebase (first commit 2017-02-13, 3,536 commits). The challenge input is
the four **AI-made patches** on top of base `32258fdb` (4, 4, 28, 237 files).
Everything below reviews the patch — the human base is the oracle that makes
the checks possible ("did this assumption exist before the agent arrived?").

---

## Beat 0 — The reviewer that was confidently wrong (90 s)

**Claim to the audience:** an AI reviewer with no provenance discipline produced
a false finding on these very branches, during this project.

It reported that all four agentic branches re-applied a dependency bump the
maintainers had deliberately reverted, and it cited a real commit:
`d62699e7 "Rollback package dependency versions for analyzers"`. Plausible,
specific, evidence-backed — and **false**.

The cause was one unrecorded assumption: *"the merge-base is the base."*
`origin/develop` does not exist in this fork, so the fallback silently used
`master` and every diff started two commits too early.

```bash
cd repo
git rev-parse origin/ju26-issue-2283^          # 32258fdb  <- the real base
git merge-base origin/ju26-issue-2283 origin/master   # 524fd55e  <- off by two
git rev-parse --verify origin/develop          # fails: the ref does not exist
cd ..
```

**The point:** the diff never changes, but the conclusion drawn from it does.
Base resolution is an assumption, and unrecorded assumptions are where
hallucinations come from.

## Beat 1 — Base resolution as a checked assumption (60 s)

```bash
cd trust/ingest
python base_resolver.py --repo ../../repo --all-ju26 \
    --expect-files 2283=4,2234=4,2129=28,2297=237
```

Observed: all four branches resolve to `32258fdb`, each flagged
`methods disagree` (the exact failure condition, detected), then confirmed by
the oracle — 4, 4, 28, 237 changed files, matching the brief exactly.

## Beat 2 — Assumption ledger and blast radius (3 min)

One falsified assumption yields a family of pre-aimed hypotheses, not one
paragraph.

```bash
cd ../assumptions
python engine.py --repo ../../repo --branch origin/ju26-issue-2297 \
    --base 32258fdb --issue-text ../../.trust/issues/2297.md --reconstructed \
    --json ../../.trust/findings/2297-blast.json
```

Observed: **4 assumptions harvested, 3 falsified, 1 supported.** The guard
`#if !NETSTANDARD2_0 && !NETFRAMEWORK` around
`ExcludeFromCodeCoverage` compiles unguarded on both excluded frameworks (the
compatibility premise is false), the issue asked for the attribute
unconditionally, and the change also wrote a factually false sentence into the
README ("only emitted for targets where it is available"). Blast radius: **228
impact sites** — 2 shipped target frameworks, 6 templates, 220 snapshots that
now codify the gap. Severity is capped by `inflation_guard` at what the
evidence supports: **moderate**. Nine pre-aimed hypotheses are rendered
separately and labelled unverified.

The #2297 agent did most of the job **well**: six templates updated, 222
snapshots regenerated consistently, `.tt` and `.cs` kept in sync. Say so
before the finding — it earns the finding credibility.

## Beat 3 — Graph retrieval instead of a context dump (60 s)

```bash
cd ../memory
python recall.py --rebuild --db ../../.trust/memory.db --repo ../../repo \
    --base 32258fdb --branch origin/ju26-issue-2297 \
    --ledger ../../.trust/findings/2297-blast.json \
    --graph ../session_graph/session_graph.json \
    --issue ../../.trust/issues/2297.md \
    --budget 1200 --query "why is the attribute guarded by a target framework"
```

The store returns cited snippets within the token budget. Exact totals depend
on the installed tokenizer and the current ledger; use the command output for
current numbers. Retrieval is the mechanism behind "pull in only what it
needs".

## Beat 3b — The context tree: lookups, propagation, token ledger (60 s)

The evidence is arranged as a tree, and every review question is a measured
walk through it. When a claim is falsified, the walk **re-enters the tree**
and recursively visits the claim's blast radius.

```bash
cd ../tree
python context_tree.py --repo ../../repo --branch origin/ju26-issue-2297 \
    --base 32258fdb --issue ../../.trust/issues/2297.md \
    --ledger ../../.trust/findings/2297-blast.json \
    --graph ../session_graph/session_graph.json \
    --json ../../.trust/tree/2297-tree.json \
    --html ../../.trust/tree/2297-tree.html
```

The command prints the tree size, the full-dump cost, and every pass with its
token cost and revisits. Open `2297-tree.html`: blue nodes are the lookup
path, red nodes are falsification propagation, purple nodes were revisited,
and the right panel shows the pass ledger plus A/B bars — graph walker vs. a
traditional agent reading the full diff vs. a triaged agent. Quality of a
live traditional agent is labelled "not measured in dry-run".

**MongoDB Atlas backend (challenge track).** The same walk can run on Atlas:
nodes, edges and traversals live in collections, `$graphLookup` computes the
lookup paths and the propagation subtrees, an aggregation pipeline sums the
token ledger, and every pass is written to a `traversals` document:

```bash
MONGO_URI="mongodb+srv://<user>:<pass>@<cluster>/trust_demo" \
python mongo_tree.py --repo ../../repo --branch origin/ju26-issue-2297 \
    --base 32258fdb --issue ../../.trust/issues/2297.md \
    --ledger ../../.trust/findings/2297-blast.json \
    --json ../../.trust/tree/2297-tree.mongo.json
```

Without `MONGO_URI` the offline engine runs and the output says which backend
ran. Both paths emit the same JSON, so the viewer works identically.

## Beat 4 — What context actually costs a model (30 s)

```bash
cd ../ab
python llm_arm.py --repo ../../repo --branch origin/ju26-issue-2297 \
    --base 32258fdb --db ../../.trust/memory.db --dry-run \
    --issue ../../.trust/issues/2297.md
```

The command compares a full diff, a diff with generated files triaged, and
cited retrieval. It reports whether counts use `tiktoken` or a rough
character-based estimate. These are context-size measurements only; no review
quality is measured in `--dry-run`.

## Beat 5 — exploratory naive vs checked pipeline (30 s)

```bash
python run_ab.py --repo ../../repo --branch origin/ju26-issue-2297 \
    --issue ../../.trust/issues/2297.md --expect-files 237
```

The naive arm resolves the wrong base and produces a false finding. The checked
arm resolves the branch parent and runs an additional framework probe that
finds a test-invisible feature gap. **This is not a controlled capsule A/B:**
Tieto supplied no author transcript for #2297 and the arms run different
checks. Do not present the precision percentages as evidence that a capsule
caused the improvement. The probe verifies API availability; the generated
output still requires human assessment.

## Beat 6 — You run it, not us (30 s)

```bash
cd ../repro
python make_repro.py --repo ../../repo --branch origin/ju26-issue-2297 \
    --ledger ../../.trust/findings/2297-blast.json \
    --out ../../.trust/repro/2297 --run
# Audience:  cd .trust/repro/2297 && dotnet test
```

Observed: **Failed: 2, Passed: 1** — the two defect assertions fail while the
defect exists, the sanity assertion passes so the suite cannot succeed
vacuously.

---

## The re-enactment experiment (the agent-context question)

Tieto did not ship the authoring sessions, so **the authentic agent context for
their four branches is unrecoverable** — every assumption checked on them is
read off what was committed (a guard in code, a sentence in the README), and is
labelled `reconstructed`.

To measure what recorded context is worth when it *does* exist, we run a
controlled re-enactment on issue #2283 (the 4-file patch):

```bash
# 1. isolated worktree at the base, branch ju26-re-2283
git -C repo worktree add ../re2283 -b ju26-re-2283 32258fdb

# 2. an instrumented session implements the fix; its transcript is converted
#    deterministically (deepcode harness -> Claude Code format) and graphed
cd trust/session_graph
python deepcode_convert.py \
    ~/.deepcode/projects/d-work-big-hackathon/<session>.jsonl \
    ../../.trust/capsules/re2283-session.claude.jsonl
python build_graph.py --session ../../.trust/capsules/re2283-session.claude.jsonl \
    --repo ../../repo --out ../../.trust/capsules/re2283-capsule.json \
    --html ../../.trust/capsules/re2283-capsule.html

# 3. per-line provenance on the patch, seeded from the pre-edit revision
python why_lines.py --session ../../.trust/capsules/re2283-session.claude.jsonl \
    --seed-rev 32258fdb \
    --file "d:/work/big-hackathon/re2283/src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs" \
    --line 1442

# 4. the same review pipeline as Beat 5, now with a genuine capsule
cd ../ab
python run_ab.py --repo ../../repo --branch ju26-re-2283 \
    --issue ../../.trust/issues/2283.md --expect-files 4
```

Results (honest):

- The implementation is **byte-identical** to Tieto's commit `9df83c3`
  (4 files, 225 insertions, 3 deletions) — a *guided reproduction*, because the
  implementer saw the reference. The commit message says so.
- The worktree builds and its regression tests pass: **19/19**
  (`dotnet test --filter GenericsFormatterTests`).
- The capsule graph: **365 nodes, 720 edges**, including the human decisions
  with their rejected options, the branch↔commit join, and every edit with its
  uuid.
- `why_lines` attributes the patch lines to the exact edit + stated reason +
  trigger + commit, and reports `replay matches disk exactly`.
- The reviewer on this patch finds **no defect** (same as Tieto's branch) and
  Arm A's false base finding is rejected by the shared verifier. A null result
  is reported as a null result.
- **Pending:** the clean-room run (same task, no access to the reference) after
  the Claude usage limit resets, to measure convergence without steering.

What the re-enactment is **not**: it is not Tieto's agent, and it is never
presented as such. It measures the *mechanism* — how much of an author's
reasoning is capturable (L0–L3) and what it changes — under controlled
conditions.

---

## The before/after, in one table

| | Without agent context | With capsule |
|---|---|---|
| Base commit | silent fallback, off by two | derived, cross-checked, oracle-validated |
| Why a line exists | commit message | exact edit + stated reason + trigger + originating ask |
| Assumptions | invisible | enumerated, compiled to commands, falsified |
| #2297's gap | unreachable — no test fails | found, with a 2-command repro |
| Reviewer error | confident and unfalsifiable | caught by its own provenance |
| Author's real reasoning | not shipped by Tieto — unrecoverable | captured only in our own re-enactment, labelled as ours |

## Honesty rules for the presentation

1. Beat 0's false finding is **ours**, not Tieto's. Present it as our error.
2. The #2297 agent did most of the job well. Say so before the finding.
3. The #2297 finding is a **feature gap plus a false README sentence** — not a
   crash, not corruption, not a security issue. Do not inflate it.
4. Three of the four branches yield nothing real from either arm. That is an
   honest result, not four wins.
5. Private agent reasoning is NOT recoverable. Claude Code stores thinking
   blocks empty (36 blocks, 0 chars). We recover what was RECORDED, and our
   converter deliberately does not copy `reasoning_content` even when a harness
   records it.
6. The repository is HUMAN code; the challenge input is the four AI-made
   patches. Tieto shipped no authoring sessions, so no capsule of their agents'
   reasoning exists and we claim none. The re-enactment capsule is OUR
   session, labelled guided, never presented as theirs.
7. Confirmed findings and unverified hypotheses are counted separately and
   never combined into one score.
8. Token figures from `--dry-run` may use tiktoken or a rough fallback. The
   output states which; neither measures review quality.
