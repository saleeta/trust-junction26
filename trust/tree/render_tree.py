"""Render the context tree as a standalone HTML viewer.

Left: the tree. Nodes are chips showing label + token cost; nodes visited in
the lookup pass light up blue, nodes revisited by falsification propagation
light up red, nodes touched by both light purple. Buttons dim everything else
so the traversal path is readable at a glance.

Right: the token ledger. Every pass with its cost, then the A/B columns -
the graph walker vs a traditional agent reading the full diff vs a triaged
agent - as measured token bars, with the honest note about dry-run limits.

No CDN, no build step: the data is inlined and the file opens with file://.
"""

from __future__ import annotations

import html
import json
from pathlib import Path


def _esc(s: object) -> str:
    return html.escape(str(s or ""))


def render(data: dict) -> str:
    # ---- index nodes: id -> depth, pass marks --------------------------------
    marks: dict[str, set[str]] = {}
    for p in data.get("passes", []):
        cls = "p0" if p.get("kind") == "lookup" else "p1"
        for v in p.get("visits", []):
            marks.setdefault(v["node_id"], set()).add(cls)

    def walk_nodes(node: dict, depth: int, out: dict) -> None:
        out[node["id"]] = {"depth": depth, "kind": node.get("kind", ""),
                           "label": node.get("label", ""),
                           "tokens": node.get("tokens", 0),
                           "falsified": node.get("falsified", False)}
        for c in node.get("children", []):
            walk_nodes(c, depth + 1, out)

    index: dict[str, dict] = {}
    walk_nodes(data["tree"], 0, index)

    def render_node(node: dict, depth: int) -> str:
        info = index.get(node["id"], {})
        m = marks.get(node["id"], set())
        cls = "node "
        cls += "p0" if "p0" in m else ""
        cls += " p1" if "p1" in m else ""
        cls = cls.strip()
        fal = " falsified" if node.get("falsified") else ""
        title = _esc(node.get("detail", "")[:300]).replace('"', "&quot;")
        kids = "".join(render_node(c, depth + 1) for c in node.get("children", []))
        collapse = "<span class='tgl' onclick='tgl(this)'>&#9662;</span>" if kids else "<span class='tgl leaf'>&#183;</span>"
        kind = _esc(node.get("kind"))
        label = _esc(node.get("label"))[:90]
        tok = node.get("tokens", 0)
        return (
            f"<li class='{cls}{fal}' title=\"{title}\">"
            f"<div class='row'>{collapse}"
            f"<span class='kind'>{kind}</span>"
            f"<span class='label'>{label}</span>"
            f"<span class='tok'>{tok}</span></div>"
            f"{'<ul>' + kids + '</ul>' if kids else ''}</li>")

    tree_html = render_node(data["tree"], 0)

    # ---- ledger --------------------------------------------------------------
    passes = data.get("passes", [])
    rows = []
    for i, p in enumerate(passes):
        rev = sum(1 for v in p.get("visits", []) if v.get("revisit"))
        rev_html = (f"<span class='rev' title='nodes re-visited by this pass'>"
                    f"&#8635;{rev}</span>") if rev else ""
        rows.append(
            f"<div class='passrow {'prop' if p.get('kind') == 'propagation' else 'look'}"
            f"' data-pass='{i}' onclick='focusPass({i})'>"
            f"<span class='pkind'>{_esc(p.get('kind'))}</span>"
            f"<span class='pname'>{_esc(p.get('name'))[:64]}</span>"
            f"<span class='ptok'>{p.get('tokens', 0)}</span>{rev_html}</div>")

    t = data.get("totals", {})
    b = data.get("baselines", {})
    walker = t.get("total_tokens", 0)
    full = b.get("traditional_full_prompt_tokens", 0)
    triaged = b.get("traditional_triaged_prompt_tokens", 0)
    max_tok = max(walker, full, triaged, 1)

    def bar(label: str, tok: int, extra: str) -> str:
        pct = max(2, int(100 * tok / max_tok))
        return (f"<div class='abar'><div class='aname'>{label}<br>"
                f"<b>{tok:,}</b> {extra}</div>"
                f"<div class='atrack'><div class='afill' style='width:{pct}%'></div>"
                f"</div></div>")

    ab_html = (
        bar("graph walker (this tree)",
            walker, f"{t.get('nodes_visited', 0)} nodes, {t.get('revisits', 0)} revisits")
        + bar("traditional agent - full diff",
              full, f"{b.get('traditional_full_files', 0)} files, no citations")
        + bar("traditional agent - triaged",
              triaged, f"{b.get('traditional_triaged_files', 0)} files, no citations"))

    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>context tree - {_esc(data.get('branch', ''))}</title>
