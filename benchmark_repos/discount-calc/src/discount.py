"""Discount calculation module for the demo repository."""

from __future__ import annotations


def calculate_discount(quantity: int, unit_price: float, coupon: str = "") -> float:
    """Compute total price after bulk and coupon discounts.

    Bug: calling with a negative quantity produces an incorrect total
    (no negative-quantity validation).
    """
    subtotal = quantity * unit_price

    if quantity >= 100:
        subtotal = subtotal * 0.8
    elif quantity >= 50:
        subtotal = subtotal * 0.9
    elif quantity >= 10:
        subtotal = subtotal * 0.95

    if coupon == "SAVE10":
        subtotal = subtotal * 0.9
    elif coupon == "FLAT5":
        subtotal = subtotal - 5.0

    return subtotal