# Two-minute stage presentation

## Architecture presentation (recommended)

Open [the animated architecture deck](demo/architecture-presentation.html).
Press **Present 2:00** for the timed nine-slide run, or use the arrow keys to
go at your own pace. **Notes** (or `N`) shows the line to say for the current
slide; **Details** (or `D`) shows the technical deep dive for questions.

Slides 1–5 use a simple made-up example every programmer knows: an AI
"shortens" `average()` by deleting its empty-list check, the tests stay green,
and `average([])` raises `ZeroDivisionError`. Slides 8–9 show real results from
this project (five scored PRs; toy-shop PR #5 approved on Entire Trail #2;
MessagePack #2297 pending on Trail #1).

### Script (about 310 words, 2.5–2.75 words per second)

| Time | Slide | Say |
|---|---|---|
| 0–13 s | **1. The tests passed. The code still broke.** | “Here's a simple example. An AI made average() shorter by deleting its empty-list check. The tests stayed green, because none used an empty list. So average of an empty list now crashes.” |
| 13–28 s | **2. Don't take the AI's word. Make it show proof.** | “A normal AI review says: shorter, tests pass, approve. It never tried an empty list. We do it differently. Write down the promise. Actually run average of an empty list. Look. It crashes. That's proof, and anyone can repeat it.” |
| 28–40 s | **3. Step 1: gather the evidence.** | “Step one: gather three things. The promise, the change, and the AI's reason from its Entire chat log. Alone, each looks fine. Together, you see the promise needs the line the AI deleted.” |
| 40–54 s | **4. Step 2: turn the promise into a test.** | “Step two: make the promise checkable. "Never crashes" becomes: for every list, including the empty one, average doesn't crash. It stays linked to the README, the code and the chat. Until we run it, it's just a claim.” |
| 54–70 s | **5. Step 3: run it, then look around.** | “Step three: run it. The empty list crashes, and one crash is enough to prove "every list" false. Then we look around. report() and grade_summary() use average too, and older promises might break. Each gets its own check before we call it broken.” |
| 70–81 s | **6. Step 4: only four honest answers.** | “Step four: only four honest answers. Refuted. Proved, for the cases we listed. Tested, on some examples. Or unknown. The AI can suggest. Only a real run decides.” |
| 81–94 s | **7. We check promises, not lines.** | “We check promises, not lines. Many lines point to one promise, with a failing case and a re-runnable proof. Old promises become tests for new changes, but each review only reads the change.” |
| 94–107 s | **8. We ran it on all five of our PRs.** | “Does it work? We ran it on all five of our pull requests, and kept the bad news. A basic AI reads up to 36,600 tokens of diff. Ours carried about 400.” |
| 107–120 s | **9. The AI finds it. A human signs for it.** | “Who says yes? Never the AI. It finds the bug, someone fixes it, the checks re-run, and a named person signs. Our toy-shop fix is approved on Entire. The MessagePack patch still waits.” |

The deck advances on its own in **Present 2:00** mode; finish each line as the
next slide's animation starts. The interactive review replay below is the
evidence view for questions after the timed presentation.

## Interactive review replay

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
does not run a proof checker for arbitrary repositories. If the latest 100
closed PRs contain no merge, the browser scans the current repository tree,
reads up to 80 source/document files, and passes structural and text-pattern
claims through explicit checks. It reports the exact scan scope and keeps
unresolved intent `Unknown`. No model, project build, or test suite runs in
this static GitHub Pages fallback.

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