<style>
 body {{ font: 14px/1.45 system-ui, Segoe UI, sans-serif; margin:0; color:#1a2233;
        background:#f4f6fa; }}
 header {{ background:#101828; color:#e6eaf2; padding:10px 16px; }}
 header h1 {{ font-size:16px; margin:0; }} header .sub {{ color:#93a0b4; font-size:12px; }}
 #wrap {{ display:flex; height:calc(100vh - 64px); }}
 #tree {{ flex:1; overflow:auto; padding:14px 10px 40px 14px; background:#fff; }}
 #panel {{ width:420px; border-left:1px solid #d8dee9; overflow:auto;
           background:#fbfcfe; padding:14px; }}
 ul {{ list-style:none; margin:0; padding-left:20px; }}
 li > ul {{ display:none; }} li.open > ul {{ display:block; }}
 .row {{ padding:2px 6px; border-radius:5px; white-space:nowrap; }}
 .tgl {{ cursor:pointer; color:#8a94a6; display:inline-block; width:14px; }}
 .tgl.leaf {{ cursor:default; }}
 .kind {{ display:inline-block; min-width:74px; color:#8a94a6; font-size:11px; }}
 .label {{ margin-left:4px; }}
 .tok {{ float:right; color:#5b6675; font-size:11px; background:#eef1f6;
         border-radius:8px; padding:0 7px; }}
 .node.p0 .row {{ background:#dceafe; outline:1px solid #7fb0f0; }}
 .node.p1 .row {{ background:#fde3d9; outline:1px solid #f09a7f; }}
 .node.p0.p1 .row {{ background:#e9defa; outline:1px solid #b08ae0; }}
 .node.falsified .label {{ color:#c0392b; font-weight:600; }}
 .node.dim > .row {{ opacity:.18; }}
 .passrow {{ display:grid; grid-template-columns:86px 1fr auto auto; gap:6px;
   padding:5px 6px; border-radius:6px; margin-bottom:4px; cursor:pointer;
   background:#eef1f6; }}
 .passrow.look {{ border-left:3px solid #4d8ff0; }}
 .passrow.prop {{ border-left:3px solid #e2603a; }}
 .passrow.active {{ box-shadow:0 0 0 2px #b08ae0; }}
 .pkind {{ font-size:11px; color:#7b8698; text-transform:uppercase; }}
 .ptok {{ font-weight:700; }}
 .rev {{ color:#e2603a; font-size:11px; }}
 h2 {{ font-size:13px; text-transform:uppercase; letter-spacing:.06em;
      color:#7b8698; margin:14px 0 6px; }}
 .stat {{ display:flex; justify-content:space-between; padding:2px 0;
          border-bottom:1px dotted #d8dee9; font-size:13px; }}
 .abar {{ margin:8px 0 12px; }}
 .aname {{ font-size:12px; color:#3d4757; margin-bottom:2px; }}
 .atrack {{ background:#eef1f6; border-radius:4px; height:14px; }}
 .afill {{ background:linear-gradient(90deg,#4d8ff0,#b08ae0); height:14px;
           border-radius:4px; }}
 .note {{ color:#8a94a6; font-size:11px; margin-top:10px; }}
 button {{ background:#101828; color:#e6eaf2; border:0; border-radius:5px;
           padding:5px 10px; margin:2px 4px 8px 0; cursor:pointer; font-size:12px; }}
 button.off {{ background:#d8dee9; color:#3d4757; }}
</style></head><body>
<header><h1>context tree &mdash; {_esc(data.get('branch', ''))}
 <span class="sub">base {_esc(data.get('base', ''))[:9]}</span></h1>
 <div class="sub">blue = lookup pass &nbsp; red = falsification propagation &nbsp;
 purple = revisited &nbsp; &#8635; = recurring traversal</div></header>
<div id="wrap">
 <div id="tree">
  <button onclick="all(1)">expand</button>
  <button onclick="all(0)">collapse</button>
  <button id="dimbtn" onclick="dim()">show only visited</button>
  <ul>{tree_html}</ul>
 </div>
 <div id="panel">
  <h2>traversal passes</h2>
  <div class="passrow" style="grid-template-columns:86px 1fr auto">
    <span class="pkind">total</span><span class="pname">all passes</span>
    <span class="ptok">{t.get('total_tokens', 0):,}</span></div>
  {''.join(rows)}
  <div class="stat"><span>lookup tokens</span><b>{t.get('lookup_tokens', 0):,}</b></div>
  <div class="stat"><span>propagation tokens</span><b>{t.get('propagation_tokens', 0):,}</b></div>
  <div class="stat"><span>nodes visited</span><b>{t.get('nodes_visited', 0)}</b></div>
  <div class="stat"><span>revisits (recurring traversal)</span><b>{t.get('revisits', 0)}</b></div>
  <div class="stat"><span>falsified assumptions</span><b>{t.get('falsified_assumptions', 0)}</b></div>
  <h2>token usage - vs a traditional agent</h2>
  {ab_html}
  <div class="stat"><span>full tree dump (everything known)</span>
    <b>{b.get('full_tree_dump_tokens', 0):,}</b></div>
  <div class="note">{_esc(b.get('note', ''))}<br>
  data is inlined; open with file:// - no network needed.</div>
 </div>
</div>
<script>
const DATA = {payload};
const marks = {{}};
DATA.passes.forEach((p, pi) => {{
  (p.visits || []).forEach(v => {{
    (marks[v.node_id] = marks[v.node_id] || []).push(pi);
  }});
}});
function tgl(el) {{ el.parentElement.parentElement.classList.toggle('open'); }}
function all(open) {{
  document.querySelectorAll('#tree li').forEach(li => li.classList.toggle('open', !!open));
}}
function dim() {{
  const btn = document.getElementById('dimbtn');
  btn.classList.toggle('off');
  document.querySelectorAll('#tree .node').forEach(n => {{
    if (btn.classList.contains('off')) n.classList.add('dim');
    else n.classList.remove('dim');
  }});
}}
function focusPass(pi) {{
  document.querySelectorAll('.passrow').forEach(r => r.classList.remove('active'));
  document.querySelectorAll(`.passrow[data-pass="${{pi}}"]`).forEach(r => r.classList.add('active'));
  document.querySelectorAll('#tree .node').forEach(n => n.classList.remove('dim'));
  document.querySelectorAll('#tree .node').forEach(n => {{
    if (!(marks[n.querySelector('.label').textContent] || [])
        .some(p => p === pi)) {{
      // dim nodes not in this pass by matching via the visit list
    }}
  }});
  const pass = DATA.passes[pi];
  const ids = new Set((pass.visits || []).map(v => v.node_id));
  document.querySelectorAll('#tree .node').forEach(n => {{
    const id = n.querySelector('.kind').textContent;
    // rows do not carry ids; use label+kind lookup through marks instead
  }});
  // simplest correct approach: rebuild dim from visit list via title match
  document.querySelectorAll('#tree .node').forEach(n => {{
    const lbl = n.querySelector('.label').textContent;
    const knd = n.querySelector('.kind').textContent;
    const hit = (pass.visits || []).some(v => v.label === lbl && v.kind === knd);
    n.classList.toggle('dim', !hit);
  }});
}}
</script>
</body></html>"""


def main(argv=None) -> int:
    import argparse
    import sys
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            pass
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("data", help="context_tree.py JSON output")
    ap.add_argument("--out", help="html path (default: <data>.html)")
    args = ap.parse_args(argv)
    data = json.loads(Path(args.data).read_text(encoding="utf-8"))
    out = Path(args.out) if args.out else Path(args.data).with_suffix(".html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(data), encoding="utf-8")
    print(f"wrote {out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
