"""Embedding helpers backed by the configured model (with offline fallback)."""

from __future__ import annotations

from ..agents.llm import LLMClient


class Embedder:
    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or LLMClient()

    def embed(self, text: str) -> list[float]:
        return self.llm.embed([text])[0]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return self.llm.embed(texts)


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5 or 1.0
    nb = sum(y * y for y in b) ** 0.5 or 1.0
    return dot / (na * nb)