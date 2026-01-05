def final_price(base, discounts):
    """Price after discounts. A discount of 0.2 means 20% off.

    The total discount is capped at 100%: a customer is never charged a
    negative price, and no single discount (VIP 60%) is limited on its own.
    """
    total = min(sum(discounts), 1.0)
    return base * (1 - total)
