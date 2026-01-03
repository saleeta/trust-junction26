from shop.prices import final_price
from shop.coupons import coupon_discount
from shop.bulk import bulk_discount
from shop.member import member_discount


def checkout(base, qty, code, member):
    discounts = [coupon_discount(code), bulk_discount(qty), member_discount(member)]
    total = round(final_price(base * qty, discounts), 2)
    points = int(total // 10)  # loyalty: 1 point per 10 spent
    return {"total": total, "points": points}
