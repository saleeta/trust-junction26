"""
logic - a tiny first-order logic over FINITE domains, with honest verdict labels.

A claim is a formula.  Evaluating it can end four ways, and the label is decided
by how the evaluation ended, never by who wrote the claim:

    Refuted               a counterexample (witness) was found.   Always sound.
    Proved within scope   every element of every domain was checked, and every
                          domain is declared exhaustive *under listed assumptions*.
    Tested                no counterexample, but some domain was only a sample.
    Unknown               a predicate raised Undecidable (no checker exists).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable

PROVED, REFUTED, TESTED, UNKNOWN = "Proved within scope", "Refuted", "Tested", "Unknown"


class Undecidable(Exception):
    """A predicate has no checker.  Becomes the label Unknown."""


@dataclass
class Domain:
    name: str
    items: list
    exhaustive: bool = True      # False => a sample: no-counterexample means Tested
    assumption: str = ""         # what must hold for 'exhaustive' to be true


@dataclass
class Verdict:
    label: str
    formula: str
    witnesses: list = field(default_factory=list)
    checked: int = 0
    assumptions: list = field(default_factory=list)
    note: str = ""


class F:
    def show(self) -> str: raise NotImplementedError


@dataclass
class Pred(F):
    name: str
    fn: Callable[[dict], bool]
    def show(self): return self.name


@dataclass
class Not(F):
    f: F
    def show(self): return "¬" + self.f.show()


@dataclass
class Implies(F):
    a: F
    b: F
    def show(self): return f"({self.a.show()} → {self.b.show()})"


@dataclass
class Forall(F):
    var: str
    domain: Domain | Callable[[dict], Domain]
    body: F
    def dom(self, env): return self.domain(env) if callable(self.domain) else self.domain
    def show(self):
        d = self.domain.name if isinstance(self.domain, Domain) else "…"
        return f"∀ {self.var} ∈ {d}. {self.body.show()}"


class _Acc:
    def __init__(self): self.n = 0; self.exhaustive = True; self.assumptions = []


def _ev(f: F, env: dict, acc: _Acc, cap: int = 50):
    """-> (truth, witnesses).  Witness = the variable bindings that break f."""
    if isinstance(f, Pred):
        acc.n += 1
        ok = bool(f.fn(env))
        return ok, ([] if ok else [{}])
    if isinstance(f, Not):
        t, _ = _ev(f.f, env, acc, cap)
        return (not t), ([] if not t else [{}])
    if isinstance(f, Implies):
        ta, _ = _ev(f.a, env, acc, cap)
        return (True, []) if not ta else _ev(f.b, env, acc, cap)
    if isinstance(f, Forall):
        d = f.dom(env)
        if not d.exhaustive:
            acc.exhaustive = False
        if d.assumption and d.assumption not in acc.assumptions:
            acc.assumptions.append(d.assumption)
        bad = []
        for item in d.items:
            t, ws = _ev(f.body, {**env, f.var: item}, acc, cap)
            if not t:
                bad += [{f.var: item, **w} for w in ws]
                if len(bad) >= cap:
                    break
        return (not bad), bad
    raise TypeError(f)


def check(f: F, env: dict | None = None) -> Verdict:
    acc = _Acc()
    try:
        ok, ws = _ev(f, env or {}, acc)
    except Undecidable as e:
        return Verdict(UNKNOWN, f.show(), checked=acc.n, assumptions=acc.assumptions, note=str(e))
    if not ok:
        return Verdict(REFUTED, f.show(), ws, acc.n, acc.assumptions)
    label = PROVED if acc.exhaustive else TESTED
    return Verdict(label, f.show(), [], acc.n, acc.assumptions)
