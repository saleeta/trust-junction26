"""
review.py - proof-carrying review of toy PR #4 (a tiny shop).

    python toy/review.py              # build repo, run every checker, write toy/out/
    python toy/review.py --check A1   # re-run ONE claim and print its witness

How the review gets deeper than the diff (each step is a named rule, see RULES):

    1. DIFF      claims made by the changed lines.                    (R-RUN)
    2. HISTORY   promises made by EARLIER PRs are re-checked.         (R-HIST)
    3. CALLERS   functions that call the changed one are found by
                 parsing the code (ast); each is re-checked on the
                 SAME counterexample that broke the changed function. (R-CALL)

Every verdict comes from EXECUTING the code at a commit. Nothing is guessed.
"""
from __future__ import annotations
import argparse, ast, importlib, io, itertools, json, re, subprocess, sys, tarfile, tempfile
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from logic import *            # noqa
import build_repo

REPO = build_repo.REPO
BASE = 100
CODES = ["", "WELCOME", "HALF", "VIP"]
QTYS = [1, 10]
MEMBERS = [False, True]

RULES = {
    "R-RUN": "A claim is only true or false because code was executed.",
    "R-HIST": "A promise made by an earlier PR is a test for every later PR.",
    "R-CALL": "If a function's promise is refuted, every function that calls it is re-checked on the same counterexample.",
    "R-DOC": "A sentence in the docs inherits the verdict of the code claim it restates.",
    "R-TEST": "A passing test only speaks for the inputs it actually runs.",
    "R-HUMAN": "Questions of intent are not decidable by code. They go to a person.",
}


def git(*a):
    return subprocess.run(["git", *a], cwd=REPO, capture_output=True, text=True, encoding="utf-8").stdout


