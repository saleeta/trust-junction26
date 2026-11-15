"""Build the two-minute, result-led architecture talk from checked toy artifacts.

The visual examples come from toy/out/review.json and toy/out/accept.json.
The four-case refund illustration is labelled as illustrative in the deck.
"""
from __future__ import annotations

import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs" / "architecture-presentation.html"
DEMO = ROOT / "demo" / "architecture-presentation.html"


def t(x, y, value, cls="svg-small", *, color=None, anchor=None, size=None):
    attrs = f' x="{x}" y="{y}" class="{cls}"'
    if anchor:
        attrs += f' text-anchor="{anchor}"'
    style = []
    if color:
        style.append(f"fill:var(--{color})")
    if size:
        style.append(f"font-size:{size}px")
    if style:
        attrs += f' style="{";".join(style)}"'
    return f'<text{attrs}>{html.escape(str(value))}</text>'


def card(x, y, w, h, title, lines, kind="node", delay="", *, title_color=None):
    out = [f'<g class="reveal {delay}"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" class="{kind}"/>',
           t(x + 22, y + 46, title, "svg-strong", color=title_color)]
    for i, line in enumerate(lines):
        if isinstance(line, tuple):
            value, color = line
            out.append(t(x + 22, y + 90 + 32 * i, value, "svg-mono", color=color))
        else:
            out.append(t(x + 22, y + 90 + 32 * i, line))
    return "".join(out) + "</g>"


def slide(num, duration, title, sub, visual, note, foot, details):
    cls = "slide active" if num == 1 else "slide"
    return (f'<section class="{cls}" data-duration="{duration}" data-note="{html.escape(note, quote=True)}">'
            f'<p class="eyebrow">{num:02d} / {html.escape(foot[0])}</p>'
            f'<h1>{html.escape(title)}</h1><p class="sub">{sub}</p>'
            f'<svg class="visual" viewBox="0 0 1200 470" role="img" aria-label="{html.escape(details[0], quote=True)}">'
            f'{visual}</svg><div class="foot"><span>{foot[1]}</span><span>{duration} s</span></div></section>')


