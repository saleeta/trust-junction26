# Two-minute stage presentation

Open the new [concept deck](demo/concept-deck.html) before the timer starts.
It is a self-contained, five-slide HTML presentation. Arrow keys navigate;
**N** shows speaker notes. Click the review-flow nodes, target frameworks,
changed lines, and Entire capabilities to explain the idea visually.
The #2297 evidence on slide 3 comes from the working review receipt;
slide 4 is explicitly labelled as a proposed proof-carrying interface.

| Time | Stage action and line |
|---|---|
| 0–15 s | Slide 1. “AI wrote the patch. Who checks the AI? We make every important review claim traceable to a check and a human decision.” |
| 15–39 s | Slide 2. Click **Intent → Impact → Claims → Checks → Receipt → Human**. “This is the review contract. A model cannot silently turn missing evidence into approval.” |
| 39–74 s | Slide 3. Click **net472**, then **netstandard2.0**. “The 237-file #2297 patch excludes two shipped targets from the attribute the issue requested for all generated code. Our compile probes show the attribute is available there.” |
| 74–99 s | Slide 4. Click the `#if` line, then the attribute line. “This is the next step: each change links to a scoped claim and its proof, counterexample, test, or unknown status. We have a counterexample here, not a proof of the whole library.” |
| 99–120 s | Slide 5. Click **Graph** and **Trail**. “Entire keeps the context and code map beside the receipt. The AI recommends changes; the named engineer owns the final decision. This one remains pending.” |

Use the older [technical walkthrough](demo/presentation.html) for questions
after the pitch. It is built from pipeline artifacts. If those artifacts are
stale, rebuild the technical walkthrough first:

```bash
python present.py            # runs the pipeline if needed, then builds the deck
```

Keep [DEMO.md](DEMO.md) for questions; do not run the seven-beat pipeline on stage.

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
