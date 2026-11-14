"""
recall - the graph retrieval API (sprints.md #6).

The mechanism behind "pull in only what it needs". A reviewer should not be
handed a transcript and a 237-file diff; it should ask a question and get back
a few cited snippets, with the cost of that retrieval accounted for.

Backed by SQLite + FTS5 (both stdlib), so the store works long after the
originating transcript is gone, and ships inside the repo as `.trust/memory.db`.

    store = Store(path)
    store.ingest_graph(graph_json)        # session provenance
    store.ingest_diff(repo, base, branch) # the change itself
    store.ingest_assumptions(ledger_json) # the assumption ledger
    store.ingest_text("issue", text)

    r = store.recall("why is the attribute guarded", budget_tokens=1500)
    for hit in r.hits:
        print(hit.citation, hit.snippet)

EVERY HIT CARRIES A CITATION. A retrieval layer that returns text without
saying where it came from just launders provenance, which is the opposite of
the point.

TOKEN ACCOUNTING
----------------
`tokens` is an ESTIMATE (ceil(chars/4)) unless `tiktoken` is installed, and
`Recall.estimated` says which. Honest accounting means labelling the estimate,
not hiding it. `Recall.full_dump_tokens` reports what dumping every stored row
would have cost, so the saving is measured rather than asserted.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS evidence (
    id         INTEGER PRIMARY KEY,
    kind       TEXT NOT NULL,
    ref        TEXT NOT NULL,
    symbol     TEXT,
    path       TEXT,
    text       TEXT NOT NULL,
    provenance TEXT NOT NULL,
    weight     REAL DEFAULT 1.0
);
CREATE INDEX IF NOT EXISTS idx_ev_path   ON evidence(path);
CREATE INDEX IF NOT EXISTS idx_ev_symbol ON evidence(symbol);
CREATE INDEX IF NOT EXISTS idx_ev_kind   ON evidence(kind);

CREATE VIRTUAL TABLE IF NOT EXISTS evidence_fts USING fts5(
    ref, symbol, path, text,
    content='evidence', content_rowid='id', tokenize='porter unicode61'
);
"""

TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS ev_ai AFTER INSERT ON evidence BEGIN
  INSERT INTO evidence_fts(rowid, ref, symbol, path, text)
  VALUES (new.id, new.ref, COALESCE(new.symbol,''), COALESCE(new.path,''), new.text);
END;
CREATE TRIGGER IF NOT EXISTS ev_ad AFTER DELETE ON evidence BEGIN
  INSERT INTO evidence_fts(evidence_fts, rowid, ref, symbol, path, text)
  VALUES ('delete', old.id, old.ref, COALESCE(old.symbol,''), COALESCE(old.path,''), old.text);
