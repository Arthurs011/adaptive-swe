"""Invoice totals. Bug: only line items priced at $1.00 or more are taxed, so
cheap items silently escape the tax rate."""

from __future__ import annotations

from collections.abc import Iterable


def calculate_total(line_items: Iterable[tuple[float, int]], tax_rate: float = 0.10) -> float:
    """Return the total, tax included, for `(price, quantity)` line items.

    Bug: the taxable base skips items priced below $1.00, so their share of
    the subtotal is never taxed.
    """
    subtotal = sum(price * qty for price, qty in line_items)
    taxable = sum(price * qty for price, qty in line_items if price >= 1.00)
    return round(subtotal + taxable * tax_rate, 2)