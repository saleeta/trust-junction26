"""Small, executable example used by the claim comparison slide.

The requirement is: unknown items return "not found" without an exception.
The AI patch replaced prices.get(item, "not found") with prices[item].
"""

import json

PRICES = {"foo": 10, "bar": 20}
TESTED_ITEMS = ("foo", "bar")


def price(item: str):
    return PRICES[item]  # AI patch: before, PRICES.get(item, "not found")


def checkout(item: str) -> str:
    return f"Pay {price(item)}"


def observe(fn, item: str) -> dict:
    try:
        return {"input": item, "result": fn(item), "error": None}
    except KeyError:
        return {"input": item, "result": None, "error": "KeyError"}


if __name__ == "__main__":
    print(json.dumps({
        "known_foo": observe(price, "foo"),
        "known_bar": observe(price, "bar"),
        "unknown": observe(price, "baz"),
        "caller_unknown": observe(checkout, "baz"),
        "tested_items": TESTED_ITEMS,
    }, indent=2))
