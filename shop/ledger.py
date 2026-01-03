from shop.checkout import checkout


def post_sale(revenue_so_far, base, qty, code, member):
    return revenue_so_far + checkout(base, qty, code, member)["total"]
