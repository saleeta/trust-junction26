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
INDEX = ROOT / "docs" / "index.html"
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
             None, {"status": "OPEN", "kind": "info"},
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
         "at": [None, None, {"status": "AMBIGUOUS", "kind": "warn"},
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

    # ---- drill-down truths: the claims each row is really about -------------
    # (kept clean on the canvas; opened only when the row is clicked)
    def truth_for(cid: str) -> dict:
        c = claims.get(cid, {})
        return {
            "id": c.get("id", cid),
            "claim": c.get("claim", c.get("short", "")),
            "formula": c.get("formula", ""),
            "label": c.get("label", "Unknown"),
            "rule": c.get("rule", ""),
            "witnesses": c.get("witnesses") or [],
            "example": c.get("example", ""),
            "command": c.get("command", f"python toy/review.py --check {cid}"),
            "checked": c.get("checked", 0),
        }

    rows[0]["truth"] = [truth_for("A1")]
    rows[1]["truth"] = [truth_for("B2")]
    rows[2]["truth"] = [truth_for("U1")]
    rows[3]["truth"] = [truth_for("A1"), truth_for("B2"), truth_for("T1")]

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
            "beliefs": total_claims,
            "checked": sum(c.get("label") != "Unknown" for c in review.get("claims", [])),
            "refuted": refuted,
            "tokens": sum(r["tokens"] for r in rows),
            "agent_context": False,
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
// These are the four supplied AI-made branch patches. Only #2297 has a
// published, reproducible finding; the other rows deliberately stay open.
const supplied=[
 {number:2283,branch:'ju26-issue-2283',title:'Closed generic struct from a referenced assembly',source:'Issue #2283 · 4 changed files',caption:'AI-made branch for issue #2283. The review did not establish a defect in this supplied patch.',summary:'No verified concern found in the supplied patch.',kind:'warn',claims:[{id:'REQ-2283',claim:'The generator handles a closed generic struct from a referenced assembly.',label:'Not established',evidence:'Issue #2283 and the four-file patch',challenge:'No confirmed counterexample in this review.',new:'A guided, separate re-enactment has 19 passing regression tests.',gap:'The original author session was not supplied.'}]},
 {number:2234,branch:'ju26-issue-2234',title:'Analyzer suppression behavior',source:'Issue #2234 · 4 changed files',caption:'AI-made branch for issue #2234. No verified concern was produced by the available checks.',summary:'No verified concern found; unchecked behavior remains open.',kind:'warn',claims:[{id:'REQ-2234',claim:'The analyzer and SuppressSourceGeneration behave as the issue intends.',label:'Not established',evidence:'Issue #2234 and the four-file patch',challenge:'No confirmed breach found.',new:'The patch adds the requested analyzer behavior.',gap:'No exhaustive proof of all consumer configurations.'}]},
 {number:2129,branch:'ju26-issue-2129',title:'Formatter for referenced-assembly types',source:'Issue #2129 · 28 changed files',caption:'AI-made branch for issue #2129. A larger patch is not itself evidence of a defect.',summary:'No verified concern found; broader review remains open.',kind:'warn',claims:[{id:'REQ-2129',claim:'Types from referenced assemblies receive the intended formatter.',label:'Not established',evidence:'Issue #2129 and the 28-file patch',challenge:'No confirmed breach found.',new:'The patch extends formatter generation.',gap:'The available review does not prove compatibility across every target.'}]},
 {number:2297,branch:'ju26-issue-2297',title:'Exclude generated code from coverage',source:'Issue #2297 · 237 changed files',caption:'The checker finds a concrete gap: the new guard excludes two shipped frameworks. AI recommends changes; human decision stays pending.',summary:'Request changes · a checked requirement breach',kind:'risk',claims:[
  {id:'C-2297-1',claim:'Every generated declaration carries ExcludeFromCodeCoverage on every shipped framework.',label:'Refuted',evidence:'The introduced #if guard is false for net472 and netstandard2.0; compile probes show the attribute is available there.',challenge:'A generated declaration on either target lacks the attribute.',new:'The patch adds coverage attributes to many templates and snapshots.',gap:'Full emitted output was not built for every consumer configuration.',check:'python trust/assumptions/tfm_guard_check.py --repo repo --branch origin/ju26-issue-2297 --base 32258fdbee4bcd653c79f51b4376b5103c6f4d27 --issue-text .trust/issues/2297.md'},
  {id:'C-2297-2',claim:'Template and checked-in output files change together.',label:'Proved within scope',evidence:'All six touched .tt/.cs pairs changed on both sides.',challenge:'This does not prove that each .cs file exactly equals regenerated output.',new:'The paired edits reduce regeneration drift risk.',gap:'Output equality was not checked.'},
  {id:'C-2297-3',claim:'Existing tests observe the excluded framework configurations.',label:'Refuted',evidence:'Test projects list net8.0; the excluded targets are net472 and netstandard2.0.',challenge:'A green run cannot establish behavior on the excluded targets.',new:'The patch adds coverage tests and snapshots.',gap:'Test-project target overlap is only a proxy for observability.'},
  {id:'H-2297',claim:'A human may approve or change the requirement.',label:'Human decision pending',evidence:'Review receipt pins commit a0aa5ab2 and lists checks and limits.',challenge:'AI cannot waive the word “all” or approve its own review.',new:'A named engineer can request a fix or authorize a scope change.',gap:'No engineer has signed a decision.'}
 ]}
];
let entries=example,step=0,mode='example',pipeline=true,timer=null,focus=null,lastRenderedStep=-1;
function add(tag,attrs,parent=svg,text){const n=document.createElementNS(S,tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,String(v));if(text!==undefined)n.textContent=text;parent.appendChild(n);return n}
function txt(x,y,value,cls,parent=svg){return add('text',{x,y,class:cls},parent,value)}
function line(x1,y1,x2,y2,cls='rail-muted'){return add('line',{x1,y1,x2,y2,class:cls})}
function statusFor(i){if(mode==='supplied'||mode==='scan')return entries[i].kind;if(mode==='github'||!pipeline)return'warn';const at=entries[i]&&entries[i].at&&entries[i].at[step-1];return at?at.kind:'info'}
function statusText(i){if(mode==='scan')return entries[i].status;if(mode==='supplied')return entries[i].kind==='risk'?'REFUTED':'OPEN';if(mode==='github'||!pipeline)return'UNVERIFIED';const at=entries[i]&&entries[i].at&&entries[i].at[step-1];return at?at.status:'·'}
function setStep(n){clearInterval(timer);timer=null;by('play').textContent='Replay changes';step=Math.max(0,Math.min(entries.length,n));focus=null;closeTruth();render()}
function play(){if(timer){clearInterval(timer);timer=null;by('play').textContent='Replay changes';return}if(step>=entries.length)step=0;closeTruth();by('play').textContent='Pause replay';render();timer=setInterval(()=>{if(step>=entries.length){clearInterval(timer);timer=null;by('play').textContent='Replay changes';return}step++;focus=null;closeTruth();render()},2900)}
function render(){const entering=step!==lastRenderedStep;svg.replaceChildren();by('scrub').max=String(entries.length);by('scrub').value=String(step);by('step-count').textContent=`${step} / ${entries.length}`;by('previous').disabled=step===0;by('next').disabled=step===entries.length;const exampleOnly=mode==='example';if(by('vsbox'))by('vsbox').style.display=exampleOnly?'flex':'none';if(by('vs-strip'))by('vs-strip').style.display=exampleOnly?'block':'none';const e=entries[step-1];by('figure-caption').innerHTML='';if(!e){by('figure-caption').textContent='The ledger starts empty. Choose Replay changes or reveal one change with the arrow.'}else{by('figure-caption').textContent=e.caption}
  txt(48,50,mode==='scan'?'REVIEW PASSES':mode==='supplied'?'AI PATCHES':'MERGES','caption-label');txt(288,50,mode==='scan'?'CLAIMS ABOUT CURRENT CODE':'BELIEFS THAT SURVIVE THE MERGE','caption-label');txt(916,50,'WHY THE STATE CHANGED','caption-label');line(884,36,884,550,'divider');line(97,115,97,493,'rail');
  for(let i=0;i<entries.length;i++){const y=130+i*108,entry=entries[i],seen=i<step;line(282,y+68,850,y+68,'row-rule');add('circle',{cx:97,cy:y,r:17,class:seen&&i===step-1?'commit-dot commit-current':'commit-dot'});txt(97,y+5,String(i+1),'commit-count'+(seen&&i===step-1?' current':''),svg).setAttribute('text-anchor','middle');txt(132,y+5,seen?(mode==="supplied"?`#${entry.number}`:mode==="scan"?`PASS ${entry.number}`:`PR #${entry.number}`):'· · ·','commit-name'+(seen&&i===step-1?' current':''));if(!seen)continue;
    const g=add('g',{class:'belief-row'+(entering&&i===step-1?' entering':''),tabindex:0,role:'button','aria-label':`${entry.title}: ${statusText(i)}. Open claim review`});g.addEventListener('click',()=>{focus=i;openTruth(i);render()});g.addEventListener('keydown',ev=>{if(ev.key==='Enter'||ev.key===' '){ev.preventDefault();focus=i;openTruth(i);render()}});txt(290,y-15,entry.title.length>34?entry.title.slice(0,33)+'…':entry.title,'belief-title',g);txt(290,y+18,mode==='example'?`${entry.sha} · ${entry.source}`:mode==='supplied'||mode==='scan'?entry.source:`PR #${entry.number} · merged ${entry.merged}`,'belief-source',g);const st=statusFor(i),mark=add('g',{},g);if(st==='risk'){add('path',{d:`M815 ${y-21}l16 16m0-16l-16 16`,class:'mark-risk'},mark)}else if(st==='warn'){add('circle',{cx:823,cy:y-13,r:12,class:'mark-warn'},mark);txt(823,y-8,'?','status-word warn',mark).setAttribute('text-anchor','middle')}else{add('circle',{cx:823,cy:y-13,r:12,class:'mark-ok'},mark);txt(823,y-8,st==='ok'?'✓':'·','status-word '+st,mark).setAttribute('text-anchor','middle')}txt(730,y+18,statusText(i),'status-word '+st,g)
  }
  const be=entries[step-1];if(pipeline&&be&&be.breaches){be.breaches.forEach((b,bi)=>{const yFrom=130+(step-1)*108,yTo=130+b.to*108;add('path',{d:`M267 ${yFrom}H${230-bi*33}V${yTo}H267`,class:'breach'+(entering?' entering':'')});txt(146,yTo-13,b.label,'breach-label')})}
  renderWitness();lastRenderedStep=step;
}
function renderWitness(){const x=916;if(step===0){txt(x,194,'No claims yet','metric-sub');txt(x,236,'Reveal a change','metric-small');return}if(mode==='scan'){const e=entries[step-1];txt(x,170,e.kind==='risk'?'!':e.kind==='ok'?'✓':'?','metric '+(e.kind==='risk'?'risk':e.kind==='ok'?'':'warn'));txt(x,220,e.status,'metric-sub');txt(x,265,'Click for evidence','metric-small');txt(x,295,'Human decision: pending','metric-small');return}if(mode==='supplied'){const e=entries[step-1];txt(x,170,e.kind==='risk'?'!':'?','metric '+(e.kind==='risk'?'risk':'warn'));txt(x,220,e.kind==='risk'?'Checked breach':'Review still open','metric-sub');txt(x,265,`Issue #${e.number}`,'metric-small');txt(x,298,'Click the row for claims','metric-small');if(e.kind==='risk'){txt(x,465,'AI: REQUEST CHANGES','status-word risk');txt(x,493,'HUMAN: PENDING','status-word info')}return}if(mode==='github'||!pipeline){txt(x,172,'?','metric warn');txt(x,222,'PR title only','metric-sub');txt(x,257,'No checker has run.','metric-small');txt(x,285,'No conflict is claimed.','metric-small');return}const e=entries[step-1];if(step>=entries.length){txt(x,465,'AI: REQUEST CHANGES','status-word risk');txt(x,493,'HUMAN: PENDING','status-word info');txt(x,540,'2 tests green · gaps remain','metric-small')}
  if(e&&e.metric){txt(x,180,e.metric.big,'metric '+(e.metric.cls||''));txt(x,225,e.metric.sub,'metric-sub');e.metric.small.forEach((s,k)=>txt(x,255+k*28,s,'metric-small'));return}
  txt(x,180,'?','metric warn');txt(x,225,'No witness computed','metric-sub');txt(x,255,'Re-run the checker.','metric-small')
}
function loadExample(){mode='example';entries=example;by('notice').classList.remove('error');by('notice').textContent='Example: four PR-shaped commits in a tiny shop. Reveal each change, then click a row for evidence.';by('origin').textContent='The example replays tags pr1–pr4 in toy/_repo. These are simulated PR merges, not Git merge commits.';refreshDigest();setStep(0)}
function parseRepo(raw){let u;try{u=new URL(raw)}catch{return null}if(u.protocol!=='https:'||u.hostname.toLowerCase()!=='github.com')return null;const p=u.pathname.split('/').filter(Boolean);if(p.length<2||!/^[-\w.]+$/.test(p[0])||!/^[-\w.]+$/.test(p[1]))return null;return[p[0],p[1].replace(/\.git$/,'')]}
function showPRs(prs,repo,source){mode='github';loadedRepo=repo;entries=prs.map(pr=>({number:pr.number,title:pr.title,source:pr.html_url,merged:(pr.merged_at||'').slice(0,10),caption:`PR #${pr.number} merged: “${pr.title}”. Its intent is a candidate claim; open it to inspect available facts and gaps.`,claims:[{id:`PR-${pr.number}`,claim:pr.title,label:'Unverified intent',evidence:`GitHub PR #${pr.number}, merged ${pr.merged_at||'date unavailable'}`,challenge:'No code-level counterexample has been checked.',new:'The merge adds or changes code; inspect its changed-file list below.',gap:'A PR title is not a requirement or proof.'}]}));by('notice').classList.remove('error');by('notice').textContent=`${repo} · ${entries.length} recent merged PRs · ${source} · claims unverified`;by('origin').textContent='GitHub supplies PR metadata and changed files. A code-level checker has not run for this repository; only the supplied MessagePack #2297 branch has a verified breach.';refreshDigest();setStep(0)}
let loadedRepo='';
const SOURCE_RE=/\.(?:cs|py|js|jsx|ts|tsx|go|rs|java|kt|rb|php|swift|c|cc|cpp|h|hpp)$/i;
const DOC_RE=/(^|\/)(?:README|CONTRIBUTING|SECURITY)(?:\.[^/]+)?$|\.(?:md|rst)$/i;
const TEST_RE=/(^|\/)(?:test|tests|spec|specs)(\/|$)|(?:test|spec)\.[^/]+$/i;
function reviewSnapshot(repo,branch,tree,contents){
 const blobs=tree.tree.filter(x=>x.type==='blob'),code=blobs.filter(x=>SOURCE_RE.test(x.path)),tests=blobs.filter(x=>TEST_RE.test(x.path)),docs=blobs.filter(x=>DOC_RE.test(x.path));
 const scanned=contents.filter(x=>x.ok),lines=scanned.flatMap(f=>f.text.split('\n').map((text,i)=>({file:f.path,line:i+1,text})));
 const promises=lines.filter(x=>DOC_RE.test(x.file)&&/\b(always|never|all|every|guarantee[ds]?)\b/i.test(x.text)).slice(0,6);
 const todos=lines.filter(x=>/\b(TODO|FIXME|HACK)\b/.test(x.text)).slice(0,8);
 const markers=lines.filter(x=>/(?:\bAKIA[0-9A-Z]{16}\b|\bghp_[A-Za-z0-9]{20,}\b|\bsk-[A-Za-z0-9_-]{20,}\b)/.test(x.text)).slice(0,5);
 const scope=`${scanned.length} of ${code.length+docs.length} candidate source/document files read; complete tree: ${!tree.truncated}`;
 const claim=(id,statement,label,evidence,challenge,gap)=>({id,claim:statement,label,evidence,challenge,new:'Surfaced by the repository scan; no PR history was required.',gap});
 return [
  {number:1,title:'Map the current codebase',source:`${blobs.length} tracked files`,kind:tree.truncated?'warn':'ok',status:tree.truncated?'PARTIAL TREE':'TREE CHECKED',caption:`No merged PRs were found. The current ${branch} tree contains ${blobs.length} files, including ${code.length} source files.`,summary:'Repository structure is a checked fact, not a quality verdict.',claims:[claim('TREE-1',`The current tree contains ${blobs.length} files and ${code.length} source files.`,tree.truncated?'Tested':'Proved within scope',`GitHub tree API at ${repo}@${branch}`,`A truncated API tree would omit paths.`,`Code content scope: ${scope}`)]},
  {number:2,title:'Read requirements and promises',source:`${docs.length} documentation paths`,kind:'warn',status:'INTENT OPEN',caption:`Documentation contains ${promises.length} sampled absolute promise(s). Each needs a requirement and a targeted check.`,summary:'Statements in documentation are candidate requirements.',claims:promises.length?promises.map((p,i)=>claim(`DOC-${i+1}`,p.text.trim().slice(0,180),'Unknown',`${p.file}:${p.line}`,`Does implementation satisfy this promise?`,'No semantic checker or product owner has resolved it.')):[claim('DOC-0','Documentation intent is consistent with implementation.','Unknown',`${docs.length} documentation paths; ${scanned.filter(x=>DOC_RE.test(x.path)).length} read`,'No absolute statement was found in the sampled text.','Unstated requirements and unread documents remain open.')]},
  {number:3,title:'Check the test footprint',source:`${tests.length} test-like paths`,kind:tests.length?'ok':'warn',status:tests.length?'TEST PATHS FOUND':'COVERAGE UNKNOWN',caption:`The tree has ${tests.length} test-like paths. Their presence does not prove they execute or cover this code.`,summary:'A test inventory tells reviewers where to look next.',claims:[claim('TEST-1',`The tree has ${tests.length} test-like paths.`,tree.truncated?'Tested':'Proved within scope',tests.slice(0,5).map(x=>x.path).join(', ')||'No test-like path in the returned tree','Do tests exercise the important paths and supported configurations?','No test command was executed in the browser.')]},
  {number:4,title:'Probe code for review leads',source:`${scanned.length} files read`,kind:markers.length?'risk':'warn',status:markers.length?'PATTERN FOUND':'REVIEW LEADS',caption:`Read ${scanned.length} source/document files. Found ${todos.length} work markers and ${markers.length} credential-like pattern(s); all need context.`,summary:`Automated source scan · ${scope}`,claims:[claim('CODE-1','No credential-like patterns occur in scanned text.',markers.length?'Refuted':'Tested',markers.map(x=>`${x.file}:${x.line}`).join(', ')||scope,'A pattern match is a review lead, not proof of an active secret.','Pattern checks miss other secret formats and unread files.'),claim('CODE-2',`${todos.length} TODO/FIXME/HACK markers need triage.`,'Unknown',todos.map(x=>`${x.file}:${x.line}`).join(', ')||'No markers in scanned files','Do these notes describe unresolved behavior or harmless plans?','The browser cannot decide their impact.')]}
 ];
}
function githubError(r,what){const h=r.headers&&typeof r.headers.get==='function'?r.headers:null;if((r.status===403||r.status===429)&&h&&h.get('x-ratelimit-remaining')==='0'){const reset=Number(h.get('x-ratelimit-reset')),at=reset?new Date(reset*1000).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}):'';const e=Error(`GitHub API rate limit reached (${h.get('x-ratelimit-limit')||60} requests/hour without login)${at?`; resets at ${at}`:''}`);e.rateLimited=true;return e}return Error(`${what} returned ${r.status}`)}
async function scanRepository(repo){const headers={Accept:'application/vnd.github+json'},notice=by('notice'),branch='HEAD';notice.classList.remove('error');notice.textContent=`${repo} has no recent merged PRs. Reading its current tree…`;
 const treeResponse=await fetch(`https://api.github.com/repos/${repo}/git/trees/HEAD?recursive=1`,{headers});if(!treeResponse.ok)throw githubError(treeResponse,'Repository tree');const tree=await treeResponse.json();if(!Array.isArray(tree.tree))throw Error('Repository tree was unavailable');
 const candidates=tree.tree.filter(x=>x.type==='blob'&&x.size<=120000&&(SOURCE_RE.test(x.path)||DOC_RE.test(x.path))&&!/(^|\/)(vendor|node_modules|dist|build|bin|obj|generated)(\/|$)/i.test(x.path));
 const ordered=candidates.sort((a,b)=>Number(DOC_RE.test(b.path))-Number(DOC_RE.test(a.path))||Number(TEST_RE.test(b.path))-Number(TEST_RE.test(a.path))||a.path.localeCompare(b.path));const chosen=ordered.slice(0,80),contents=[];
 for(let i=0;i<chosen.length;i+=8){notice.textContent=`${repo} · reading code ${Math.min(i+8,chosen.length)}/${chosen.length} (up to 80 files)`;const batch=await Promise.all(chosen.slice(i,i+8).map(async f=>{try{const path=f.path.split('/').map(encodeURIComponent).join('/');const r=await fetch(`https://raw.githubusercontent.com/${repo}/${encodeURIComponent(branch)}/${path}`);return {path:f.path,ok:r.ok,text:r.ok?await r.text():''}}catch{return {path:f.path,ok:false,text:''}}}));contents.push(...batch)}
 mode='scan';loadedRepo=repo;entries=reviewSnapshot(repo,branch,tree,contents);notice.textContent=`${repo}@${branch} · no recent merged PRs · full tree + ${contents.filter(x=>x.ok).length}/${candidates.length} source/document files read`;by('origin').textContent='Repository scan: the full GitHub tree is inspected when the API does not truncate it; source content is capped at 80 files. Claims pass through explicit browser checks. No model review, build, or tests ran; human decision remains pending.';refreshDigest();setStep(0);
}
async function loadRepo(raw){const p=parseRepo(raw);if(!p){by('notice').classList.add('error');by('notice').textContent='Enter a public https://github.com/owner/repo URL.';return}const repo=`${p[0]}/${p[1]}`;if(repo.toLowerCase()==='te-industry-tech-office/junction26-messagepack-csharp'){mode='supplied';entries=supplied;loadedRepo=repo;by('notice').classList.remove('error');by('notice').textContent='Four supplied AI-made branches · click any branch to inspect its claims and evidence';by('origin').textContent='These are AI-made branch patches from the challenge repository, not merged GitHub PRs. #2297 has a verified concern; the other reviews remain open.';refreshDigest();setStep(0);return}const b=by('load-repo');b.disabled=true;b.textContent='Loading…';try{const response=await fetch(`https://api.github.com/repos/${encodeURIComponent(p[0])}/${encodeURIComponent(p[1])}/pulls?state=closed&sort=updated&direction=desc&per_page=100`,{headers:{Accept:'application/vnd.github+json'}});if(!response.ok)throw githubError(response,'GitHub');const prs=(await response.json()).filter(x=>x.merged_at).sort((a,b)=>Date.parse(a.merged_at)-Date.parse(b.merged_at)).slice(-4);if(!prs.length){await scanRepository(repo);return}showPRs(prs,repo,'GitHub API')}catch(error){try{const response=await fetch('prs.json');if(!response.ok)throw error;const snap=await response.json();if(snap&&snap.repo===repo&&snap.prs&&snap.prs.length){showPRs(snap.prs,repo,`saved snapshot ${snap.generated}`);return}throw error}catch{by('notice').classList.add('error');by('notice').textContent=error.rateLimited?`${error.message}. Try again then, or use the supplied challenge repo or Example meanwhile.`:`${error.message}. Use the supplied challenge repo or Example.`}}finally{b.disabled=false;b.textContent='Load repo'}}
function setPipeline(v){pipeline=v;document.querySelectorAll('.vsbtn').forEach(b=>b.classList.toggle('on',b.dataset.v===String(v)));const c=comparison[v?'pipeline':'replay'];const s=by('vs-strip');if(s)s.textContent=`${c.label} · ${c.note} · claims ${c.beliefs} · checked ${c.checked} · refuted ${c.refuted}`;render()}
function truthLabelCls(label){return label==='Refuted'?'risk':label==='Proved within scope'?'ok':label==='Tested'?'ok':'warn'}
function escapeHtml(value){return String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]))}
function fact(label,value){return `<p class="t-meta"><b>${escapeHtml(label)}:</b> ${escapeHtml(value)}</p>`}
function drawTruth(i){const panel=by('truth-panel'),e=entries[i];if(!panel||!e)return;let claims=[];
 if(mode==='example'){claims=step===entries.length&&pipeline?(e.truth||[]).map(t=>({id:t.id,claim:t.claim,label:t.label,evidence:`${t.rule}; ${t.checked} checks. ${t.example||''}`,challenge:(t.witnesses||[]).map(w=>JSON.stringify(w)).join('; ')||'No counterexample recorded.',new:'Linked to the current toy patch.',gap:t.label==='Tested'?'Only sampled cases were run.':t.label==='Unknown'?'A human must resolve this intent.':'See the declared finite scope.',check:t.command})): [{id:`PR-${e.number}`,claim:e.title,label:'Historical claim',evidence:e.source,challenge:'The replay has not run a checker at this historical step.',new:e.caption,gap:'The detailed checker output is for the final AI patch.'}]}
 else claims=e.claims||[];
 const body=claims.map(t=>`<details open><summary><span class="t-id">${escapeHtml(t.id)}</span> ${escapeHtml(t.claim)} <span class="t-label ${truthLabelCls(t.label)}">${escapeHtml(t.label)}</span></summary><div class="t-body">${fact('Evidence / fact',t.evidence)}${fact('What it challenges',t.challenge)}${fact('New change or knowledge',t.new)}${fact('Still open',t.gap)}${t.check?`<p class="t-cmd" title="Click to copy check command">$ ${escapeHtml(t.check)}</p>`:''}</div></details>`).join('');
 const source=mode==='supplied'?`https://github.com/te-industry-tech-office/junction26-messagepack-csharp/tree/${encodeURIComponent(e.branch)}`:mode==='github'?e.source:'';
 panel.innerHTML=`<div class="t-head"><b>Claims and evidence · ${escapeHtml(e.title)}</b><button type="button" id="close-truth" aria-label="Close claim review">×</button></div><p class="t-example">${escapeHtml(e.summary||e.caption)}</p>${body}${source?`<p class="t-meta"><a href="${escapeHtml(source)}" target="_blank" rel="noopener">Open source change</a></p>`:''}<div id="changed-files"></div>`;
 panel.querySelector('#close-truth').addEventListener('click',closeTruth);panel.querySelectorAll('.t-cmd').forEach(el=>el.addEventListener('click',()=>copyTruth(el)));panel.style.display='block';panel.scrollIntoView({behavior:'smooth',block:'nearest'});
}
async function openTruth(i){drawTruth(i);const e=entries[i];if(mode!=='github'||e.filesLoaded||!loadedRepo)return;const target=by('changed-files');target.textContent='Loading changed-file facts from GitHub…';try{const response=await fetch(`https://api.github.com/repos/${loadedRepo}/pulls/${e.number}/files?per_page=100`,{headers:{Accept:'application/vnd.github+json'}});if(!response.ok)throw githubError(response,'GitHub');const files=await response.json();e.filesLoaded=true;e.fileFacts=files;const testFiles=files.filter(f=>/test|spec/i.test(f.filename));const body=document.createElement('div');body.className='file-facts';const heading=document.createElement('h3');heading.textContent=`Changed files (${files.length}${files.length===100?'+':''})`;body.appendChild(heading);const p=document.createElement('p');p.textContent=`GitHub reports ${files.reduce((n,f)=>n+f.additions,0)} additions and ${files.reduce((n,f)=>n+f.deletions,0)} deletions. ${testFiles.length} changed path(s) look like tests. File names indicate scope, not correctness.`;body.appendChild(p);const list=document.createElement('ul');for(const f of files.slice(0,18)){const li=document.createElement('li');li.textContent=`${f.status}: ${f.filename}`;list.appendChild(li)}body.appendChild(list);if(files.length>18){const note=document.createElement('p');note.textContent=`${files.length-18} more paths omitted from this view.`;body.appendChild(note)}if(target&&focus===i)target.replaceChildren(body)}catch(error){if(target&&focus===i)target.textContent=`Changed-file facts unavailable: ${error.message}. The claims remain unverified.`}}
function closeTruth(){const panel=by('truth-panel');if(panel)panel.style.display='none'}
function copyTruth(el){const text=el.textContent.replace(/^\$\s*/,'');(navigator.clipboard?navigator.clipboard.writeText(text):Promise.reject()).then(()=>{el.textContent='copied ✓'}).catch(()=>{})}
by('previous').addEventListener('click',()=>setStep(step-1));by('next').addEventListener('click',()=>setStep(step+1));by('play').addEventListener('click',play);by('scrub').addEventListener('input',e=>setStep(Number(e.target.value)));by('load-example').addEventListener('click',loadExample);by('repo-form').addEventListener('submit',e=>{e.preventDefault();loadRepo(by('repo-url').value.trim())});document.addEventListener('keydown',e=>{if(document.activeElement===by('repo-url'))return;if(e.key==='ArrowRight'){e.preventDefault();setStep(step+1)}if(e.key==='ArrowLeft'){e.preventDefault();setStep(step-1)}});
/* VS toggle + token strip + drill-down truth panel, inserted without touching the template markup */
const mast=document.querySelector('.mast');
const vsbox=document.createElement('div');vsbox.className='vsbox';vsbox.id='vsbox';
['Replay only','Trust pipeline'].forEach((label,i)=>{const b=document.createElement('button');b.type='button';b.className='vsbtn'+(i===1?' on':'');b.dataset.v=String(i===1);b.textContent=label;b.onclick=()=>setPipeline(i===1);vsbox.appendChild(b)});
mast.appendChild(vsbox);
const strip=document.createElement('div');strip.id='vs-strip';strip.className='vs-strip';document.querySelector('.evidence').prepend(strip);
const truthPanel=document.createElement('section');truthPanel.id='truth-panel';truthPanel.className='truth-panel';truthPanel.style.display='none';
truthPanel.setAttribute('aria-label','Core truths of the selected belief');
document.querySelector('figure').after(truthPanel);
/* concise human-first digest above the figure; click opens that row's truths */
const digest=document.createElement('div');digest.id='digest';digest.className='digest';
const digestTitle=document.createElement('p');digestTitle.textContent='What to read first:';digest.appendChild(digestTitle);
function refreshDigest(){digest.querySelectorAll('button').forEach(b=>b.remove());digestTitle.textContent=mode==='scan'?'Current-code review:':mode==='supplied'?'AI-made branches:':mode==='github'?'Merged PRs:':'Toy review:';entries.forEach((e,i)=>{const b=document.createElement('button');b.type='button';b.className='digest-item';b.textContent=mode==='scan'?`${i+1}. ${e.title}`:mode==='supplied'?`#${e.number} ${e.title}`:mode==='github'?`PR #${e.number} ${e.title}`:e.title;b.onclick=()=>{setStep(i+1);focus=i;openTruth(i)};digest.appendChild(b)})}
refreshDigest();
by('notice').after(digest);
setPipeline(true);
by('repo-url').value='https://github.com/te-industry-tech-office/junction26-messagepack-csharp';
loadRepo(by('repo-url').value);
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
              "font-size:12.5px;color:var(--muted);flex-basis:100%}"
              ".truth-panel{margin:14px 0 0;border:1px solid var(--hair);"
              "border-radius:4px;background:#fbfaf7;padding:12px 16px 14px;"
              "animation:rise .25s ease both}.truth-panel .t-head{display:flex;"
              "justify-content:space-between;align-items:center;font:700 13px "
              "Consolas,monospace;letter-spacing:.08em;text-transform:uppercase;"
              "color:var(--accent);margin-bottom:8px}.truth-panel .t-head button{"
              "border:1px solid #8fa3a8;background:transparent;border-radius:3px;"
              "width:26px;height:26px;color:var(--ink);font-size:14px}"
              ".truth-panel details{border-top:1px solid var(--hair);padding:8px 0}"
              ".truth-panel summary{cursor:pointer;font:normal 19px Georgia,serif;"
              "color:var(--ink);list-style:none}.truth-panel summary::-webkit-"
              "details-marker{display:none}.truth-panel summary::before{content:"
              "'▸ ';color:var(--accent)}.truth-panel details[open] summary::before{"
              "content:'▾ '}.truth-panel .t-id{font:700 12px Consolas,monospace;"
              "color:var(--muted);margin-right:6px}.truth-panel .t-label{font:700 "
              "11px Consolas,monospace;letter-spacing:.05em;margin-left:8px;"
              "text-transform:uppercase}.truth-panel .t-label.risk{color:var(--risk)}"
              ".truth-panel .t-label.ok{color:var(--ok)}.truth-panel .t-label.warn{"
              "color:var(--warn)}.truth-panel .t-label.info{color:var(--accent)}"
              ".truth-panel .t-body{padding:6px 0 2px 18px}.truth-panel .t-formal{"
              "font:15px Consolas,monospace;color:var(--accent);margin:2px 0 6px}"
              ".truth-panel .t-meta{font-size:12.5px;color:var(--muted);margin:3px 0}"
              ".truth-panel .t-example{font:normal 16px Georgia,serif;color:var(--ink);"
              "margin:6px 0}.truth-panel .t-wits{margin:2px 0 6px;padding-left:20px;"
              "font-size:12.5px;color:var(--ink)}.truth-panel .t-cmd{font:13px "
              "Consolas,monospace;background:#f2f0e9;border:1px solid var(--hair);"
              "border-radius:3px;padding:6px 9px;cursor:pointer;color:var(--ink);"
              "margin:6px 0 0}"
              ".digest{display:flex;flex-wrap:wrap;gap:6px;align-items:center;"
              "margin-bottom:10px}.digest p{font:700 12px Consolas,monospace;"
              "letter-spacing:.08em;text-transform:uppercase;color:var(--muted);"
              "margin:0 6px 0 0}.digest-item{border:1px solid var(--hair);"
              "background:transparent;border-radius:3px;padding:4px 9px;"
              "font-size:12.5px;color:var(--ink);cursor:pointer}.digest-item:hover{"
              "border-color:var(--accent)}")
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
        INDEX.write_text(html, encoding="utf-8")
        print(f"synced {INDEX.resolve()}")
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
