"""Barcode validation and conservative extraction from an individual source product."""

import re
from collections.abc import Mapping


def valid_ean(value: str) -> bool:
    # GTIN-14 is supported alongside EAN-8 and EAN-13. Preserve leading zeros.
    if not isinstance(value, str) or not re.fullmatch(r"(?:[0-9]{8}|[0-9]{13}|[0-9]{14})", value):
        return False
    total = sum(int(digit) * (3 if i % 2 == 0 else 1) for i, digit in enumerate(value[-2::-1]))
    return (10 - total % 10) % 10 == int(value[-1])


def source_ean(*products: Mapping) -> str | None:
    """Accept only explicit, valid, unambiguous barcode fields, never SKU/article IDs.

    Do not recursively search unrelated products, infer barcodes from names or
    coerce numeric values: doing so can attach a variant's code to a group offer
    or lose leading zeros. Multiple distinct codes cannot fit the singular ean.
    """
    codes = set()
    for product in products:
        for key, value in product.items():
            if key.lower() not in {"ean", "ean8", "ean13", "gtin", "gtin8", "gtin13", "gtin14"}:
                continue
            if value is None or value == "":
                continue
            values = value if isinstance(value, list) else [value]
            for code in values:
                if not valid_ean(code):
                    return None
                codes.add(code)
    return next(iter(codes)) if len(codes) == 1 else None


def barcode_scope(value: str) -> str:
    """RCN prefixes are not globally comparable product identities (GS1 specs)."""
    if len(value) == 8:
        restricted = value.startswith(("0", "2"))
    else:
        base = value[-13:]
        restricted = base.startswith("2") or base.startswith("02")
    return "restricted_circulation" if restricted else "global_candidate"
