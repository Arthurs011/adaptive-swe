"""Agent base: shared prompt helpers and utility to read files by path."""

from __future__ import annotations

from ..config import get_settings
from ..repository.analyzer import RepoAnalysis, FunctionInfo
from .llm import LLMClient


class BaseAgent:
    name = "base"

    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or LLMClient()
        self.settings = get_settings()

    @staticmethod
    def read_file(root, path: str) -> str:
        """Read a repository file safely as text."""
        import os

        full = os.path.join(root, path.lstrip("/"))
        try:
            with open(full, encoding="utf-8", errors="replace") as fh:
                return fh.read()
        except OSError as exc:
            return f"# could not read {path}: {exc}"

    @staticmethod
    def render_functions(fns: list[FunctionInfo]) -> str:
        parts = []
        for i, fn in enumerate(fns, 1):
            parts.append(
                f"{i}. {fn.qualified}  ({fn.file}:{fn.start}-{fn.end})\n"
                f"   params={fn.params}"
            )
        return "\n".join(parts) if parts else "(none)"