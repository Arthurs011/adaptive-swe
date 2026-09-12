"""Text utilities. Bug: count_lines() counts a phantom trailing line whenever
the text ends with a newline ('a\\nb\\n' is counted as 3 lines instead of 2)."""

from __future__ import annotations


def count_lines(text: str) -> int:
    """Number of lines in `text`.

    Bug: no handling of a trailing newline — the empty trailing element from
    split() is counted as a real line.
    """
    if not text:
        return 0
    return len(text.split("\n"))


def average_word_length(text: str) -> float:
    words = [w for w in text.split() if w]
    if not words:
        return 0.0
    return sum(len(w) for w in words) / len(words)


def count_words(text: str) -> int:
    return len([w for w in text.split() if w])