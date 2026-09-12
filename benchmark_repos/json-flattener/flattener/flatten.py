"""Flatten nested dicts to dotted keys. Bug: list values are never descended
into, so {'a': [1, 2, {'b': 3}]} becomes {'a': [1, 2, {'b': 3}]} instead of
{'a.0': 1, 'a.1': 2, 'a.2.b': 3}."""

from __future__ import annotations


def flatten(obj: dict, prefix: str = "") -> dict:
    """Flatten a nested dict into dotted-key paths.

    Lists are indexed ('items.0') and dicts inside lists are recursed into.
    Bug: only dict values are recursed; list values are stored untouched.
    """
    out: dict = {}
    for k, v in obj.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(flatten(v, key + "."))
        else:
            out[key] = v
    return out