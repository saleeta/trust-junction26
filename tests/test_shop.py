import unittest
from shop.checkout import checkout


class T(unittest.TestCase):
    def test_half_coupon(self):
        self.assertEqual(checkout(100, 1, "HALF", False)["total"], 50)

    def test_no_discount(self):
        self.assertEqual(checkout(100, 1, "", False)["total"], 100)
