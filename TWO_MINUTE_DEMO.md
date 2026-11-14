# Two-minute stage presentation

Open [demo/review-2297.html](demo/review-2297.html) before the timer starts.
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
