# Explained: how the review works, and where Entire and MongoDB fit

## The idea in one paragraph

An AI reviewer should not be able to say "this is broken" (or "this is fine")
without showing it. So every finding here is a **claim** with a **rule**, a
**checker that actually runs**, a **witness** (the concrete failing case) and a
**command anyone can re-run**. The AI may suggest claims; only executed code
may decide them. A named human makes the final call. **Entire** carries the
agent's session context in and the review receipt out to that human, and
**MongoDB Atlas** stores the evidence as a graph that is walked, not dumped.

## How it works: the pipeline

```
 requirement / issue ─┐
 git diff (true base) ├─► 1 GATHER ─► 2 CLAIMS ─► 3 CHECK ─► 4 PROPAGATE ─► 5 RECEIPT ─► 6 HUMAN
 agent session (opt.) ┘     context      formal     execute    blast radius    evidence      named
                            tree         + scope    → verdict  from failures   + AI rec.     decision
```

| Step | What happens | Code |
|---|---|---|
| **0. Find the true base** | The patch is diffed against its real parent commit (merge-base), or the tool refuses. A wrong base once blamed the patch for other people's changes - that false finding is ours, and it is kept in the record. | `trust/ingest/base_resolver.py` |
| **1. Gather** | Build one **context tree**: issue → diff (files → hunks; generated bulk summarised) → assumptions → impact sites → hypotheses → session capsule. Every node keeps its source and a `verify` command. | `trust/tree/context_tree.py` |
| **2. Claims** | Turn promises and hidden assumptions into checkable claims: one quantified sentence over a **finite, listed domain**, with its assumptions. Changed lines link to the claim; the claim is stated once. | `trust/proof/proof_review.py`, `trust/assumptions/engine.py` |
| **3. Check** | A checker runs (compile probe, guard evaluation, test run, executed predicate). Only this step may set a verdict. | `proof_review.py`, `tfm_guard_check.py`, `toy/review.py` |
| **4. Propagate** | A **falsified** claim re-enters the tree and visits everything that depends on it (callers, templates, earlier promises, target frameworks). Those are **leads**, labelled unconfirmed until their own check runs. Bounded: names in more than 60 files are skipped, history is capped at 30 commits per file, and `inflation_guard()` caps severity. | `engine.py`, `context_tree.py` |
| **5. Receipt** | One page: requirement, claims, verdicts, witnesses, commands, what was **not** checked, and the AI recommendation (never called an approval). | `trust/review/review_card.py`, `demo/review-2297.html` |
| **6. Human** | A named person accepts, requests changes, or records a scope change. The AI cannot sign. | Entire Trail (below) |

### What a claim looks like (real #2297 result)

```
Requirement C-2297-0  SATISFIES(REQ-2297)                           → REFUTED
 ├ C-2297-1  FORALL t in ShippedTFMs, d in GeneratedDeclarations(t):
 │           has(d, ExcludeFromCodeCoverage)                        → REFUTED
 │           witness: net472 / netstandard2.0 - the new #if guard removes the attribute
 │           9 changed template lines link here
 ├ C-2297-2  every checked-in generated .cs matches its .tt         → PROVED IN SCOPE (6 pairs)
 └ C-2297-3  the existing tests can observe this change             → REFUTED (tests build net8.0 only)
Rule: a main claim is REFUTED if any sub-claim is; PROVED only if all are.
```

**Only four verdicts exist:** `Refuted` (counterexample found), `Proved within
scope` (every listed case checked), `Tested` (examples passed, others may
remain), `Unknown` (not checked or undecidable - reported, never dropped).

### Three tiers for any language (`trust/generic/analyze.py`)

| Tier | Source | Can conclude |
|---|---|---|
| static | git + file text (changed symbols, `git grep -w` callers, tests that mention them) | Refuted with listed assumptions, else Unknown |
| induced | git history ("these files usually change together") | **Unknown only** - a lead, never a defect |
| executed (`--run`) | the repo's own tests / your `--spec` commands | Tested, or Refuted |

## Entire: what it is used for

Entire is used at both ends: **context in** (why did the agent write this?)
and **decision out** (who signs?).

| Entire piece | How this project uses it | Where |
|---|---|---|
| **Sessions** | An agent transcript becomes a provenanced graph: `PROMPT`, `DECISION` (with rejected options), `TOOL_CALL`, `COMMIT`, `BRANCH`. The #2283 re-enactment produced 365 nodes and 720 edges. `why_lines.py` answers "why does this line exist?" with the exact edit, the stated reason, the human prompt that triggered it, and the commit. `entire session attach` links a transcript to a commit as a checkpoint. | `trust/session_graph/`, `demo/capsules/` |
| **Graph / Brain** | Implemented locally, because the hosted plugins could not be installed from this environment: the context tree (Graph) and a cited SQLite FTS evidence store over decisions and lessons (Brain). | `trust/tree/`, `trust/memory/recall.py` |
| **Trails** | The human decision layer, in the private project `et/earned-trust-review`. | links below |

