"""Patch Generation agent.

Given the bug, suspect functions (with full source), relevant callers/callees
context and optionally similar repair-memory examples, produce the *new full
content* of each file it touches. The unified diff is derived from git so it
is always well-formed.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field

from ..utils import files_from_diff as _files_from_diff
from .base import BaseAgent

SYSTEM_PROMPT = """You are a senior Python engineer producing a minimal patch for a bug.

You are given:
- bug description
- the FULL current source of the files that may need changes
- related structural context (callers/callees, related code snippets)
- optional: similar past repairs (treated as contextual knowledge only — do NOT copy)

Task: for every file that needs a change, produce the file's NEW complete
source (the whole file after your edit). Keep changes minimal and surgical.
Do not reformat or rename unrelated symbols. Do not change file paths.

Reply ONLY with JSON:
{
  "edits": [
    {
      "path": "relative/repo/path.py",
      "new_content": "<complete new file content, all lines, JSON-escaped \\n>"
    }
  ],
  "strategy": "short description of what changed and why",
  "risk": "which existing behaviours could be affected"
}

Rules:
- `path` must use EXACTLY the repository-relative paths given in the prompt.
  Do not invent prefixes like a top-level `src/` folder.
- `new_content` must be the ENTIRE file after editing (not just the changed
  hunk). It must parse as valid Python when the file is a .py file."""


@dataclass
class Edit:
    path: str
    new_content: str


@dataclass
class PatchResult:
    diff: str
    files: list[str]
    strategy: str
    risk: str = ""
    edits: list[Edit] = field(default_factory=list)
    applied: bool = False


class PatchGenerator(BaseAgent):
    name = "patch_generator"

    def generate(
        self,
        issue_text: str,
        suspects: list[dict],
        analysis,
        graph,
        memory_context: str = "",
        failure_context: str | None = None,
    ) -> PatchResult:
        parts: list[str] = []
        parts.append(f"Bug report:\n{issue_text}")

        if failure_context:
            parts.append(f"\nPrevious attempt feedback (revise accordingly):\n{failure_context}")

        files_needed: list[str] = []
        for s in suspects[:4]:
            fn = analysis.functions.get(s.get("qualified"))
            if fn and fn.file not in files_needed:
                files_needed.append(fn.file)
            source = fn.source if fn else "<not found>"
            callers = graph.callers(s["qualified"])[:6]
            callees = graph.callees(s["qualified"])[:6]
            parts.append(
                f"\n--- Suspect {s['qualified']} ({s['file']}:{s.get('line')}) ---\n"
                f"EXACT repository path (use verbatim): {s['file']}\n"
                f"reason: {s.get('reason', '')}\n"
                f"callers: {callers}\ncallees: {callees}\n"
                f"function source:\n{source}"
            )

        # include the full source of the suspect files
        for f in files_needed:
            full = self.read_file(self._root, f) if hasattr(self, "_root") else ""
            parts.append(f"\n===== FULL CURRENT CONTENT OF {f} =====\n{full}")

        if memory_context:
            parts.append(f"\n=== Similar past repairs (context only, adapt — never copy verbatim) ===\n{memory_context[:8000]}")

        content, _t = self.llm.chat(SYSTEM_PROMPT, "\n\n".join(parts), json_mode=True)
        raw = self.llm.parse_json(content)
        edits = [
            Edit(path=e.get("path", "").strip(), new_content=e.get("new_content", ""))
            for e in raw.get("edits", [])
            if e.get("path")
        ]
        return PatchResult(
            diff="",
            files=[e.path for e in edits],
            strategy=raw.get("strategy", ""),
            risk=raw.get("risk", ""),
            edits=edits,
        )

    def validate_edits(self, edits: list[Edit]) -> list[str]:
        """Return list of errors; empty list means edits are healthy."""
        errors: list[str] = []
        for e in edits:
            if not e.path:
                errors.append("edit with empty path")
            if not e.new_content.strip():
                errors.append(f"empty content for {e.path}")
            elif e.path.endswith(".py"):
                try:
                    ast.parse(e.new_content)
                except SyntaxError as exc:
                    errors.append(f"{e.path}: invalid Python syntax ({exc.msg} line {exc.lineno})")
        return errors