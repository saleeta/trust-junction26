# Planned Entire Trail: Evidence-backed review of AI-made code

**Status:** LIVE 2026-11-14.

- Project: `et/earned-trust-review` (EU, aws-eu-central-1, private, account-owned)
- Repository: `et/earned-trust-review/trust` (private) — hosts this project's
  code on `master`, the reviewed patch on `review/2297`, and the true base on
  `base/2297` (= `32258fdb`)
- Trail #1: https://entire.com/et/earned-trust-review/-/trails/1
  "Review AI-made patch for MessagePack-CSharp #2297 against its requirement"
  - change trust/1: https://entire.com/et/earned-trust-review/-/trails/1/changes/trust/1
  - branch `review/2297` retargeted onto `base/2297` (the patch's real parent)
  - findings attached: HIGH falsified-assumption guard
    (CompositeResolverTemplate.tt:7, with suggested patch) and MEDIUM false
    README claim (README.md:1640, with suggested patch)
  - AI recommendation: request changes. Human decision: pending.
- Raw re-enactment session data is excluded from pushes (gitignored, pending
  clearance review); the Entire session-attach step is scheduled after the
  Claude usage limit resets so a fresh, cleared session can be captured.

## How the project maps onto the Entire challenge

The challenge asks for Sessions, Graph, Brain, and Trails with measurable
token efficiency. This project implements all four locally and uses the hosted
Entire product for the collaboration layer:

| Entire capability | Our implementation | Where |
|---|---|---|
| **Sessions** (shared memory / checkpoints) | transcript → provenanced graph (`PROMPT`, `DECISION` with rejected options, `TOOL_CALL`, `COMMIT`, `BRANCH`); deepcode-harness logs re-encoded deterministically; capsules per branch | `trust/session_graph/`, `trust/tree/` |
| **Graph** (codebase mapping, search instead of blind file reads) | context tree (issue → diff files/hunks → assumptions → sites → hypotheses + capsule); lookup paths and propagation re-traversals; token cost per walk measured | `trust/tree/context_tree.py`, `trust/memory/recall.py` |
| **Brain** (persistent reasoning, past decisions) | memory store over session decisions and verified lessons (CONCEPT_CARD.md failure-mode table); falsified-assumption patterns reusable across branches | `trust/memory/`, `trust/assumptions/engine.py` |
| **Trails** (agent works → review: does the change match intent?) | the core loop: requirement → base/target resolution → assumption ledger → compile probes → evidence receipt with AI recommendation, refusals, unchecked areas, pending human decision | `trust/review/`, `demo/review-2297.html` |
| **Token efficiency (measured)** | full dump vs triaged vs retrieval/tree walk, dry-run token accounting; on the 237-file patch: 79.2k → 5.6k → 2.3–2.5k tokens | `trust/ab/llm_arm.py`, `trust/tree/` |

The MongoDB Atlas challenge track is the storage backend for the same tree
(`trust/tree/mongo_tree.py`: nodes/edges/traversals collections, `$graphLookup`
traversal, aggregation token ledger).

## Intent

Use Entire Sessions, Graph, Brain, and a Trail to review one AI-made
MessagePack-CSharp change against its requirement. The reviewer must show
what it checked, what it could not check, and the evidence behind its
recommendation. A named engineer owns the final decision.

**Reference change:** `origin/ju26-issue-2297`, requirement
`MessagePack-CSharp#2297`. Tieto did not provide its authoring session, so
the original agent's intent cannot be recovered. Our own guided #2283
re-enactment is a separate, clearly labelled session demonstration.

## Why Graph is needed

Index the **repository under review**, then query the subgraph touched by
the proposed change: changed symbols and templates, generated outputs,
callers and consumers, target frameworks, tests, and related configurations.
The graph routes attention and exposes possible impact. It does **not** prove
correctness or completeness. Show parser coverage and unresolved relations
beside results; a missing edge is not evidence that no consumer exists.

For #2297, the review question is: “Which generated types, templates,
target frameworks, tests, and coverage settings are affected by the new
attribute guard?” The executable compile probes and requirement text remain
separate evidence.

## Entire-native workflow

1. **Sessions:** capture the fresh implementation/review session as a
   checkpoint linked to its commit. Keep Tieto's original branches labelled
   as having no original session.
2. **Graph:** run `capabilities`, `diff`, and focused `impact`/`query` commands
   on the MessagePack checkout. Record the Git revision and coverage report.
3. **Brain:** retrieve prior decisions, the checkpoint, and relevant code
   context. Compare retrieval cost to a fair triaged-diff baseline while
   measuring finding quality separately.
4. **Trail:** attach requirement, evidence, AI recommendation, refusals,
   unchecked areas, and human decision. Do not call the AI recommendation an
   approval.

## Acceptance criteria

- A private Entire-native repository and one open Trail exist, with a URL
  recorded here.
- A real Entire checkpoint is linked to a new commit; its captured session
  is reviewed for disclosure before upload.
- Entire Graph indexes the C# checkout, reports C# semantic coverage and
  exclusions, and produces a change-impact result for the sample.
- Brain answers one prior-decision question using the captured session and
  code map, with source references.
- The Trail presents #2297's requirement, the two successful unguarded
  compile probes, the AI's request-changes recommendation, and its refusal
  to waive the requirement.
- A named human records the final decision and residual risk. Until then,
  approval is pending.

## Current setup and blockers

- Entire CLI 0.13.4 is installed locally under `.tools/entire-bin/`.
- `entire enable --agent codex` configured local Sessions capture in this
  project with `push_sessions: false` and telemetry off.
- Entire Graph/Brain are not installed. The plugin installer cannot reach
  `github.com` from this environment.
- The CLI device flow was approved in a browser, but polling
  `eu.auth.entire.io` failed with a connection reset, leaving the CLI logged
  out. Hosted project/repo/Trail creation is pending authenticated access.
- The project Git repository has no remote. The sample `repo/` clone points
  to Tieto's repository; it should not be used as our writable Trail remote.

## Hosted setup once access works

Create an EU-region private Entire project and native repository, then
create an **intent-only Trail** first. Link a branch only after the project
snapshot is committed and the session data is cleared. The exact project
owner and resulting URLs must come from the authenticated account, not be
guessed.
