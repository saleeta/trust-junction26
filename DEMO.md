# DEMO — runnable script

Every command below has been run on this machine. Copy-paste order, ~6 minutes.

Prerequisites: Python 3.11+, .NET 8 SDK, the target repo cloned at `./repo`.

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

---

## Beat 1 — Base resolution as a checked assumption (60 s)

The resolver computes the base several independent ways, refuses to pick a
winner silently when they disagree, and validates against an external oracle —
the challenge brief's own file counts.

```bash
cd trust/ingest
python base_resolver.py --repo ../../repo --all-ju26 \
    --expect-files 2283=4,2234=4,2129=28,2297=237 \
    --json ../../.trust/bases.json
```

Observed output: all four branches resolve to `32258fdb`, each flagged
`methods disagree` (reproducing the exact failure condition as a *detected*
dispute), then confirmed by the oracle — 4, 4, 28, 237 changed files, matching
the brief exactly.

---

## Beat 2 — A real hidden problem in Tieto's branch (3 min)

This is the centrepiece: a genuine defect in AI-authored code that **compiles,
passes every test, and no reviewer would catch in a 237-file diff.**

```bash
cd ../assumptions
python tfm_guard_check.py \
    --repo ../../repo \
    --branch origin/ju26-issue-2297 \
    --base 32258fdb \
    --issue-text ../../.trust/issues/2297.md \
    --json ../../.trust/findings/2297-tfm-guard.json
```

### What it finds

Branch `ju26-issue-2297` implements issue #2297, *"Add ExcludeFromCodeCoverage
attribute to generated code."* The agent did most of this **well**: all six T4
templates updated, all 222 verified snapshots regenerated consistently, `.tt`
and generated `.cs` kept in sync. Say so — it earns the finding credibility.

But it wrapped the attribute in a guard of its own invention:

```csharp
#if !NETSTANDARD2_0 && !NETFRAMEWORK
    [global::System.Diagnostics.CodeAnalysis.ExcludeFromCodeCoverage]
#endif
```

That guard asserts an unstated assumption: *the attribute is unavailable on
netstandard2.0 and .NET Framework.* The tool falsifies it by compiling the
attribute, unguarded, against those exact frameworks:

| Probe | Result |
|---|---|
| `netstandard2.0` | **COMPILES** |
| `net472` | **COMPILES** |

So the premise is false, and the consequence is a silent feature gap:

| Fact | Value |
|---|---|
| TFMs the library ships | `netstandard2.0`, `netstandard2.1`, `net8.0`, `net472` |
| TFMs the tests cover | `net8.0` only |
| TFMs silently excluded | `netstandard2.0`, `net472` |
| Test-observable | **No** |

**Two of the four shipped target frameworks never receive the feature the issue
asked for.**

### Why no test catches it

1. All eight test projects target `net8.0`, where the guard always passes. CI
   never compiles the excluded path.
2. The 222 verified snapshots were regenerated *with* the guard, so the
   snapshot tests now assert the guarded output is correct. **The tests codify
   the gap.**

### Why it is not merely a style preference

```bash
cd ../../repo
# the guard is not a repo convention - it did not exist at the base
git grep -c 'NETSTANDARD2_0 && !NETFRAMEWORK' 32258fdb || echo "0 occurrences at base"
# the repo's CI already consumes this attribute - the feature has a real client
grep -n 'ExcludeFromCodeCoverageAttribute' azure-pipelines/test.runsettings
cd ..
```

And the issue text (`.trust/issues/2297.md`) settles intent. The request:
*"I would like all generated code to be decorated with ExcludeFromCodeCoverage
attribute."* Unconditional. **Neither the issue nor either of its two comments
mentions any target framework.** The conditionality came from the implementer,
not the request.

### Verify it yourself — the whole point

The tool keeps its probe projects on disk precisely so this works:

```bash
dotnet build ".trust/probes/origin_ju26-issue-2297/probe_netstandard2_0/p.csproj" -v q --nologo
# Build succeeded.  0 Error(s)
```

Nothing above is taken on the reviewer's word.

### It does not cry wolf

```bash
cd trust/assumptions
for b in 2283 2234 2129; do
  python tfm_guard_check.py --repo ../../repo --branch origin/ju26-issue-$b --base 32258fdb
done
# "no introduced target-framework guards in this diff"  x3
```

---

## Beat 3 — Ask any line why it exists (90 s)

With the author's session captured, the repo becomes interrogable per line.

```bash
cd ../session_graph
python why_lines.py --list
python why_lines.py --file build_graph.py --line 592
```

Returns the exact edit, its timestamp and transcript uuid, the stated reason,
what triggered it, and which human request it serves — plus
`replay matches disk exactly - attribution is complete`.

**State the limit out loud:** `L4 PRIVATE` is unavailable. Claude Code stores
`thinking` blocks with empty text and a signature only (36 blocks, 0 characters
in this session). We recover what the agent *recorded*, not what it privately
reasoned. So the question answered is *"what reason was recorded for this line,
and does it hold up?"* — which is auditable — not *"what truly caused it?"*,
which is not.

Then show it refusing to over-claim:

```bash
python why_lines.py --file ../../DESIGN.md --all
```

Regions touched by untracked shell writes are reported as divergent, and
narration covering several edits is flagged `[batch]` rather than attributed to
single lines.

---

## Beat 4 — The fused graph (60 s)

```bash
python build_graph.py --session <session-id> --repo ../../repo \
    --out session_graph.json --html session_graph.html
```

Open `session_graph.html`. 133 nodes, 239 edges, fully provenanced, no LLM in
the extraction path. Click **Fuse view** to show only the conversation↔git
join, then click the `DECISION` nodes — they carry the options the human
*rejected*, which no diff records. Use **Replay** to scrub the session forward.

---

## The before/after, in one table

| | Without agent context | With capsule |
|---|---|---|
| Base commit | silent fallback, off by two | derived, cross-checked, oracle-validated |
| Why a line exists | commit message | exact edit + stated reason + trigger + originating ask |
| Assumptions | invisible | enumerated, compiled to commands, falsified |
| #2297's gap | unreachable — no test fails | found, with a 2-command repro |
| Reviewer error | confident and unfalsifiable | caught by its own provenance |

---

## Honesty rules for the presentation

- Beat 0's false finding is **ours**, not Tieto's. Present it as our error.
- #2297's agent did most of the job well. Say so before the finding.
- The #2297 gap is a **feature gap**, not a crash or data-corruption bug. Do
  not inflate it.
- `L4 PRIVATE` is unavailable. Never imply we recover an agent's chain of
  thought.
- Beat 2's finding is real and needs no injection. If an injected regression is
  used for any other beat, it is labelled in the branch name, the commit
  message, the report header and the narration.