def build():
    review = json.loads((ROOT / "toy" / "out" / "review.json").read_text(encoding="utf-8"))
    accepted = json.loads((ROOT / "toy" / "out" / "accept.json").read_text(encoding="utf-8"))
    claims = {c["id"]: c for c in review["claims"]}
    assert claims["A1"]["label"] == "Refuted" and claims["A1"]["checked"] == 16
    assert claims["P1"]["label"] == "Proved within scope" and claims["P1"]["checked"] == 4
    assert claims["B1"]["label"] == "Refuted"
    assert claims["D1"]["label"] == claims["D2"]["label"] == "Refuted"
    assert all(accepted["results"][c]["verdict"] == "Proved within scope" for c in ("A1", "B2", "D1", "D2"))

    slides = []
    details = []

    # 1 · Start with a business-level promise and zoom to the changed line.
    v = card(18, 65, 270, 245, "Product promise", ["A sale must not", "reduce revenue."], "node-blue")
    v += card(315, 65, 270, 245, "Sale flow", ["post_sale()", "calls checkout()"], "node", "delay1")
    v += card(612, 65, 270, 245, "Price function", ["checkout() calls", "final_price()"], "node", "delay2")
    v += card(909, 65, 270, 245, "Changed line", [("min(d, .5)", "red"), "caps each discount"], "node-red", "delay3")
    v += '<path d="M288 185 H315 M585 185 H612 M882 185 H909" class="edge-hot route r1"/>'
    v += t(600, 385, "One business promise narrows to one line of code.", "svg-strong", anchor="middle")
    slides.append(slide(1, 12, "Zoom from a promise to one line.",
        "A large review becomes a path: <b>promise → call chain → changed line</b>.", v,
        "Start wide: a sale must not reduce revenue. Follow post_sale through checkout to final_price and its changed discount cap.",
        ("THE DRILL-DOWN", "Actual four-PR toy shop; the same path is visible in the proof tableau."),
        ("Product promise, sale flow, price function, and changed discount line form a drill-down path.",)))
    details.append("<b>Source:</b> toy PR #4. The call edges are found by parsing the toy code. The changed lines are linked to claim IDs in toy/out/review.json. The line alone is not a theorem; its behavior is checked against requirements.")

    # 2 · One changed line can carry several independent obligations.
    v = card(15, 18, 590, 420, "Code excerpt · shop/prices.py", [
        ("MAX_DISCOUNT = 0.5", "red"),
        ("capped = [min(d, MAX_DISCOUNT)", "red"),
        ("          for d in discounts]", "red"),
        ("return base * (1 - sum(capped))", "red"),
        "Source lines 1, 6, 7 (line 6 wrapped)"
    ], "node", "")
    v += card(655, 15, 525, 125, "A1 · price promise", ["Every basket total ≥ 0"], "node-blue", "delay1")
    v += card(655, 170, 525, 125, "B1 · earlier VIP promise", ["A 60% coupon still gives 60%"], "node-amber", "delay2")
    v += card(655, 325, 525, 125, "P1 · ordinary shoppers", ["No-coupon price stays the same"], "node-green", "delay3")
    v += '<path d="M605 220 H630 V77 H655 M630 232 H655 M630 387 H655" class="edge-hot route r1"/>'
    slides.append(slide(2, 14, "One code change. Three claims.",
        "The diff identifies the line. Requirements and history tell us which <b>behaviors</b> that line must preserve.", v,
        "The changed discount line links to three separate claims: no negative total, VIP still gets 60 percent, and no-coupon shoppers are unchanged. A line points to claims; it is not automatically translated into a theorem.",
        ("CODE → CLAIMS", "Line links: toy/out/review.json · source: shop/prices.py at toy PR #4"),
        ("Changed price code on the left connects to three independent candidate claims on the right.",)))
    details.append("<b>Mechanism:</b> git diff locates changed lines; the review attaches A1, B1 and P1 to those lines. A1 comes from the product promise, B1 from PR #2 history, and P1 from a regression obligation. Each claim has its own formula, scope and checker.")

    # 3 · Quantification and negation make a universal promise falsifiable.
    v = card(20, 55, 555, 230, "A1 · universal claim", [("∀ b ∈ B₁₆ : total(b) ≥ 0", "teal"), "Every listed basket is nonnegative."], "node-blue")
    v += card(625, 55, 555, 230, "Negate to seek a witness", [("∃ b ∈ B₁₆ : total(b) < 0", "red"), "One negative basket refutes A1."], "node-red", "delay1")
    v += '<path d="M575 165 H625" class="edge-hot route r1"/>'
    v += card(165, 335, 870, 110, "Declared finite domain", ["4 coupons × 2 quantities × 2 member states = 16 baskets"], "node", "delay2")
    slides.append(slide(3, 12, "Classical logic tells us what to try.",
        "A universal claim is refuted by <b>one existential counterexample</b> within its stated domain.", v,
        "A1 says every listed basket has a nonnegative total. Negate that: does any basket have a negative total? Four coupons times two quantities times two membership states give sixteen concrete cases.",
        ("CLAIM → TEST", "Rule R-RUN · finite scope stated explicitly · python toy/review.py --check A1"),
        ("Universal claim, its existential negation, and the finite 16-basket domain.",)))
    details.append("<b>Classical logic:</b> ¬∀b P(b) ≡ ∃b ¬P(b). B₁₆ is declared exhaustive only for the listed coupon, quantity and membership combinations. A refutation needs one witness; a proof within scope needs every listed case checked.")

    # 4 · The actual checker result, rendered as a finite tableau.
    coupon_rows = [("NONE", 0), ("WELCOME", .1), ("HALF", .5), ("VIP", .6)]
    cols = [(1, False), (1, True), (10, False), (10, True)]
    v = t(28, 43, "COUPON", "svg-mono")
    for j, (qty, member) in enumerate(cols):
        v += t(280 + 188 * j, 43, f"{qty}× / {'M' if member else '—'}", "svg-mono", anchor="middle")
    for i, (coupon, discount) in enumerate(coupon_rows):
        y = 70 + 88 * i
        v += t(28, y + 49, coupon, "svg-strong")
        for j, (qty, member) in enumerate(cols):
            total = round(100 * qty * (1 - min(discount, .5) - (.4 if qty >= 10 else 0) - (.2 if member else 0)))
            x = 195 + 188 * j
            bad = total < 0
            v += f'<g class="reveal delay{min(i + 1, 4)}"><rect x="{x}" y="{y}" width="170" height="72" rx="9" class="{"node-red" if bad else "node-green"}"/>'
            v += t(x + 85, y + 47, str(total), "svg-strong", color="red" if bad else "green", anchor="middle") + '</g>'
    v += card(950, 77, 235, 325, "RESULT · A1", [("16 checked", "teal"), ("14 pass", "green"), ("2 fail", "red"), ("HALF × 10 × M", "red"), ("total = −100", "red")], "node-red", "delay4")
    slides.append(slide(4, 12, "The 16-case tableau finds a witness.",
        "Two cells are red. <b>HALF + bulk + member</b> gives a total of −100, so A1 is refuted.", v,
        "The checker executes all sixteen baskets. Fourteen are nonnegative; two are negative. HALF coupon, ten items, member yields minus one hundred. That is a concrete witness, not an AI opinion.",
        ("CHECK → REFUTED", "Executed result: A1 Refuted · 16 checked · witnesses in toy/out/review.json"),
        ("Sixteen actual basket totals in a four-by-four grid; two negative cells and the A1 verdict.",)))
    details.append("<b>Executed evidence:</b> toy/out/review.json records A1 as Refuted, checked 16, with witnesses HALF and VIP at quantity 10 with membership. Run python toy/review.py --check A1. The green cells are true for their listed inputs; they do not rescue the universal claim.")

    # 5 · Walk the same witness back out through real callers.
    v = card(15, 65, 355, 245, "A1 · final_price()", [("total = −100", "red"), "HALF × 10 · member", ("REFUTED", "red")], "node-red")
    v += card(422, 65, 355, 245, "D1 · checkout()", [("points = −10", "red"), "same basket, one hop", ("REFUTED", "red")], "node-red", "delay1")
    v += card(829, 65, 355, 245, "D2 · post_sale()", [("1000 → 900", "red"), "same basket, two hops", ("REFUTED", "red")], "node-red", "delay2")
    v += '<path d="M370 186 H422 M777 186 H829" class="edge-hot route r1"/>'
    v += t(600, 387, "Graph edge = where to check. Executed result = verdict.", "svg-strong", anchor="middle")
    slides.append(slide(5, 14, "The same witness climbs back up.",
        "The graph finds callers; <b>separate executions</b> show whether the failure reaches them.", v,
        "We pass the same failing basket up the call chain. It gives minus ten loyalty points, then lowers revenue from one thousand to nine hundred. D1 and D2 become findings only after their own checks run.",
        ("PROPAGATE → CHECK", "R-CALL · Python AST finds the path · python toy/review.py --check D1 / D2"),
        ("Failing basket propagates through final_price, checkout and post_sale with three checked results.",)))
    details.append("<b>Propagation:</b> Python AST confirms final_price → checkout → post_sale. The A1 witness selects a useful input; R-CALL executes each caller separately. D1 and D2 are Refuted on both stored witnesses, checked 2 each. A call edge alone is never a verdict.")

    # 6 · The same line affects an older promise, while another claim passes.
    v = card(15, 40, 355, 250, "PR #2 · promise", ["VIP coupon = 60%", "price of 100 → 40"], "node-blue")
    v += card(422, 40, 355, 250, "PR #4 · changed line", [("min(.60, .50)", "red"), "VIP is capped to 50%"], "node", "delay1")
    v += card(829, 40, 355, 250, "B1 · checked result", [("actual price = 50", "red"), ("expected = 40", "teal"), ("REFUTED", "red")], "node-red", "delay2")
    v += '<path d="M370 160 H422 M777 160 H829" class="edge-hot route r1"/>'
    v += card(185, 340, 830, 105, "P1 · ordinary shoppers", [("No-coupon prices unchanged · 4/4 checked → PROVED WITHIN SCOPE", "green")], "node-green", "delay3")
    slides.append(slide(6, 12, "One line can fail and preserve different claims.",
        "The VIP promise is falsified. The no-coupon regression claim <b>passes all four scoped cases</b>.", v,
        "An earlier PR promised a sixty percent VIP discount. The new cap changes a price of forty to fifty, refuting B1. But ordinary no-coupon prices are unchanged in all four listed cases, so P1 is proved within scope.",
        ("HISTORY → TWO VERDICTS", "B1 Refuted · P1 Proved within scope · source: toy/out/review.json"),
        ("Earlier VIP promise meets the changed cap and fails, while no-coupon behavior passes four checks.",)))
    details.append("<b>R-HIST:</b> B1 compares coupon behavior before and after PR #4, and VIP is its counterexample. <b>R-RUN:</b> P1 compares the four no-coupon baskets across the two commits and finds equality for all four. The same changed line legitimately links to both claims.")

    # 7 · Small, independent Boolean example of the same logical move.
    v = card(15, 20, 560, 155, "Policy · illustrative", [("recent OR defective", "teal")], "node-blue")
    v += card(625, 20, 560, 155, "AI patch · illustrative", [("return recent AND defective", "red")], "node", "delay1")
    labels = [("neither", "no / no", False), ("defective only", "yes / no", True), ("recent only", "yes / no", True), ("both", "yes / yes", False)]
    for i, (name, result, bad) in enumerate(labels):
        x = 15 + i * 300
        v += card(x, 230, 275, 185, name, ["policy / code", (result, "red" if bad else "green"), ("MISMATCH" if bad else "MATCH", "red" if bad else "green")], "node-red" if bad else "node-green", f"delay{min(i + 1, 4)}")
    slides.append(slide(7, 12, "Even a one-word change needs a claim.",
        "Four Boolean inputs make this small rule completely checkable. <b>Two mismatches refute it.</b>", v,
        "Here is the same method on a simple illustrative rule: refund if recent or defective. The patch says and. Both true and both false still match, but either condition alone fails. Code becomes a four-case claim, and two cases falsify it.",
        ("SMALL EXAMPLE · ILLUSTRATIVE", "Illustration only; the shop results on the other slides come from executed repository checks."),
        ("Refund policy and one-line patch lead to a four-case Boolean truth table with two mismatches.",)))
    details.append("<b>Finite model:</b> ∀ r,d ∈ {False,True}: refund_ok(r,d) = r ∨ d. The patch implements r ∧ d. The two mixed assignments are countermodels. This is an illustrative truth table, not a claim about the MessagePack or shop code.")

    # 8 · A compact ledger keeps both positive and negative outcomes visible.
    rows = [
        ("A1", "Price ≥ 0", "16 baskets", "REFUTED", "red"),
        ("D1", "Points ≥ 0", "2 witnesses", "REFUTED", "red"),
        ("D2", "Revenue never falls", "2 witnesses", "REFUTED", "red"),
        ("B1", "VIP remains 60%", "3 coupons", "REFUTED", "red"),
        ("P1", "No-coupon unchanged", "4 baskets", "PROVED IN SCOPE", "green"),
        ("U1", "Stacking is intended", "human policy", "UNKNOWN", "amber"),
    ]
    v = t(18, 35, "CLAIM", "svg-mono") + t(140, 35, "BEHAVIOR", "svg-mono") + t(620, 35, "CHECKED SCOPE", "svg-mono") + t(910, 35, "RESULT", "svg-mono")
    for i, (cid, name, scope, verdict, color) in enumerate(rows):
        y = 58 + i * 65
        v += f'<g class="reveal delay{min(i // 2 + 1, 4)}"><rect x="10" y="{y}" width="1180" height="58" rx="8" class="node"/>'
        v += t(27, y + 38, cid, "svg-strong", color="teal") + t(140, y + 38, name, "svg-small")
        v += t(620, y + 38, scope, "svg-mono") + t(910, y + 38, verdict, "svg-mono", color=color) + '</g>'
    slides.append(slide(8, 12, "Here are the actual review results.",
        "A finding is a <b>claim plus checked scope and evidence</b>. Unanswered intent stays Unknown.", v,
        "The ledger shows the outcomes together: four refuted claims, one scoped proof, and one question of business intent marked unknown. The system never turns an untested lead into a confirmed defect.",
        ("RESULT LEDGER", 'Actual toy/out/review.json · re-run python toy/review.py · <a href="toy/review.html">full receipt ↗</a>'),
        ("Six-row review ledger showing refuted, proved within scope, and unknown results.",)))
    details.append("<b>Verdict semantics:</b> Refuted requires a witness; Proved within scope requires every declared finite case to pass; Tested means samples passed; Unknown means no decisive checker or a human policy question. The table reads from toy/out/review.json.")

    # 9 · Place logic inside the full collaboration architecture.
    v = card(20, 45, 355, 235, "Entire · context", ["Session → commit → Trail", "Why the agent changed it", "Missing session → Unknown"], "node-amber")
    v += card(423, 45, 355, 235, "Claim engine · logic", ["Diff line → claim", "Rule → checker → witness", "Verdict has declared scope"], "node-blue", "delay1")
    v += card(826, 45, 355, 235, "MongoDB · ledger", ["Nodes, edges, traversals", "Impact path and token cost", "Re-walkable evidence"], "node", "delay2")
    v += '<path d="M375 160 H423 M778 160 H826" class="edge-hot route r1"/>'
    v += t(600, 365, "Context explains. Logic checks. The ledger remembers.", "svg-strong", anchor="middle")
    slides.append(slide(9, 10, "Three roles, one auditable review.",
        "Entire carries agent context and the Trail. Classical logic decides scoped claims. MongoDB records the traversal.", v,
        "Entire carries the session and the Trail. The claim engine binds code to a precise obligation and checker. MongoDB records which graph nodes were visited and what evidence was used. Missing context stays unknown.",
        ("ARCHITECTURE", '<a href="brain-compare.html">Entire context comparison ↗</a> · Mongo graph traversal is re-walkable'),
        ("Entire context, logic checker, and MongoDB audit ledger connected left to right.",)))
    details.append("<b>Boundaries:</b> Entire context can establish recorded intent but cannot prove code behavior. The checker decides scoped behavior. MongoDB stores graph paths and traversal ledgers; it does not decide truth. Human acceptance is a separate act.")

    # 10 · The same checks run after a correction; the human owns acceptance.
    v = card(20, 45, 550, 325, "PR #4 · AI patch", [("A1 price: REFUTED", "red"), ("B1 VIP: REFUTED", "red"), "AI: request changes", "Human: pending"], "node-red")
    v += card(630, 45, 550, 325, "PR #5 · corrected", [("A1: 16/16 pass", "green"), ("VIP: price 40", "green"), ("D1 + D2: 16/16 pass", "green"), "Named human: approved"], "node-green", "delay1")
    v += '<path d="M570 198 H630" class="edge-hot route r1"/>'
    v += t(600, 430, "The AI brings a receipt. The human owns the decision.", "svg-strong", anchor="middle")
    slides.append(slide(10, 10, "The fix earns a new decision.",
        "The corrected patch reruns the <b>same obligations</b>. A named engineer accepts the remaining risk.", v,
        "PR five caps the total discount at one hundred percent while preserving VIP's sixty percent. The same checks now pass within their listed scopes. Saleeta Qadir approved the corrected sample on the Entire Trail. The AI cannot sign.",
        ("PROOF-CARRYING REVIEW", 'toy/out/accept.json · <a href="https://entire.com/et/earned-trust-review/-/trails/2" target="_blank" rel="noopener">Entire Trail #2 ↗</a>'),
        ("PR four refuted results beside PR five corrected scoped results and named human approval.",)))
    details.append("<b>Executed correction:</b> toy/out/accept.json records A1, B2, D1 and D2 as Proved within scope; T1 as Tested; U1 as Unknown, with human policy resolution recorded. The corrected sample was approved by Saleeta Qadir on Entire Trail #2.")

    durations = [12, 14, 12, 12, 14, 12, 12, 12, 10, 10]
    assert sum(durations) == 120 and len(slides) == len(details) == 10
    source = DOCS.read_text(encoding="utf-8")
    prefix = source.split('<section class="slide active"', 1)[0]
    controls = '''</main><div class="controls"><button id="prev" aria-label="Previous scene">←</button><button id="next">Next scene →</button><button id="auto" class="primary">Present 2:00</button><button id="notesBtn" aria-label="Toggle speaker notes">Notes</button><button id="detailsBtn" aria-label="Toggle deep-dive details">Details</button><a class="tableau-link" href="formal-tableau.html">16-case tableau ↗</a><span class="counter" id="counter">1 / 10</span><div class="progress" aria-label="Presentation progress"><span id="bar"></span></div><span class="counter" id="clock">2:00</span></div><aside class="notes" id="notes"><b>Say this:</b> <span id="noteText"></span></aside><aside class="notes" id="details" style="display:none"><b>Technical detail:</b> <span id="detailText"></span></aside></div>'''
    script = '''<script>
const DETAILS=__DETAILS__;
const slides=[...document.querySelectorAll('.slide')],durations=slides.map(s=>Number(s.dataset.duration)),total=durations.reduce((a,b)=>a+b,0);let current=0,running=false,started=0,elapsed=0,raf=0;
function show(n){current=Math.max(0,Math.min(slides.length-1,n));slides.forEach((s,i)=>s.classList.toggle('active',i===current));document.getElementById('counter').textContent=`${current+1} / ${slides.length}`;document.getElementById('prev').disabled=current===0;document.getElementById('next').disabled=current===slides.length-1;document.getElementById('noteText').textContent=slides[current].dataset.note;document.getElementById('detailText').innerHTML=DETAILS[current];document.getElementById('bar').style.width=`${durations.slice(0,current).reduce((a,b)=>a+b,0)/total*100}%`}
function format(sec){return `${Math.floor(sec/60)}:${String(Math.floor(sec%60)).padStart(2,'0')}`}
function tick(){if(!running)return;elapsed=(performance.now()-started)/1000;let sum=0,index=slides.length-1;for(let i=0;i<durations.length;i++){sum+=durations[i];if(elapsed<sum){index=i;break}}if(index!==current)show(index);document.getElementById('clock').textContent=format(Math.max(0,total-elapsed));document.getElementById('bar').style.width=`${Math.min(100,elapsed/total*100)}%`;if(elapsed>=total){stop();document.getElementById('clock').textContent='0:00';return}raf=requestAnimationFrame(tick)}
function stop(){running=false;cancelAnimationFrame(raf);document.getElementById('auto').textContent='Present 2:00'}
function start(){stop();show(0);elapsed=0;started=performance.now();running=true;document.getElementById('auto').textContent='Pause';raf=requestAnimationFrame(tick)}
document.getElementById('prev').onclick=()=>{stop();show(current-1)};document.getElementById('next').onclick=()=>{stop();show(current+1)};document.getElementById('auto').onclick=()=>running?stop():start();document.getElementById('notesBtn').onclick=()=>document.getElementById('notes').classList.toggle('show');document.getElementById('detailsBtn').onclick=()=>document.getElementById('details').classList.toggle('show');
document.addEventListener('keydown',e=>{if(e.key==='ArrowRight'||e.key===' '){e.preventDefault();stop();show(current+1)}else if(e.key==='ArrowLeft'){e.preventDefault();stop();show(current-1)}else if(e.key.toLowerCase()==='n'){document.getElementById('notes').classList.toggle('show')}else if(e.key.toLowerCase()==='d'){document.getElementById('details').classList.toggle('show')}});
show(0);
</script></body></html>'''.replace("__DETAILS__", json.dumps(details, ensure_ascii=False))
    output = prefix + "\n\n".join(slides) + controls + script
    DOCS.write_text(output, encoding="utf-8")
    DEMO.write_text(output, encoding="utf-8")
    print(f"wrote {len(slides)} slides / {sum(durations)} s to {DOCS} and {DEMO}")


if __name__ == "__main__":
    build()