END;
"""


# ---------------------------------------------------------------------------
# token accounting
# ---------------------------------------------------------------------------

def _tiktoken_counter():
    try:
        import tiktoken  # type: ignore
        enc = tiktoken.get_encoding("cl100k_base")
        return lambda s: len(enc.encode(s)), False
    except Exception:
        return lambda s: math.ceil(len(s) / 4), True


_COUNT, _ESTIMATED = _tiktoken_counter()


def count_tokens(s: str) -> int:
    return _COUNT(s or "")


# ---------------------------------------------------------------------------
# results
# ---------------------------------------------------------------------------

@dataclass
class Hit:
    kind: str
    ref: str
    snippet: str
    citation: str
    provenance: dict[str, Any]
    score: float
    tokens: int

    def render(self) -> str:
        return f"[{self.kind}] {self.citation}\n{self.snippet}"


@dataclass
class Recall:
    query: str
    mode: str
    hits: list[Hit] = field(default_factory=list)
    budget_tokens: int = 0
    tokens_used: int = 0
    candidates_considered: int = 0
    hits_dropped_for_budget: int = 0
    full_dump_tokens: int = 0
    estimated: bool = _ESTIMATED

    @property
    def saving_ratio(self) -> float:
        if not self.full_dump_tokens:
            return 0.0
        return 1.0 - (self.tokens_used / self.full_dump_tokens)

    def as_context(self) -> str:
        """The block handed to a model, citations included."""
        return "\n\n".join(h.render() for h in self.hits)

    def summary(self) -> str:
        est = " (estimated)" if self.estimated else ""
        return (f"recall({self.mode}:{self.query!r}) -> {len(self.hits)} hits, "
                f"{self.tokens_used}/{self.budget_tokens} tokens{est}; "
                f"full dump would be {self.full_dump_tokens} "
                f"({self.saving_ratio:.0%} saved); "
                f"{self.hits_dropped_for_budget} dropped for budget")


# ---------------------------------------------------------------------------
# store
# ---------------------------------------------------------------------------

class Store:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        try:
            self.db.executescript(TRIGGERS)
        except sqlite3.OperationalError:
            pass
        self.db.commit()

    # -- writing ---------------------------------------------------------
    def add(self, kind: str, ref: str, text: str, provenance: dict,
            symbol: str | None = None, path: str | None = None,
            weight: float = 1.0) -> int:
        text = (text or "").strip()
        if not text:
            return -1
        cur = self.db.execute(
            "INSERT INTO evidence(kind, ref, symbol, path, text, provenance, weight)"
            " VALUES (?,?,?,?,?,?,?)",
            (kind, ref, symbol, path, text, json.dumps(provenance), weight))
        return int(cur.lastrowid or -1)

    def ingest_graph(self, graph: dict) -> int:
        """Session provenance: prompts, decisions, tool calls, commits."""
        n = 0
        interesting = {"PROMPT": 2.0, "DECISION": 3.0, "TOOL_CALL": 0.8,
                       "COMMIT": 1.5, "BRANCH": 1.0, "ARTIFACT": 1.2,
                       "FINDING": 2.0, "REQUIREMENT": 2.0, "HYPOTHESIS": 1.0}
        for node in graph.get("nodes", []):
            t = node.get("type")
            if t not in interesting:
                continue
            prov = node.get("provenance") or {}
            body = node.get("detail") or node.get("label") or ""
            if t == "DECISION":
                body = (f"QUESTION: {prov.get('question','')}\n"
                        f"CHOSEN: {prov.get('chosen')}\n"
                        f"REJECTED: {', '.join(prov.get('rejected') or [])}")
            self.add(kind=f"graph:{t}", ref=node.get("id", ""), text=body,
                     provenance=prov, path=prov.get("path"),
                     weight=interesting[t])
            n += 1
        self.db.commit()
        return n

    def ingest_diff(self, repo: Path, base: str, branch: str,
                    skip_generated: bool = True) -> int:
        """One row per changed file's hunks, so retrieval can be file-scoped."""
        def git(*a: str) -> str:
            p = subprocess.run(["git", *a], cwd=repo, capture_output=True,
                               text=True, timeout=300)
            return p.stdout if p.returncode == 0 else ""

        names = [l for l in git("diff", "--name-only",
                                f"{base}..{branch}").splitlines() if l.strip()]
        n = 0
        for path in names:
            if skip_generated and re.search(r"(\.g\.cs$|\.verified\.|/Resources/)",
                                            path):
                continue
            hunk = git("diff", f"{base}..{branch}", "--", path)
            if not hunk:
                continue
            self.add(kind="diff", ref=path, text=hunk[:20000],
                     provenance={"base": base, "branch": branch, "path": path,
                                 "verify": f"git diff {base[:9]}..{branch} -- {path}"},
                     path=path, symbol=Path(path).stem, weight=1.5)
            n += 1
        # a single compact row describing the generated bulk, so it is
        # representable without being dumped
        gen = [p for p in names if re.search(r"(\.g\.cs$|\.verified\.)", p)]
        if gen:
            self.add(kind="diff-summary", ref="generated files",
                     text=(f"{len(gen)} generated/snapshot files changed, e.g. "
                           + ", ".join(gen[:5])),
                     provenance={"count": len(gen),
                                 "verify": f"git diff --name-only {base[:9]}..{branch}"},
                     weight=0.5)
            n += 1
        self.db.commit()
        return n

    def ingest_assumptions(self, ledger: list[dict]) -> int:
        n = 0
        for b in ledger:
            a = b.get("assumption", {})
            sites = b.get("sites", [])
            hyps = b.get("hypotheses", [])
            text = (f"ASSUMPTION: {a.get('statement')}\n"
                    f"VERDICT: {a.get('verdict')}\n"
                    f"SOURCE: {a.get('source_kind')} {a.get('source_ref')}\n"
                    f"EVIDENCE: " + "; ".join(a.get("evidence") or []) + "\n"
                    f"IMPACT SITES: {len(sites)}\n"
                    f"HYPOTHESES: " + "; ".join(
                        h.get("failure_mode", "") for h in hyps))
            self.add(kind="assumption", ref=a.get("id", ""), text=text,
                     provenance={"verdict": a.get("verdict"),
                                 "severity": b.get("severity"),
                                 "reconstructed": a.get("reconstructed", False),
                                 "verify": a.get("check_cmd", "")},
                     weight=3.0)
            n += 1
        self.db.commit()
        return n

    def ingest_text(self, kind: str, text: str, ref: str = "",
                    provenance: dict | None = None, weight: float = 2.0) -> int:
        i = self.add(kind=kind, ref=ref or kind, text=text,
                     provenance=provenance or {"kind": kind}, weight=weight)
        self.db.commit()
        return i

    # -- reading ---------------------------------------------------------
    @property
    def size(self) -> int:
        return int(self.db.execute("SELECT COUNT(*) FROM evidence").fetchone()[0])

    def full_dump_tokens(self) -> int:
        rows = self.db.execute("SELECT text FROM evidence").fetchall()
        return sum(count_tokens(r["text"]) for r in rows)

    def recall(self, query: str, mode: str = "question",
               budget_tokens: int = 2000, limit: int = 12,
               snippet_chars: int = 1200) -> Recall:
        """Retrieve cited snippets for a query within a token budget.

        mode: question (full-text), symbol (exact-ish), path (prefix/suffix).
        """
        r = Recall(query=query, mode=mode, budget_tokens=budget_tokens,
                   full_dump_tokens=self.full_dump_tokens())

        if mode == "path":
            rows = self.db.execute(
                "SELECT *, 1.0 AS rank FROM evidence WHERE path LIKE ? "
                "ORDER BY weight DESC LIMIT ?", (f"%{query}%", limit * 3)).fetchall()
        elif mode == "symbol":
            rows = self.db.execute(
                "SELECT *, 1.0 AS rank FROM evidence "
                "WHERE symbol = ? OR symbol LIKE ? OR ref LIKE ? "
                "ORDER BY weight DESC LIMIT ?",
                (query, f"%{query}%", f"%{query}%", limit * 3)).fetchall()
        else:
            try:
                rows = self.db.execute(
                    "SELECT e.*, bm25(evidence_fts) AS rank "
                    "FROM evidence_fts JOIN evidence e ON e.id = evidence_fts.rowid "
                    "WHERE evidence_fts MATCH ? "
                    "ORDER BY rank LIMIT ?",
                    (_fts_query(query), limit * 3)).fetchall()
            except sqlite3.OperationalError:
                rows = []
            if not rows:   # fall back to LIKE so a miss is never silent
                terms = [t for t in re.findall(r"\w{4,}", query.lower())][:4]
                if terms:
                    clause = " OR ".join("LOWER(text) LIKE ?" for _ in terms)
                    rows = self.db.execute(
                        f"SELECT *, 1.0 AS rank FROM evidence WHERE {clause} "
                        "ORDER BY weight DESC LIMIT ?",
                        (*[f"%{t}%" for t in terms], limit * 3)).fetchall()

        r.candidates_considered = len(rows)

        scored = []
        for row in rows:
            base = -float(row["rank"]) if row["rank"] < 0 else 1.0 / (1.0 + abs(float(row["rank"])))
            scored.append((base * float(row["weight"]), row))
        scored.sort(key=lambda x: -x[0])

        for score, row in scored:
            if len(r.hits) >= limit:
                r.hits_dropped_for_budget += 1
                continue
            snippet = _focus(row["text"], query, snippet_chars)
            tok = count_tokens(snippet)
            if r.tokens_used + tok > budget_tokens:
                r.hits_dropped_for_budget += 1
                continue
            prov = json.loads(row["provenance"])
            r.hits.append(Hit(
                kind=row["kind"], ref=row["ref"], snippet=snippet,
                citation=_citation(row["kind"], row["ref"], prov),
                provenance=prov, score=score, tokens=tok))
            r.tokens_used += tok
        return r

    def close(self) -> None:
        self.db.close()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _fts_query(q: str) -> str:
    """FTS5 is picky; quote each term and OR them."""
    terms = re.findall(r"\w+", q)
    terms = [t for t in terms if len(t) > 2][:12]
    if not terms:
        return '"' + q.replace('"', "") + '"'
    return " OR ".join(f'"{t}"' for t in terms)


