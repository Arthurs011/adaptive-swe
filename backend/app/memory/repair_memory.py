"""Persistent repair memory: store + query.

Every repaired issue becomes a memory row. Future issues retrieve similar rows
to guide patch generation (contextual knowledge, never copied verbatim).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import get_settings
from ..models import RepairMemoryEntry
from .embeddings import Embedder
from .retrieval import MemoryRetriever, RetrievedMemory


@dataclass
class MemoryRecord:
    repository_url: str
    issue_description: str
    issue_category: str
    affected_files: list[str]
    affected_functions: list[str]
    fault_pattern: str
    generated_patch: str
    generated_tests: list[str]
    test_results: dict
    num_attempts: int
    successful: bool
    failure_reasons: list[str]
    solution_pattern: str
    session_id: str | None = None


class RepairMemory:
    def __init__(self, db_session_factory, embedder: Embedder | None = None) -> None:
        self.db_factory = db_session_factory
        self.embedder = embedder or Embedder()
        self.retriever = MemoryRetriever(db_session_factory, embedder)

    # -- store ----------------------------------------------------------------

    def store(self, record: MemoryRecord) -> RepairMemoryEntry:
        text_for_vec = (
            f"{record.issue_description}\n"
            f"category: {record.issue_category}\n"
            f"fault: {record.fault_pattern}\n"
            f"affected: {record.affected_files} {record.affected_functions}\n"
            f"solution: {record.solution_pattern}\n"
            f"patch:\n{record.generated_patch}"
        )
        vec = self.embedder.embed(text_for_vec)
        db = self.db_factory()
        try:
            entry = RepairMemoryEntry(
                repository_url=record.repository_url,
                issue_description=record.issue_description,
                issue_category=record.issue_category,
                affected_files=record.affected_files,
                affected_functions=record.affected_functions,
                fault_pattern=record.fault_pattern,
                generated_patch=record.generated_patch,
                generated_tests=record.generated_tests,
                test_results=record.test_results,
                num_attempts=record.num_attempts,
                successful=record.successful,
                failure_reasons=record.failure_reasons,
                solution_pattern=record.solution_pattern,
                embedding=vec,
                session_id=record.session_id,
            )
            db.add(entry)
            db.commit()
            db.refresh(entry)
            return entry
        finally:
            db.close()

    # -- query ----------------------------------------------------------------

    def load_all(self) -> list[dict]:
        db = self.db_factory()
        try:
            rows = db.query(RepairMemoryEntry).all()
            return [_entry_dict(r) for r in rows]
        finally:
            db.close()

    def count(self) -> int:
        db = self.db_factory()
        try:
            return db.query(RepairMemoryEntry).count()
        finally:
            db.close()

    def retrieve(
        self,
        issue_text: str,
        issue_category: str = "",
        repository_url: str = "",
        k: int = 3,
    ) -> RetrievedMemory:
        contents = self.load_all()
        hits = self.retriever.search(
            contents=contents,
            issue_text=issue_text,
            issue_category=issue_category,
            repository_url=repository_url,
            k=k,
        )
        db = self.db_factory()
        try:
            for e in hits.entries:
                row = db.query(RepairMemoryEntry).filter(RepairMemoryEntry.id == e.get("id")).first()
                if row:
                    row.usage_count = (row.usage_count or 0) + 1
            db.commit()
        finally:
            db.close()
        return hits


def _entry_dict(r: RepairMemoryEntry) -> dict:
    return {
        "id": r.id,
        "repository_url": r.repository_url,
        "issue_description": r.issue_description,
        "issue_category": r.issue_category,
        "affected_files": r.affected_files,
        "affected_functions": r.affected_functions,
        "fault_pattern": r.fault_pattern,
        "generated_patch": r.generated_patch,
        "generated_tests": r.generated_tests,
        "test_results": r.test_results,
        "num_attempts": r.num_attempts,
        "successful": r.successful,
        "failure_reasons": r.failure_reasons,
        "solution_pattern": r.solution_pattern,
        "embedding": r.embedding,
        "usage_count": r.usage_count or 0,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "session_id": r.session_id,
    }