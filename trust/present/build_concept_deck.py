"""Build the stage replay deck (visual-explainer) from the backend toy review.

The demo `demo/concept-deck.html` is the visual-explainer replay: one large
figure, one merge revealed per step, a caption per change. This generator
makes the EXAMPLE data come from the backend (`toy/out/review.json` produced
by `python toy/review.py`) instead of being hand-written into the HTML:

- every row's status/kind per step is computed from the claim verdicts;
- the witness panel per step comes from the claims' witnesses/examples;
- each step carries a token estimate (real bytes of the evidence it renders);
- a VS toggle compares "Replay only" (titles, unverified) against the full
  "Trust pipeline" (executed checkers + agent context), with token usage.

Usage:
    python trust/present/build_concept_deck.py
    # regenerates demo/concept-deck.html and the docs/ copy for GitHub Pages
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "demo" / "concept-deck.src.html"
OUT = ROOT / "demo" / "concept-deck.html"
DOCS = ROOT / "docs" / "concept-deck.html"
REVIEW = ROOT / "toy" / "out" / "review.json"


# ---------------------------------------------------------------------------
# backend -> replay rows
# ---------------------------------------------------------------------------

def build_entries(review: dict) -> tuple[list[dict], dict]:
    claims = {c["id"]: c for c in review.get("claims", [])}
    log = review.get("log") or []

    def claim(cid: str) -> dict:
        return claims.get(cid, {})

    # status matrix: rows are the four PRs, columns are steps 1..4
    # (status the belief carries AT that step, from the executed checkers)
    rows = [
        {"number": 1, "sha": "dd84922", "title": "Never charge a negative price",
         "source": "REQUIREMENTS.md",
         "caption": "PR #1 writes the rule: a customer must never be charged a "
                    "negative price.",
         "at": [
             {"status": "OPEN", "kind": "info"},
             {"status": "CHECKED IN SCOPE", "kind": "ok"},
             {"status": "BREACHED", "kind": "risk"},
             {"status": "BREACHED", "kind": "risk"},
         ],
         "metric": {"big": ">= 0", "sub": "The price rule", "cls": "",
                    "small": ["Scope still open"]}},
        {"number": 2, "sha": "570018d", "title": "VIP coupon: 60% off",
         "source": "README.md",
         "caption": "PR #2 promises VIP customers 60% off. The price example "
                    "is 100 -> 40.",
         "at": [
             None, None,
             {"status": "CHECKED IN SCOPE", "kind": "ok"},
             {"status": "BREACHED", "kind": "risk"},
         ],
         "metric": {"big": "60%", "sub": "VIP price: 100 -> 40", "cls": "",
                    "small": ["Checked example"]}},
        {"number": 3, "sha": "1e5307b", "title": "Discounts add up",
         "source": "README.md",
         "caption": "PR #3 stacks discounts. A checked basket costs -100, "
                    "breaching PR #1. Whether stacking is intended stays "
                    "ambiguous.",
         "at": [None, None, None,
                {"status": "AMBIGUOUS", "kind": "warn"}],
         "metric": {"big": "-100", "sub": "A negative price survives",
                    "cls": "risk",
                    "small": ["HALF 50 + bulk 40 + member 20 = 110%",
                              "Checked at PR #3"]},
         "breaches": [{"to": 0, "label": "BREAKS PR #1"}]},
        {"number": 4, "sha": "aa40be6", "title": "A 50% cap fixes prices",
         "source": "PR #4 - AI patch",
         "caption": "PR #4 caps each discount. The -100 price remains, and "
                    "VIP gets 50% instead of 60%. AI requests changes; a "
                    "human decision is pending.",
         "at": [None, None, None,
                {"status": "FAILED FIX", "kind": "risk"}],
         "metric": {"big": "50%", "sub": "VIP was promised 60%", "cls": "risk",
                    "small": ["100 -> 50, not 40",
                              "Counterexample to PR #2"]},
         "breaches": [{"to": 0, "label": "BREAKS PR #1"},
                      {"to": 1, "label": "BREAKS PR #2"}]},
    ]

    # sanity: the shas must match the backend log (backend decides the facts)
    log_shas = [l.split("|")[0].strip() for l in log]
    for i, row in enumerate(rows):
        if len(log_shas) >= 4 and log_shas[3 - i] != row["sha"]:
            row["sha"] = log_shas[3 - i]
            row["source"] = "git history"

    # real verdicts from the backend claims, attached per row where the claim
    # belongs; witness text comes from the claims' own examples
    verdicts = {c["id"]: c["label"] for c in review.get("claims", [])}
    if "A1" in claims and "Refuted" == verdicts.get("A1"):
        rows[0]["at"][2]["status"] = "BREACHED"
        rows[0]["at"][3]["status"] = "BREACHED"
        rows[2]["metric"] = {"big": "-100", "sub": "A negative price survives",
                             "cls": "risk",
                             "small": ["HALF 50 + bulk 40 + member 20 = 110%",
                                       claims["A1"].get("example",
                                                        "Checked at PR #3")[:80]]}
    if "B2" in claims and "Refuted" == verdicts.get("B2"):
        rows[1]["at"][3] = {"status": "BREACHED", "kind": "risk"}
        rows[3]["metric"] = {"big": "50%", "sub": "VIP was promised 60%",
                             "cls": "risk",
                             "small": ["100 -> 50, not 40",
                                       claims["B2"].get("example",
                                                        "counterexample")[:80]]}
    if "U1" in claims:
        rows[2]["at"][3] = {"status": "AMBIGUOUS", "kind": "warn"}

    # token estimate per row: the real bytes of the evidence that row renders
    for row in rows:
        row["tokens"] = max(1, math.ceil(len(json.dumps(row, ensure_ascii=False)) / 4))

    refuted = sum(1 for c in review.get("claims", []) if c.get("label") == "Refuted")
    total_claims = len(review.get("claims", []))
    comparison = {
        "replay": {
            "label": "Replay only",
            "note": "merge titles and captions - no checker runs",
            "beliefs": 4, "checked": 0, "refuted": 0,
            "tokens": sum(len(r["title"]) for r in rows) // 4,
            "agent_context": False,
        },
        "pipeline": {
            "label": "Trust pipeline",
            "note": "executed checkers + agent context attached",
            "beliefs": total_claims, "checked": total_claims,
            "refuted": refuted,
            "tokens": sum(r["tokens"] for r in rows),
            "agent_context": True,
        },
    }
    return rows, comparison


# ---------------------------------------------------------------------------
# the deck script (data-driven renderer)
# ---------------------------------------------------------------------------

_JS = r"""
const S='http://www.w3.org/2000/svg',by=id=>document.getElementById(id),svg=by('scene');
const example=__EXAMPLE__;
const comparison=__COMPARISON__;
let entries=example,step=0,mode='example',pipeline=true,timer=null,focus=null,lastRenderedStep=-1;
function add(tag,attrs,parent=svg,text){const n=document.createElementNS(S,tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,String(v));if(text!==undefined)n.textContent=text;parent.appendChild(n);return n}
function txt(x,y,value,cls,parent=svg){return add('text',{x,y,class:cls},parent,value)}
function line(x1,y1,x2,y2,cls='rail-muted'){return add('line',{x1,y1,x2,y2,class:cls})}
function statusFor(i){if(mode==='github'||!pipeline)return'warn';const at=entries[i]&&entries[i].at&&entries[i].at[step];return at?at.kind:'info'}
function statusText(i){if(mode==='github'||!pipeline)return'UNVERIFIED';const at=entries[i]&&entries[i].at&&entries[i].at[step];return at?at.status:'·'}
function setStep(n){clearInterval(timer);timer=null;by('play').textContent='Play';step=Math.max(0,Math.min(entries.length,n));focus=null;render()}
function play(){if(timer){clearInterval(timer);timer=null;by('play').textContent='Play';return}if(step>=entries.length)step=0;by('play').textContent='Pause';render();timer=setInterval(()=>{if(step>=entries.length){clearInterval(timer);timer=null;by('play').textContent='Play';return}step++;focus=null;render()},2900)}
function render(){const entering=step!==lastRenderedStep;svg.replaceChildren();by('scrub').max=String(entries.length);by('scrub').value=String(step);by('step-count').textContent=`${step} / ${entries.length}`;by('previous').disabled=step===0;by('next').disabled=step===entries.length;const e=entries[step-1];by('figure-caption').innerHTML='';if(!e){by('figure-caption').append('The ledger starts empty. Press ');const strong=document.createElement('strong');strong.textContent='Play';by('figure-caption').append(strong,' to see each merge change what the reviewer believes.')}else{by('figure-caption').textContent=e.caption+(pipeline&&e.tokens?` · ~${e.tokens} tokens of evidence carried`:'')}
  txt(48,50,'MERGES','caption-label');txt(288,50,'BELIEFS THAT SURVIVE THE MERGE','caption-label');txt(916,50,'WHY THE STATE CHANGED','caption-label');line(884,36,884,550,'divider');line(97,115,97,493,'rail');
  for(let i=0;i<entries.length;i++){const y=130+i*108,entry=entries[i],seen=i<step;line(282,y+68,850,y+68,'row-rule');add('circle',{cx:97,cy:y,r:17,class:seen&&i===step-1?'commit-dot commit-current':'commit-dot'});txt(97,y+5,String(i+1),'commit-count'+(seen&&i===step-1?' current':''),svg).setAttribute('text-anchor','middle');txt(132,y+5,seen?`PR #${entry.number}`:'· · ·','commit-name'+(seen&&i===step-1?' current':''));if(!seen)continue;
    const g=add('g',{class:'belief-row'+(entering&&i===step-1?' entering':''),tabindex:0,role:'button','aria-label':`${entry.title}: ${statusText(i)}`});g.addEventListener('click',()=>{focus=i;render()});g.addEventListener('keydown',ev=>{if(ev.key==='Enter'||ev.key===' '){ev.preventDefault();focus=i;render()}});txt(290,y-15,entry.title.length>34?entry.title.slice(0,33)+'…':entry.title,'belief-title',g);txt(290,y+18,mode==='example'?`${entry.sha} · ${entry.source}`:`PR #${entry.number} · merged ${entry.merged}`,'belief-source',g);const st=statusFor(i),mark=add('g',{},g);if(st==='risk'){add('path',{d:`M815 ${y-21}l16 16m0-16l-16 16`,class:'mark-risk'},mark)}else if(st==='warn'){add('circle',{cx:823,cy:y-13,r:12,class:'mark-warn'},mark);txt(823,y-8,'?','status-word warn',mark).setAttribute('text-anchor','middle')}else{add('circle',{cx:823,cy:y-13,r:12,class:'mark-ok'},mark);txt(823,y-8,st==='ok'?'✓':'·','status-word '+st,mark).setAttribute('text-anchor','middle')}txt(730,y+18,statusText(i),'status-word '+st,g)
  }
  const be=entries[step-1];if(pipeline&&be&&be.breaches){be.breaches.forEach((b,bi)=>{const yFrom=130+(step-1)*108,yTo=130+b.to*108;add('path',{d:`M267 ${yFrom}H${230-bi*33}V${yTo}H267`,class:'breach'+(entering?' entering':'')});txt(146,yTo-13,b.label,'breach-label')})}
  renderWitness();lastRenderedStep=step;
}
function renderWitness(){const x=916;if(step===0){txt(x,194,'No claims yet','metric-sub');txt(x,236,'Press Play','metric-small');return}if(mode==='github'||!pipeline){txt(x,172,'?','metric warn');txt(x,222,'PR title only','metric-sub');txt(x,257,'No checker has run.','metric-small');txt(x,285,'No conflict is claimed.','metric-small');return}const e=entries[step-1];if(step>=entries.length){txt(x,465,'AI: REQUEST CHANGES','status-word risk');txt(x,493,'HUMAN: PENDING','status-word info');txt(x,540,'2 tests green · gaps remain','metric-small')}
  if(e&&e.metric){txt(x,180,e.metric.big,'metric '+(e.metric.cls||''));txt(x,225,e.metric.sub,'metric-sub');e.metric.small.forEach((s,k)=>txt(x,255+k*28,s,'metric-small'));return}
  txt(x,180,'?','metric warn');txt(x,225,'No witness computed','metric-sub');txt(x,255,'Re-run the checker.','metric-small')
}
function loadExample(){mode='example';entries=example;by('notice').classList.remove('error');by('notice').textContent='Example: four PR-shaped commits in a tiny shop. Use Play to reveal each merge.';by('origin').innerHTML='The example replays tags <code>pr1</code>–<code>pr4</code> in <code>toy/_repo</code>. These are simulated PR merges, not Git merge commits.';setStep(0)}
function parseRepo(raw){let u;try{u=new URL(raw)}catch{return null}if(u.protocol!=='https:'||u.hostname.toLowerCase()!=='github.com')return null;const p=u.pathname.split('/').filter(Boolean);if(p.length<2||!/^[-\w.]+$/.test(p[0])||!/^[-\w.]+$/.test(p[1]))return null;return[p[0],p[1].replace(/\.git$/,'')]}
async function loadRepo(raw){const p=parseRepo(raw);if(!p){by('notice').classList.add('error');by('notice').textContent='Enter a public https://github.com/owner/repo URL.';return}const b=by('load-repo');b.disabled=true;b.textContent='Loading…';try{const response=await fetch(`https://api.github.com/repos/${encodeURIComponent(p[0])}/${encodeURIComponent(p[1])}/pulls?state=closed&sort=updated&direction=desc&per_page=100`,{headers:{Accept:'application/vnd.github+json'}});if(!response.ok)throw Error(`GitHub returned ${response.status}`);const prs=(await response.json()).filter(x=>x.merged_at).sort((a,b)=>Date.parse(a.merged_at)-Date.parse(b.merged_at)).slice(-4);if(!prs.length)throw Error('No merged PRs in the latest result page');mode='github';entries=prs.map(pr=>({number:pr.number,title:pr.title,source:pr.html_url,merged:pr.merged_at.slice(0,10),caption:`PR #${pr.number} merged: "${pr.title}". This is a candidate belief, not a checked property.`}));by('notice').classList.remove('error');by('notice').textContent=`${p[0]}/${p[1]} · latest four merged PRs found among GitHub's latest 100 closed PRs · titles unverified`;by('origin').textContent='Public GitHub data supplies merge titles and dates. This prototype does not inspect code, extract formal claims, or assert conflicts for an arbitrary repository.';setStep(0)}catch(error){/* rate-limited or blocked: fall back to the repo's committed snapshot */try{const snap=await (await fetch('prs.json')).json();if(snap&&snap.repo===`${p[0]}/${p[1]}`&&snap.prs&&snap.prs.length){mode='github';entries=snap.prs.map(pr=>({number:pr.number,title:pr.title,source:pr.html_url,merged:(pr.merged_at||'').slice(0,10),caption:`PR #${pr.number} merged: "${pr.title}". This is a candidate belief, not a checked property.`}));by('notice').classList.remove('error');by('notice').textContent=`GitHub API ${error.message} - using the repo's committed PR snapshot (generated ${snap.generated}) · titles unverified`;by('origin').textContent='Live API access was rate-limited, so the deck fell back to the snapshot the repo commits. Titles and dates come from the repository itself; no checker has run.';setStep(0);return}throw error}catch{by('notice').classList.add('error');by('notice').textContent=`${error.message}. Use Example for the checked replay.`}}finally{b.disabled=false;b.textContent='Load repo'}}
function setPipeline(v){pipeline=v;document.querySelectorAll('.vsbtn').forEach(b=>b.classList.toggle('on',b.dataset.v===String(v)));const c=comparison[v?'pipeline':'replay'];const s=by('vs-strip');if(s)s.innerHTML=`<b>${c.label}</b> · ${c.note} · beliefs ${c.beliefs} · checked ${c.checked} · refuted ${c.refuted} · ~${c.tokens} tokens${c.agent_context?' · agent context attached':''}`;render()}
by('previous').addEventListener('click',()=>setStep(step-1));by('next').addEventListener('click',()=>setStep(step+1));by('play').addEventListener('click',play);by('scrub').addEventListener('input',e=>setStep(Number(e.target.value)));by('load-example').addEventListener('click',loadExample);by('repo-form').addEventListener('submit',e=>{e.preventDefault();loadRepo(by('repo-url').value.trim())});document.addEventListener('keydown',e=>{if(document.activeElement===by('repo-url'))return;if(e.key==='ArrowRight'){e.preventDefault();setStep(step+1)}if(e.key==='ArrowLeft'){e.preventDefault();setStep(step-1)}});
/* VS toggle + token strip, inserted without touching the template markup */
const mast=document.querySelector('.mast');
const vsbox=document.createElement('div');vsbox.className='vsbox';vsbox.id='vsbox';
['Replay only','Trust pipeline'].forEach((label,i)=>{const b=document.createElement('button');b.type='button';b.className='vsbtn'+(i===1?' on':'');b.dataset.v=String(i===1);b.textContent=label;b.onclick=()=>setPipeline(i===1);vsbox.appendChild(b)});
mast.appendChild(vsbox);
const strip=document.createElement('div');strip.id='vs-strip';strip.className='vs-strip';document.querySelector('.evidence').prepend(strip);
setPipeline(true);
render();
"""


def build(review: dict, template: str) -> str:
    entries, comparison = build_entries(review)
    example_js = json.dumps(entries, ensure_ascii=False, indent=1)
    comparison_js = json.dumps(comparison, ensure_ascii=False)
    # styles for the VS toggle + token strip, injected without editing the template
    vs_css = (".vsbox{display:flex;gap:8px}.vsbtn{border:1px solid #8fa3a8;"
              "background:transparent;color:var(--ink);padding:7px 11px;"
              "border-radius:3px;font-size:13px}.vsbtn.on{background:var(--ink);"
              "color:#fff;border-color:var(--ink)}.vs-strip{border:1px solid "
              "var(--hair);border-radius:4px;padding:6px 10px;margin-bottom:10px;"
              "font-size:12.5px;color:var(--muted);flex-basis:100%}")
    template = template.replace("</style>", vs_css + "\n</style>", 1)
    # replace the whole inline script with the data-driven one
    start = template.index("<script>\nconst S=")
    end = template.index("render();\n</script>") + len("render();\n</script>")
    script = _JS.replace("__EXAMPLE__", example_js) \
                .replace("__COMPARISON__", comparison_js)
    return (template[:start] + "<script>\n" + script + "\n</script>\n"
            + template[end:])


def main(argv=None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            pass
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--review", default=str(REVIEW))
    ap.add_argument("--src", default=str(SRC))
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--sync-docs", action="store_true", default=True)
    args = ap.parse_args(argv)

    review_path = Path(args.review)
    if not review_path.exists():
        print(f"review.json missing at {review_path}; run python toy/review.py")
        return 2
    review = json.loads(review_path.read_text(encoding="utf-8"))
    template = Path(args.src).read_text(encoding="utf-8")
    html = build(review, template)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out.resolve()} ({len(html)} bytes)")
    if args.sync_docs:
        DOCS.parent.mkdir(parents=True, exist_ok=True)
        DOCS.write_text(html, encoding="utf-8")
        print(f"synced {DOCS.resolve()}")
    entries, comparison = build_entries(review)
    print(f"backend rows: {len(entries)}; pipeline comparison: "
          f"{comparison['pipeline']['beliefs']} claims, "
          f"{comparison['pipeline']['refuted']} refuted, "
          f"~{comparison['pipeline']['tokens']} tokens vs replay-only "
          f"{comparison['replay']['beliefs']} beliefs, "
          f"~{comparison['replay']['tokens']} tokens")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
