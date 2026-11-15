# trust-pitch.mp4 — transcript with emotive direction

Video: `demo/videos/trust-pitch.mp4` · voice: en-US-JennyNeural (+10% rate, +2Hz pitch)
Tags describe delivery, not content changes. Keep the energy conversational;
only two `[excited]` beats in the whole script.

Tag legend:
- `[crisp]` — clean, clipped, businesslike
- `[warm]` — friendly, inviting
- `[emphatic]` — stress the words that follow
- `[beat]` — a short pause before the next phrase
- `[excited]` — genuine energy burst (used sparingly)
- `[serious]` — lower, slower, weight on the words
- `[upbeat]` — lighter, forward-moving
- `[firm]` — no negotiation, final

---

## 01 · The problem — a simple example

`[crisp]` Here's the problem, in one picture. `[conversational]` An AI was asked to
shorten a function called *average*. It deleted one little line — `[beat]` the
guard for an empty list. `[emphatic]` Every test stayed green, because no test
ever tried an empty list. Then someone calls average on nothing — `[excited]`
and it crashes! `[serious]` This is the everyday AI-coding accident.
`[warm]` And this review catches it.

## 02 · The idea

`[upbeat]` So here's the idea. Same change, two reviews. `[wry]` One gives an
opinion — *"looks fine to me."* `[crisp]` The other runs a test that anyone can
repeat. `[emphatic]` Don't take the AI's word for it: `[firm]` make it show
proof. `[warm]` Every claim gets a sentence, a scope, and one command that
re-runs the check.

## 03 · Step 1 — gather evidence

`[crisp]` Step one: gather the evidence. `[conversational]` What was promised,
what the AI changed, and why it did it — `[beat]` from the AI's own chat log.
`[upbeat]` Then we put them side by side. `[serious]` And when the chat log
doesn't exist? `[firm]` We label the gap. `[emphatic]` No fake context, ever.

## 04 · Step 2 — make it checkable

`[crisp]` Step two: turn the promise into a test. `[dry]` *"Never crashes"* is
vague — `[upbeat]` so we rewrite it so a computer can check it: `[emphatic]` for
every list, including the empty one, average must not crash. `[beat]` One
sentence, one scope, one command. `[warm]` That's an audit trail you can walk.

## 05 · Step 3 — run it, then look around

`[crisp]` Step three: run it — `[upbeat]` then look around. `[conversational]`
We try every list, including the empty one. It crashes — `[emphatic]` and one
crash is enough to prove the claim wrong. `[curious]` Then we ask: what else
uses average? `[firm]` Every caller gets re-checked. `[beat]` Leads — not guilt.

## 06 · Step 4 — answer honestly

`[crisp]` Step four: only four honest answers. `[emphatic]` Refuted: we saw it
fail. `[emphatic]` Proved in scope: we checked the whole stated domain.
`[calm]` Tested: the examples passed. `[serious]` Unknown: reported, never
dropped. `[firm]` An answer only counts if a real run produced it —
`[beat]` the AI can suggest. `[emphatic]` It can't hand out answers.

## 07 · How it grows

`[upbeat]` And this is how it grows: `[emphatic]` we check promises, not lines.
`[warm]` One promise covers many lines of code. `[crisp]` Each review reads only
what changed — `[upbeat]` and every promise that's already checked becomes a
test for the next change. `[beat]` `[warm]` The trust compounds.

## 08 · Does it work?

`[curious]` Does it work? `[crisp]` We ran it on all five PRs of this project.
Same checks on every change. `[conversational]` Grey: how much text a basic AI
must read — `[emphatic]` up to thirty-six thousand tokens. Purple: what our
review actually needed — `[excited]` four hundred.

## 09 · Context + ledger

`[warm]` One last thing: where does all this live? `[crisp]` The agent context
travels with the change on the Entire Trail — `[beat]` the session that records
what the AI was thinking. `[serious]` Without it, the review honestly says:
intent, *Unknown* — `[beat]` meaning, we have no evidence. `[upbeat]` With the
session, the agent's own words are the evidence, so that Unknown is *resolved* —
`[emphatic]` turned into *Refuted*, meaning, `[firm]` we found a counterexample.
`[warm]` And MongoDB keeps the audit ledger: every step of the review, and what
it cost — `[beat]` so anyone can re-walk it.

## 10 · Who decides

`[serious]` Finally — who decides? `[firm]` The AI finds the problem, but it is
never allowed to approve its own work. `[warm]` It hands a person the evidence,
and the person decides. `[proud]` In our repo, a named engineer — Saleeta Qadir
— signed the corrected patch. `[beat]` `[firm]` The AI cannot sign.
`[emphatic]` `[warm]` A human owns the trust.
