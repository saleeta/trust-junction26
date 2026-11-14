"""
Builds a four-commit toy git repo: a tiny online shop.

  PR #1  prices.final_price           (requirement R-1: a price is never negative)
  PR #2  coupons: WELCOME 10%, HALF 50%, VIP 60%   (README promises "VIP: 60% off")
  PR #3  bulk + member discounts, checkout(), ledger.post_sale(), tests
  PR #4  the AI patch: "cap every discount at 50% so prices can't go negative"

The patch looks sensible and the tests stay green. It is wrong in three ways that
get progressively harder to see: in the diff, in an earlier PR, and in code that
merely CALLS the changed function.
"""
import os, shutil, stat, subprocess
from pathlib import Path

REPO = Path(__file__).parent / "_repo"

REQ = "R-1: a customer is never charged a negative price.\n"

PRICES1 = '''def final_price(base, discounts):
    """Price after discounts. A discount of 0.2 means 20% off."""
    return base * (1 - sum(discounts))
'''
PRICES4 = '''MAX_DISCOUNT = 0.5  # no single discount may take more than half off


def final_price(base, discounts):
    """Price after discounts. A discount of 0.2 means 20% off."""
    capped = [min(d, MAX_DISCOUNT) for d in discounts]
    return base * (1 - sum(capped))
'''
PRICES5 = '''def final_price(base, discounts):
    """Price after discounts. A discount of 0.2 means 20% off.

    The total discount is capped at 100%: a customer is never charged a
    negative price, and no single discount (VIP 60%) is limited on its own.
    """
    total = min(sum(discounts), 1.0)
    return base * (1 - total)
'''
COUPONS = '''COUPONS = {"WELCOME": 0.10, "HALF": 0.50, "VIP": 0.60}


def coupon_discount(code):
    return COUPONS.get(code, 0.0)
'''
BULK = '''def bulk_discount(qty):
    return 0.40 if qty >= 10 else 0.0
'''
MEMBER = '''def member_discount(is_member):
    return 0.20 if is_member else 0.0
'''
CHECKOUT = '''from shop.prices import final_price
from shop.coupons import coupon_discount
from shop.bulk import bulk_discount
from shop.member import member_discount


def checkout(base, qty, code, member):
    discounts = [coupon_discount(code), bulk_discount(qty), member_discount(member)]
    total = round(final_price(base * qty, discounts), 2)
    points = int(total // 10)  # loyalty: 1 point per 10 spent
    return {"total": total, "points": points}
'''
LEDGER = '''from shop.checkout import checkout


def post_sale(revenue_so_far, base, qty, code, member):
    return revenue_so_far + checkout(base, qty, code, member)["total"]
'''
TESTS = '''import unittest
from shop.checkout import checkout


class T(unittest.TestCase):
    def test_half_coupon(self):
        self.assertEqual(checkout(100, 1, "HALF", False)["total"], 50)

    def test_no_discount(self):
        self.assertEqual(checkout(100, 1, "", False)["total"], 100)
'''
README1 = "# shop\nPrices with discounts.\n"
README2 = README1 + "VIP coupon: 60% off.\n"
README3 = README2 + "Discounts add up: coupon + bulk (10+ items) + member.\n"
README4 = README3 + "Prices can never go negative.\n"


def _rm(fn, p, _):
    os.chmod(p, stat.S_IWRITE)
    fn(p)


def build() -> Path:
    if REPO.exists():
        shutil.rmtree(REPO, onerror=_rm)
    REPO.mkdir(parents=True)
    env = {**os.environ, "GIT_AUTHOR_NAME": "toy", "GIT_AUTHOR_EMAIL": "toy@example.com",
           "GIT_COMMITTER_NAME": "toy", "GIT_COMMITTER_EMAIL": "toy@example.com"}

    def git(*a, date="2026-01-01T12:00:00"):
        e = {**env, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
        subprocess.run(["git", *a], cwd=REPO, env=e, check=True, capture_output=True)

    def w(path, text):
        p = REPO / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")

    git("init", "-q")
    git("config", "core.autocrlf", "false")
    w("REQUIREMENTS.md", REQ); w("README.md", README1); w("shop/__init__.py", ""); w("shop/prices.py", PRICES1)
    git("add", "-A"); git("commit", "-qm", "PR #1: final_price", date="2026-01-01T12:00:00"); git("tag", "pr1")
    w("shop/coupons.py", COUPONS); w("README.md", README2)
    git("add", "-A"); git("commit", "-qm", "PR #2: coupons", date="2026-01-02T12:00:00"); git("tag", "pr2")
    w("shop/bulk.py", BULK); w("shop/member.py", MEMBER); w("shop/checkout.py", CHECKOUT)
    w("shop/ledger.py", LEDGER); w("tests/test_shop.py", TESTS); w("README.md", README3)
    git("add", "-A"); git("commit", "-qm", "PR #3: bulk, member, checkout, ledger, tests", date="2026-01-03T12:00:00"); git("tag", "pr3")
    w("shop/prices.py", PRICES4); w("README.md", README4)
    git("add", "-A"); git("commit", "-qm", "PR #4: cap discounts (AI patch)", date="2026-01-04T12:00:00"); git("tag", "pr4")
    # PR #5: the CORRECTED, human-accepted sample - total discount capped at
    # 100%, VIP 60% intact. This is the branch the named engineer signs.
    w("shop/prices.py", PRICES5); w("README.md", README4 + "Discounts add up, but the total discount is capped at 100%.\\n")
    git("add", "-A"); git("commit", "-qm", "PR #5: cap total discount at 100% (human-approved fix)", date="2026-01-05T12:00:00"); git("tag", "pr5")
    return REPO


if __name__ == "__main__":
    print(build())