class Tree:
    """The shop at one commit, exported to disk and really imported."""

    def __init__(self, rev):
        raw = subprocess.run(["git", "archive", rev], cwd=REPO, capture_output=True).stdout
        self.root = Path(tempfile.mkdtemp(prefix=f"toy_{rev}_"))
        tarfile.open(fileobj=io.BytesIO(raw)).extractall(self.root)
        for m in [m for m in sys.modules if m == "shop" or m.startswith("shop.")]:
            del sys.modules[m]
        sys.path.insert(0, str(self.root))
        try:
            self.prices = importlib.import_module("shop.prices")
            self.coupons = importlib.import_module("shop.coupons")
            self.checkout_m = importlib.import_module("shop.checkout")
            self.ledger = importlib.import_module("shop.ledger")
        finally:
            sys.path.remove(str(self.root))
        self.tests_src = (self.root / "tests/test_shop.py").read_text(encoding="utf-8")

    def total(self, b):          return self.checkout_m.checkout(BASE, b[1], b[0], b[2])["total"]
    def points(self, b):         return self.checkout_m.checkout(BASE, b[1], b[0], b[2])["points"]
    def revenue_after(self, b):  return self.ledger.post_sale(1000, BASE, b[1], b[0], b[2])

    def call_graph(self):
        defs = {}
        for p in (self.root / "shop").glob("*.py"):
            for fn in [n for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))) if isinstance(n, ast.FunctionDef)]:
                calls = {c.func.id for c in ast.walk(fn) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
                defs[fn.name] = (p.name, calls)
        return defs

    def tested_baskets(self):
        """(code, qty, member) combinations the tests actually run - read from the test source."""
        out = set()
        for c in ast.walk(ast.parse(self.tests_src)):
            if isinstance(c, ast.Call) and getattr(c.func, "id", "") == "checkout":
                a = [x.value for x in c.args if isinstance(x, ast.Constant)]
                out.add((a[2], a[1], a[3]))
        return out


def callers_of(defs, target):
    """Breadth-first: who calls `target`, directly or through others? -> [(name, hops)]."""
    seen, frontier, hops, out = {target}, [target], 0, []
    while frontier:
        hops += 1
        nxt = []
        for name, (_, calls) in defs.items():
            if name not in seen and calls & set(frontier):
                seen.add(name); nxt.append(name); out.append((name, hops))
        frontier = nxt
    return out


def fmt_basket(b):
    code, qty, member = b
    return f"{'a ' + code + ' coupon' if code else 'no coupon'}, {qty} item{'s' if qty > 1 else ''}, {'a member' if member else 'not a member'}"


def run_all() -> dict:
    build_repo.build()
    t3, t4 = Tree("pr3"), Tree("pr4")
    pr3, pr4 = git("rev-parse", "pr3").strip(), git("rev-parse", "pr4").strip()
    baskets = Domain("BASKETS", list(itertools.product(CODES, QTYS, MEMBERS)), True,
                     f"base price is {BASE}; codes {CODES}; qty {QTYS}; member {MEMBERS}")
    plain = Domain("BASKETS without a coupon", [b for b in baskets.items if b[0] == ""], True, baskets.assumption)
    coupons = Domain("COUPONS", sorted(t4.coupons.COUPONS), True, "coupons are read from shop/coupons.py")
    R = {}   # id -> dict(claim data + Verdict)

    def add(id, short, rule, claim, formula, origin, plain_words, **kw):
        v = check(formula) if formula is not None else None
        R[id] = dict(id=id, short=short, rule=rule, claim=claim, origin=origin, plain=plain_words, v=v, **kw)
        return v

    # ---- 1. DIFF -----------------------------------------------------------------
    a1 = add("A1", "price never negative", "R-RUN",
        "For every basket, the customer's total is never negative.",
        Forall("b", baskets, Pred("total(b) >= 0", lambda e: t4.total(e["b"]) >= 0)),
        "requirement R-1 and the purpose of PR #4", "The patch says it stops negative prices. Does it?", stage=1)
    add("A2", "README: 'never negative'", "R-DOC",
        'README: "Prices can never go negative."', None,
        "sentence added to README.md by PR #4", "The README repeats the same promise.", derive_from="A1", stage=1)
    add("P1", "no-coupon baskets unchanged", "R-RUN",
        "For baskets with no coupon, PR #4 charges exactly what PR #3 charged.",
        Forall("b", plain, Pred("total_pr4(b) == total_pr3(b)", lambda e: t4.total(e["b"]) == t3.total(e["b"]))),
        "a regression check between the two commits", "Did the patch leave ordinary shoppers alone?", stage=1)

    # ---- 2. HISTORY --------------------------------------------------------------
    add("B1", "cap changes no coupon", "R-HIST",
        "Capping discounts does not change what any existing coupon is worth.",
        Forall("c", coupons, Pred("price_pr4(c) == price_pr3(c)",
               lambda e: t4.prices.final_price(BASE, [t4.coupons.COUPONS[e["c"]]]) == t3.prices.final_price(BASE, [t3.coupons.COUPONS[e["c"]]]))),
        "coupons were added in PR #2", "Old coupons should still be worth what they were.", stage=2)
    add("B2", "README (PR #2): VIP = 60% off", "R-DOC",
        'README since PR #2: "VIP coupon: 60% off."', None,
        "sentence from PR #2", "A promise to customers, made two PRs ago.", derive_from="B1", stage=2)
    tested = t4.tested_baskets()
    add("T1", "unit tests pass", "R-TEST",
        "The repository's unit tests pass on PR #4.",
        Forall("c", Domain("TEST_RUN", ["python -m unittest"], False, ""),
               Pred("tests pass", lambda e: subprocess.run([sys.executable, "-m", "unittest", "tests.test_shop"], cwd=t4.root,
                                                           capture_output=True).returncode == 0)),
        "CI-style gate", "The tests are green.", stage=2,
        scope_note=f"Examples only. The tests run just these baskets: {sorted(tested)}.")
    witnesses_a1 = [w["b"] for w in a1.witnesses]
    add("T2", "tests would catch A1", "R-TEST",
        "The existing tests would have caught the baskets that make A1 fail.",
        Forall("w", Domain("WITNESSES(A1)", witnesses_a1, True, "the counterexamples found for A1"),
               Pred("a test runs w", lambda e: e["w"] in tested)),
        "tests were added in PR #3", "Why is the build green if the patch is wrong?", stage=2)
    add("U1", "stacking all three is intended", "R-HUMAN",
        "Letting coupon + bulk + member discounts all stack is what the business wants.",
        Pred("intended(stacking)", lambda e: (_ for _ in ()).throw(Undecidable("a business decision; code cannot decide it. A human must."))),
        "README line from PR #3: 'Discounts add up'", "Maybe the real fix is not a cap at all.", stage=2)

    # ---- 3. CALLERS: find them by parsing, then re-check on the same counterexample -
    defs = t4.call_graph()
    chain = callers_of(defs, "final_price")                    # [("checkout",1),("post_sale",2)]
    WIT = Domain("WITNESSES(A1)", witnesses_a1, False, "only the baskets that already broke A1")
    caller_claims = {
        "checkout": ("D1", "loyalty points never negative", "checkout() awards 1 loyalty point per 10 spent: points >= 0.",
                     Forall("w", WIT, Pred("points(w) >= 0", lambda e: t4.points(e["w"]) >= 0)),
                     "A negative total quietly takes points away from the customer."),
        "post_sale": ("D2", "a sale never lowers revenue", "ledger.post_sale() records a sale: revenue never goes down.",
                      Forall("w", WIT, Pred("revenue_after(w) >= revenue_before", lambda e: t4.revenue_after(e["w"]) >= 1000)),
                      "A negative sale makes the shop's books go down on a sale."),
    }
    for name, hops in chain:
        if name in caller_claims and R["A1"]["v"].label == REFUTED:
            id, short, claim, f, pw = caller_claims[name]
            add(id, short, "R-CALL", claim, f, f"{name}() calls final_price (found by parsing, {hops} hop{'s' if hops > 1 else ''} away)", pw,
                stage=3, hops=hops, fn=name)

    # derived (doc) claims inherit
    for c in list(R.values()):
        if c.get("derive_from"):
            src = R[c["derive_from"]]["v"]
            c["v"] = Verdict(src.label, f"README ⇔ {c['derive_from']}", src.witnesses, 0, src.assumptions,
                             note=f"derived: this sentence restates {c['derive_from']}, so it inherits its verdict (R-DOC)")

    # ---- plain-language examples from witnesses ---------------------------------
    def example(c):
        v, w = c["v"], (c["v"].witnesses[0] if c["v"].witnesses else None)
        if c["v"].label != REFUTED or not w:
            return ""
        if c["id"] in ("A1", "A2"):
            b = w["b"]; return f"A shopper with {fmt_basket(b)} is charged {t4.total(b):g}. The shop pays them."
        if c["id"] == "B1":
            return f"The VIP coupon was worth 60% off (price {t3.prices.final_price(BASE,[0.6]):g}). It now gives {t4.prices.final_price(BASE,[0.6]):g}."
        if c["id"] == "B2":
            return f"The README still tells customers 60% off. The code now delivers 50%."
        if c["id"] == "T2":
            return f"No test uses {fmt_basket(w['w'])}, so the build stays green."
        if c["id"] == "D1":
            b = w["w"]; return f"Same shopper ({fmt_basket(b)}): total {t4.total(b):g}, loyalty points {t4.points(b)}."
        if c["id"] == "D2":
            b = w["w"]; return f"Same shopper: revenue goes from 1000 to {t4.revenue_after(b):g} after a sale."
        return ""

    # ---- diff and line -> claim links ---------------------------------------------
    diff = git("diff", "-U0", pr3, pr4)
    files = {}
    for rel in ("shop/prices.py", "README.md"):
        files[rel] = [{"n": i + 1, "text": s, "changed": False, "claims": []} for i, s in enumerate(git("show", f"pr4:{rel}").splitlines())]
    cur = None
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            cur = line[6:]
        m = re.match(r"@@ -\S+ \+(\d+)(?:,(\d+))? @@", line)
        if m and cur in files:
            s, n = int(m.group(1)), int(m.group(2) or 1)
            for k in range(s, s + n):
                files[cur][k - 1]["changed"] = True
    for l in files["shop/prices.py"]:
        if l["changed"] and ("MAX_DISCOUNT" in l["text"] or "capped" in l["text"]):
            l["claims"] = ["A1", "P1", "B1", "U1"]
    for l in files["README.md"]:
        if l["changed"] and "never go negative" in l["text"]:
            l["claims"] = ["A2"]

    # ---- graph ------------------------------------------------------------------
    nodes = [  # id, label, sub, kind, col, stage
        ("PR1", "PR #1", "final_price", "pr", 0, 2), ("PR2", "PR #2", "coupons", "pr", 0, 2),
        ("PR3", "PR #3", "checkout, tests", "pr", 0, 2), ("PR4", "PR #4 (AI patch)", "under review", "cur", 0, 0),
        ("fp", "prices.final_price", "changed by PR #4", "code", 1, 0), ("rd4", "README.md", "new sentence (PR #4)", "code", 1, 0),
        ("cp", "coupons.py", "VIP = 60% (PR #2)", "code", 1, 2), ("rd2", "README promise", "VIP: 60% off (PR #2)", "code", 1, 2),
        ("bm", "bulk + member", "discounts (PR #3)", "code", 1, 2), ("ts", "tests", "run 2 baskets (PR #3)", "code", 1, 2),
        ("co", "checkout()", "calls final_price", "code", 1, 3), ("lg", "ledger.post_sale()", "calls checkout()", "code", 1, 3),
    ]
    for c in R.values():
        nodes.append((c["id"], f"{c['id']} {c['short']}", "", "claim", 2, c["stage"]))
    for c in R.values():
        nodes.append(("V" + c["id"], c["v"].label, c["id"], "ver", 3, 4))
    edges = [("PR4", "fp", "touch", 0), ("PR4", "rd4", "touch", 0), ("fp", "A1", "claim", 1), ("fp", "P1", "claim", 1),
             ("rd4", "A2", "claim", 1), ("A1", "A2", "derive", 1),
             ("PR2", "cp", "hist", 2), ("PR2", "rd2", "hist", 2), ("PR3", "bm", "hist", 2), ("PR3", "ts", "hist", 2),
             ("PR1", "fp", "hist", 2), ("cp", "B1", "claim", 2), ("fp", "B1", "claim", 2), ("rd2", "B2", "claim", 2), ("B1", "B2", "derive", 2),
             ("bm", "A1", "domain", 2), ("bm", "U1", "claim", 2), ("ts", "T1", "claim", 2), ("ts", "T2", "claim", 2), ("A1", "T2", "derive", 2),
             ("PR3", "co", "hist", 3), ("fp", "co", "calls", 3), ("co", "lg", "calls", 3), ("co", "D1", "claim", 3), ("lg", "D2", "claim", 3),
             ("A1", "D1", "derive", 3), ("A1", "D2", "derive", 3)]
    edges += [(c["id"], "V" + c["id"], "verdict", 4) for c in R.values()]

    claims = []
    for c in R.values():
        v = c["v"]
        claims.append(dict(
            id=c["id"], short=c["short"], rule=c["rule"], claim=c["claim"], origin=c["origin"], plain=c["plain"],
            formula=v.formula, label=v.label, checked=v.checked, assumptions=v.assumptions, note=v.note,
            scope_note=c.get("scope_note", ""), example=example(c), stage=c["stage"],
            tier={"R-DOC": "derived", "R-HUMAN": "human"}.get(c["rule"], "executed"),
            chain=[n for n, h in [("final_price", 0)] + chain if h <= c.get("hops", -1)] if c["rule"] == "R-CALL" else [],
            witnesses=[{k: (list(x) if isinstance(x, tuple) else x) for k, x in w.items()} for w in v.witnesses][:8],
            n_witnesses=len(v.witnesses), command=f"python toy/review.py --check {c['id']}"))
    return dict(pr3=pr3[:8], pr4=pr4[:8], claims=claims, files=files, nodes=nodes, edges=edges, rules=RULES,
                chain=[("final_price", 0)] + chain, base=BASE,
                log=git("log", "--format=%h|%s", "pr4").splitlines())


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--check")
    a = ap.parse_args()
    data = run_all()
    if a.check:
        c = next(c for c in data["claims"] if c["id"] == a.check)
        print(f"{c['id']}  {c['label'].upper()}\n  claim:   {c['claim']}\n  formula: {c['formula']}\n  commit:  {data['pr4']}")
        for w in c["witnesses"][:6]:
            print("  witness:", w)
        if c["example"]:
            print("  in plain words:", c["example"])
        if c["note"]:
            print("  note:   ", c["note"])
        return
    out = HERE / "out"
    out.mkdir(exist_ok=True)
    (out / "review.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    html = (HERE.parent / "trust" / "generic" / "viewer.html").read_text(encoding="utf-8").replace("__DATA__", json.dumps(data))
    (out / "review.html").write_text(html, encoding="utf-8")
    for c in data["claims"]:
        print(f"{c['id']}  {c['label']:<20} {c['short']}")
    print("call chain found by parsing:", " <- ".join(f"{n}({h})" for n, h in data["chain"]))
    print("wrote", out / "review.html")


if __name__ == "__main__":
    main()
