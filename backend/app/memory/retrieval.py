"""Repair-memory retrieval.

Searches the persistent repair memory for rows similar to a new issue and
formats them into compact, prompt-friendly knowledge snippets.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .embeddings import Embedder, cosine

if TYPE_CHECKING:
    from ..database import SessionLocal as SessionType  # noqa: F401


@dataclass
class RetrievedMemory:
    entries: list[dict] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.entries)

    def to_prompt(self, limit: int = 3, max_chars: int = 8000) -> str:
        parts: list[str] = []
        used = 0
        for e in self.entries[:limit]:
            block = (
                f"--- Past repair (repo={e.get('repository_url')}, category={e.get('issue_category', '?')}) ---\n"
                f"Issue: {e.get('issue_description', '')[:400]}\n"
                f"Fault pattern: {e.get('fault_pattern', '')}\n"
                f"Affected: {e.get('affected_files', [])}\n"
                f"Functions: {e.get('affected_functions', [])}\n"
                f"Successful strategy: {e.get('solution_pattern', '')}\n"
                f"Attempts needed: {e.get('num_attempts')}"
            )
            used += len(block)
            if used > max_chars:
                break
            parts.append(block)
        return "\n\n".join(parts)


class MemoryRetriever:
    def __init__(self, db_session_factory, embedder: Embedder | None = None) -> None:
        self.db_factory = db_session_factory
        self.embedder = embedder or Embedder()

    def search(
        self,
        contents: list[dict],
        issue_text: str,
        issue_category: str = "",
        repository_url: str = "",
        embed_text: str = "",
        k: int = 3,
    ) -> RetrievedMemory:
        """Search given memory entries (already loaded) by embedding similarity."""
        if not contents:
            return RetrievedMemory([])
        query = embed_text or issue_text
        q_vec = self.embedder.embed(query)
        scored: list[tuple[float, dict]] = []
        for e in contents:
            emb = e.get("embedding")
            sim = cosine(q_vec, emb) if emb else 0.0
            # structural bonus: same repo, same category
            if repository_url and e.get("repository_url") == repository_url:
                sim += 0.15
            if issue_category and e.get("issue_category") == issue_category:
                sim += 0.08
            scored.append((sim, e))
        scored.sort(key=lambda x: x[0], reverse=True)
        best = scored[:k]
        entries = []
        for sim, e in best:
            row = dict(e)
            row["score"] = round(sim, 4)
            entries.append(row)
        return RetrievedMemory(entries=entries)