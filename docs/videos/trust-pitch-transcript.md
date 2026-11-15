# trust-pitch.mp4 — ElevenLabs transcript (SSML)

Voice tip: en-US — "Lily" or "Charlotte" reads this naturally. In ElevenLabs,
enable **SSML** and paste each segment. Only the two tags ElevenLabs supports
are used, and only where the line would otherwise fall flat — everything else
is carried by punctuation.

Tags used (sparingly):
- `<break time="0.25s"/>` — a real pause (longer only at the big reveals)
- `<emphasis level="moderate|strong">…</emphasis>` — weight on the words that matter

---

## 01 · The problem

Here's the problem, in one picture. An AI was asked to shorten a function called average. It deleted one little line — <break time="0.25s"/> the guard for an empty list. <emphasis level="strong">Every test stayed green, because no test ever tried an empty list.</emphasis> Then someone calls average on nothing — and it crashes! This is the everyday AI-coding accident. And this review catches it.

## 02 · The idea

So here's the idea. Same change, two reviews. One gives an opinion — "looks fine to me." The other runs a test that anyone can repeat. <emphasis level="strong">Don't take the AI's word for it: make it show proof.</emphasis> Every claim gets a sentence, a scope, and one command that re-runs the check.

## 03 · Step 1 — gather evidence

Step one: gather the evidence. What was promised, what the AI changed, and why it did it — <break time="0.2s"/> from the AI's own chat log. Then we put them side by side. And when the chat log doesn't exist? <emphasis level="moderate">We label the gap.</emphasis> No fake context, ever.

## 04 · Step 2 — make it checkable

Step two: turn the promise into a test. "Never crashes" is vague — so we rewrite it so a computer can check it: <emphasis level="strong">for every list, including the empty one,</emphasis> average must not crash. One sentence, one scope, one command. That's an audit trail you can walk.

## 05 · Step 3 — run it, then look around

Step three: run it — then look around. We try every list, including the empty one. It crashes — and <emphasis level="strong">one crash is enough</emphasis> to prove the claim wrong. Then we ask: what else uses average? Every caller gets re-checked. <break time="0.3s"/> Leads — not guilt.

## 06 · Step 4 — answer honestly

Step four: only four honest answers. Refuted: we saw it fail. Proved in scope: we checked the whole stated domain. Tested: the examples passed. Unknown: reported, never dropped. An answer only counts if a real run produced it — <break time="0.25s"/> the AI can suggest. <emphasis level="strong">It can't hand out answers.</emphasis>

## 07 · How it grows

And this is how it grows: <emphasis level="moderate">we check promises, not lines.</emphasis> One promise covers many lines of code. Each review reads only what changed — and every promise that's already checked becomes a test for the next change. <break time="0.25s"/> The trust compounds.

## 08 · Does it work?

Does it work? We ran it on all five PRs of this project. Same checks on every change. Grey: how much text a basic AI must read — up to thirty-six thousand tokens. Purple: what our review actually needed — <emphasis level="strong">four hundred.</emphasis>

## 09 · Context + ledger

One last thing: where does all this live? The agent context travels with the change on the Entire Trail — the session that records what the AI was thinking. Without it, the review honestly says: intent, Unknown — meaning, we have no evidence. With the session, the agent's own words are the evidence, so that Unknown is resolved — <emphasis level="moderate">turned into Refuted, meaning, we found a counterexample.</emphasis> And MongoDB keeps the audit ledger: every step of the review, and what it cost — so anyone can re-walk it.

## 10 · Who decides

Finally — who decides? <emphasis level="moderate">The AI finds the problem, but it is never allowed to approve its own work.</emphasis> It hands a person the evidence, and the person decides. In our repo, a named engineer — Saleeta Qadir — signed the corrected patch. <break time="0.35s"/> <emphasis level="strong">The AI cannot sign.</emphasis> <break time="0.2s"/> A human owns the trust.