def _focus(text: str, query: str, limit: int) -> str:
    """Return the most relevant window, not a blind prefix."""
    if len(text) <= limit:
        return text
    terms = [t.lower() for t in re.findall(r"\w{4,}", query)]
    low = text.lower()
    best, pos = 0, 0
    for t in terms:
        i = low.find(t)
        if i >= 0:
            window = low[max(0, i - limit // 2): i + limit // 2]
            hits = sum(window.count(x) for x in terms)
            if hits > best:
                best, pos = hits, i
    start = max(0, pos - limit // 3)
    out = text[start:start + limit]
    prefix = "..." if start else ""
    suffix = "..." if start + limit < len(text) else ""
    return f"{prefix}{out}{suffix}"


def _citation(kind: str, ref: str, prov: dict) -> str:
    bits = [ref]
    if prov.get("transcript_uuid"):
        bits.append(f"uuid={str(prov['transcript_uuid'])[:8]}")
    if prov.get("sha"):
        bits.append(f"sha={str(prov['sha'])[:9]}")
    if prov.get("verify"):
        bits.append(f"verify: {prov['verify']}")
    if prov.get("reconstructed"):
        bits.append("RECONSTRUCTED")
    return f"{kind} :: " + " | ".join(bits)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_store(db: Path, repo: Path | None, base: str | None, branch: str | None,
                graph: Path | None, ledger: Path | None,
                issue: Path | None) -> Store:
    store = Store(db)
    if graph and graph.exists():
        n = store.ingest_graph(json.loads(graph.read_text(encoding="utf-8")))
        print(f"  ingested {n} graph nodes")
    if repo and base and branch:
        n = store.ingest_diff(repo, base, branch)
        print(f"  ingested {n} diff rows")
    if ledger and ledger.exists():
        n = store.ingest_assumptions(json.loads(ledger.read_text(encoding="utf-8")))
        print(f"  ingested {n} assumption rows")
    if issue and issue.exists():
        store.ingest_text("issue", issue.read_text(encoding="utf-8"),
                          ref=issue.name,
                          provenance={"source": "issue tracker", "file": str(issue)})
        print("  ingested issue text")
    return store


def main(argv: list[str] | None = None) -> int:
    import argparse
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            pass

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="../../.trust/memory.db")
    ap.add_argument("--repo"); ap.add_argument("--base"); ap.add_argument("--branch")
    ap.add_argument("--graph"); ap.add_argument("--ledger"); ap.add_argument("--issue")
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--query"); ap.add_argument("--mode", default="question",
                                                choices=["question", "symbol", "path"])
    ap.add_argument("--budget", type=int, default=2000)
    args = ap.parse_args(argv)

    db = Path(args.db)
    if args.rebuild and db.exists():
        db.unlink()

    if args.rebuild or not db.exists():
        print(f"building {db}")
        store = build_store(
            db, Path(args.repo).resolve() if args.repo else None,
            args.base, args.branch,
            Path(args.graph) if args.graph else None,
            Path(args.ledger) if args.ledger else None,
            Path(args.issue) if args.issue else None)
    else:
        store = Store(db)

    print(f"store holds {store.size} evidence rows "
          f"({store.full_dump_tokens()} tokens if dumped whole)")

    if args.query:
        r = store.recall(args.query, mode=args.mode, budget_tokens=args.budget)
        print(f"\n{r.summary()}\n")
        for h in r.hits:
            print("-" * 72)
            print(f"{h.citation}   [{h.tokens} tokens, score {h.score:.3f}]")
            print(h.snippet[:700])
        print("-" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
