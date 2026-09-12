"""Search index tokenizer. Bug: punctuation is kept on tokens and words are
not lower-cased, so 'Hello, world!' tokenizes to ['Hello,', 'world!'] instead
of ['hello', 'world']."""

from __future__ import annotations

import re

PUNCT = re.compile(r"[.,!?;:'\"()\[\]{}<>]")


def tokenize(text: str) -> list[str]:
    """Split `text` into lower-cased alphanumeric tokens.

    Bug: punctuation is never stripped and case is preserved.
    """
    return [w for w in text.split() if w]