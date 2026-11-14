# Two-minute stage presentation

Open the [visual review replay](demo/concept-deck.html) before the timer starts.
The four supplied AI-made MessagePack branches are already loaded. Press the
right arrow to reveal each patch, or **Replay changes** to reveal them on a
timer. Click a branch row to open its claims, facts, challenges, new knowledge,
and remaining gaps. The toy shop is available through **Example**.

| Time | Stage action and line |
|---|---|
| 0–15 s | Show the empty ledger and press **Next**. “Each merge gives the project a belief. We keep its source.” |
| 15–35 s | Advance PR #1 and #2. “A price must stay nonnegative; a VIP coupon promises 60% off. The graph grows with each promise.” |
| 35–65 s | Advance PR #3; click the red belief and amber warning. “A checked basket is charged −100: that breaches the old price rule. Whether unrestricted discount stacking is intended remains a human question.” |
| 65–100 s | Advance PR #4. “The AI caps each discount at 50%, yet the negative price survives, and VIP now gets only 50%. Green tests do not cover those cases.” |
| 100–120 s | Point to the pending human decision; open the real #2297 receipt if needed. “The reviewer brings counterexamples and uncertainty to a human. It does not approve its own patch.” |

The repository field accepts a **public GitHub URL**. The supplied challenge
repository loads its four AI-made branches and the checked #2297 finding.
Other repositories load recent merged PR metadata and changed-file facts on
selection. Their titles remain unverified candidate claims: this reference
does not run a proof checker for arbitrary repositories.

The prior [animated slide deck](demo/concept-deck-slides.html) remains available
as a fallback.

The [visual-explainer source](demo/concept-deck.src.html) is the editable
template. The **data is backend-driven**: regenerate the standalone HTML with

```bash
python trust/present/build_concept_deck.py   # reads toy/out/review.json
```

It injects the replay rows, per-step statuses, witnesses, breach arrows and
the `~N tokens of evidence carried` caption line, and adds the
**Replay only / Trust pipeline** toggle: unverified title replay (~21 tokens)
vs the executed checker pipeline with agent context (~488 tokens, 10 claims,
7 refuted). Every number comes from the toy review backend.

The renderer comes from [nicobailon/visual-explainer](https://github.com/nicobailon/visual-explainer).

Use the older [technical walkthrough](demo/presentation.html) for questions
after the pitch. It is built from pipeline artifacts. If those artifacts are
stale, rebuild the technical walkthrough first:

```bash
python present.py            # runs the pipeline if needed, then builds the deck
```

Keep [DEMO.md](DEMO.md) for questions; do not run the seven-beat pipeline on stage.

## Earlier evidence-card walkthrough (backup)

| Time | Screen and narration |
|---|---|
| 0–20 s | Point to requirement **#2297** and the 237-file AI-made patch. “The issue asks for the coverage attribute on all generated code. Reading every line is not a useful approval strategy.” |
| 20–50 s | Point to the finding. “The patch excludes two frameworks the library ships. The reviewer did not guess: it found the guard and compiled the attribute unguarded on both targets.” |
| 50–70 s | Open the evidence list; show the saved commands and pinned commit. “Any engineer can repeat these checks. We also record what the checks did not establish.” |
| 70–90 s | Point to **The AI stops here**. “AI recommends changes. It cannot waive the requirement or approve its own output.” |
| 90–110 s | Point to **Human decision pending**. “A named engineer must check the evidence, choose the action, and own the residual risk. We do not invent that approval.” |
| 110–120 s | Point to the decision log. “We even record our own false start: a wrong base produced a false finding. Trust is earned by exposing and correcting that mistake.” |

## Brief coverage

- Concept and principles: [CONCEPT_CARD.md](CONCEPT_CARD.md).
- One sample with requirement ID: the #2297 receipt and pinned commit.
- AI finding, refusal, and why: visible on the receipt.
- Named human acceptance without a full read: **not yet demonstrated**. This
  sample has a known gap, so the honest outcome is pending review and likely
  request changes. A real engineer must sign an accepted sample or a corrected
  #2297 revision before claiming this deliverable is complete.
- Failure modes and decision log: bottom of the receipt and concept card.
- Cleared sample data: the stage receipt uses the public issue and repository
  only. `python trust/review/package_stage.py` produces a four-file allowlisted
  [stage package](demo/stage-package.zip) and checks for common personal-path,
  email, and token patterns. Do not show or distribute the raw re-enactment
  transcript without a separate clearance review.

## Fallback

The card is a self-contained HTML file. If the .NET test host stalls or the
venue has no SDK, show the saved probe commands and artifact. Describe them as
recorded evidence, not as a fresh live run.
