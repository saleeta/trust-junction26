MAX_DISCOUNT = 0.5  # no single discount may take more than half off


def final_price(base, discounts):
    """Price after discounts. A discount of 0.2 means 20% off."""
    capped = [min(d, MAX_DISCOUNT) for d in discounts]
    return base * (1 - sum(capped))
