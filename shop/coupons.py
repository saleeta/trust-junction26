COUPONS = {"WELCOME": 0.10, "HALF": 0.50, "VIP": 0.60}


def coupon_discount(code):
    return COUPONS.get(code, 0.0)
