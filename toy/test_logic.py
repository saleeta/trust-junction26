import pytest
from logic import *

D = lambda items, ex=True: Domain("D", items, ex, "listed")

def test_refuted_has_witness():
    v = check(Forall("x", D([1, 2, 3]), Pred("x<3", lambda e: e["x"] < 3)))
    assert v.label == REFUTED and v.witnesses == [{"x": 3}]

def test_proved_needs_exhaustive_domain():
    f = lambda ex: Forall("x", D([1, 2], ex), Pred("pos", lambda e: e["x"] > 0))
    assert check(f(True)).label == PROVED
    assert check(f(False)).label == TESTED      # a sample can never prove

def test_refutation_beats_sampling():
    v = check(Forall("x", D([5], False), Pred("neg", lambda e: e["x"] < 0)))
    assert v.label == REFUTED                    # one counterexample is enough

def test_undecidable_is_unknown_not_proved():
    def boom(e): raise Undecidable("no checker")
    assert check(Pred("p", boom)).label == UNKNOWN

def test_implies_vacuous_and_nested():
    f = Forall("t", D(["a", "b"]), Forall("n", D([1, 2]),
        Implies(Pred("is_b", lambda e: e["t"] == "b"), Pred("n==1", lambda e: e["n"] == 1))))
    v = check(f)
    assert v.label == REFUTED and v.witnesses == [{"t": "b", "n": 2}]
