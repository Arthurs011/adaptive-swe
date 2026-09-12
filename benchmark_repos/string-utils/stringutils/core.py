"""String utilities. Bug: truncate() truncates text even when it already fits."""

from __future__ import annotations


def truncate(text: str, max_width: int) -> str:
    """Return text clipped to max_width with an ellipsis suffix when needed.

    Bug: the length check is missing, so text shorter than max_width still
    gets "..." appended (e.g. truncate("hi", 2) == "h...").
    """
    return text[: max_width - 3] + "..."


def word_count(text: str) -> int:
    if not text:
        return 0
    return len(text.split())


def reverse_words(text: str) -> str:
    return " ".join(reversed(text.split()))