def final_price(base, discounts):
    """Price after discounts. A discount of 0.2 means 20% off."""
    return base * (1 - sum(discounts))