**The two Trails:**

- **Trail #1 - MessagePack #2297 (pending).**
  <https://entire.com/et/earned-trust-review/-/trails/1>
  Branch `review/2297` retargeted onto its true base `base/2297` (`32258fdb`).
  Findings attached: HIGH guard (`CompositeResolverTemplate.tt:7`) and MEDIUM
  false README claim (`README.md:1640`), each with a suggested patch.
  AI recommendation: **request changes**. Human decision: **pending**.
- **Trail #2 - corrected toy-shop PR #5 (accepted).**
  <https://entire.com/et/earned-trust-review/-/trails/2>
  The same checkers re-ran on the fix (A1/B2/D1/D2 proved in scope, T1 tested,
  U1 left to the human), and Saleeta Qadir recorded the decision with residual
  risk. The project's approvals gate is disabled, so the signed decision lives
  as the authored Trail discussion.

The pending and accepted samples are never merged into one story. Tieto's
original #2297 authoring session was not provided, so that patch's intent is
recorded as **Unknown**, never reconstructed and presented as fact. Raw
re-enactment session data is not pushed until it has a clearance review.

## MongoDB Atlas: what it is used for

Atlas is the **storage and traversal backend for the context tree**. It is
optional: with `MONGO_URI` set, `mongo_tree.py` runs the same passes on Atlas;
without it, `context_tree.py` runs them in-process. Both emit the same JSON, so
the viewer cannot tell them apart. The stored #2297 run reports backend
`mongodb-atlas::trust_demo`.

| Collection (db `trust_demo`) | Holds |
|---|---|
| `nodes` | one document per tree node: kind, label, detail, token cost, `falsified`, provenance (`_id` = node id) |
| `edges` | `{from_id: parent, to_id: child, type: "contains"}` - the tree as references |
| `traversals` | one document per pass: the question, visited ids, tokens, revisits - the audit trail of how each answer was reached |

| Question | Atlas feature |
|---|---|
| "Where in the tree is the answer to this question?" | `$graphLookup` from the entry node to the root (`depthField`) - only nodes on that path are paid for |
| "This claim failed - what depends on it?" | `$graphLookup` over the subtree of the falsified node (blast radius) |
| "What did each pass cost?" | aggregation pipeline (`$match` / `$group` / `$sum`) as a token ledger |

**Why it matters - measured on the 237-file #2297 patch** (token estimates,
dry run; finding quality is a separate question):

| Approach | Tokens |
|---|---|
| Dump the whole diff into a prompt | 79,108 |
| Triaged diff (15 files) | 5,502 |
| Answer one question by walking the tree | 50 - 172 per lookup |
| Follow one falsified assumption to its blast radius | 251 - 1,390 per propagation |

## How the pieces fit together

```
            ┌──────────────── Entire Sessions ────────────────┐
            │ agent transcript → PROMPT/DECISION/TOOL_CALL/COMMIT graph │
            └───────────────────────────┬─────────────────────┘
 issue + true-base diff ──►  CONTEXT TREE  ◄── stored in MongoDB Atlas
                             (claims, sites,     nodes / edges / traversals
                              hypotheses)        $graphLookup walks
                                   │
                         checkers execute → verdicts + witnesses
                                   │
                        RECEIPT (AI recommends, never approves)
                                   │
                     ┌──────── Entire Trail ────────┐
                     │ named human: accept / change / pending │
                     └──────────────────────────────┘
```

## Limits (stated, not hidden)

- **No automatic claims registry shared across PRs yet.** Each review writes
  its own artifacts (`.trust/pr-reviews/prN.json`, `memory.db`, Mongo
  documents per tree). Earlier promises that R-HIST re-checks are written out
  per review; making each accepted claim a standing check is the next step.
- **"Proved within scope" covers only the listed domain** (16 baskets in the
  toy, 4 shipped target frameworks for #2297). Larger domains need sampling
  (Tested) or a real prover.
- **Claims are partly hand-written.** The #2297 and toy claims are authored;
  the generic analyzer generates claims from fixed templates (G1, G2, T1, U1)
  plus your `--spec` commands.
- **Private model reasoning is not recoverable.** We recover what the session
  recorded and label the rest Unknown.
- Three of the four supplied Tieto branches produced no real finding - an
  honest null result.

## Run it

```bash
python demo.py                    # full pipeline on the #2297 patch
python toy/review.py              # the toy shop review; --check A1 re-runs one claim
python trust/generic/analyze.py https://github.com/OWNER/REPO --pr 123   # any repo
MONGO_URI="mongodb+srv://..." python trust/tree/mongo_tree.py ...        # Atlas backend
python -m pytest                  # test suite
```
