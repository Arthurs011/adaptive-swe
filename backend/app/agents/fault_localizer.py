"""Fault Localization agent.

Given an issue analysis and repository structural info (ARISE-style graph),
rank candidate files/functions likely responsible for the bug.

It uses *selected* structural facts — not the whole repository — to build a
focused prompt, then asks the LLM to rank suspects.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..repository.analyzer import search_symbols, RepoAnalysis
from ..repository.graph import RepositoryGraph
from .base import BaseAgent

SYSTEM_PROMPT = """You are a Python fault localizer. Given a bug report and
repository structural facts, identify the functions/files most likely to cause
the bug.

Steps:
1. Cross-reference the issue keywords against the candidate symbols.
2. Prefer functions whose name/purpose matches the symptom.
3. Prefer functions in files that handle the user path described.

Reply ONLY with JSON:
{
  "suspects": [
    {"qualified": "module.function", "file": "path.py", "line": 1, "confidence": 0.9,
     "reason": "short rationale tied to the issue"}
  ]
}
List up to 6 suspects, best first. All qualified names MUST come from the
candidate list provided."""


@dataclass
class FaultLocalization:
    suspects: list[dict] = field(default_factory=list)

    @property
    def top(self) -> dict | None:
        return self.suspects[0] if self.suspects else None

    @property
    def files(self) -> list[str]:
        out: list[str] = []
        for s in self.suspects:
            if s.get("file") and s["file"] not in out:
                out.append(s["file"])
        return out


def _is_test_path(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    return any(p == "tests" or p.startswith("test_") or p.endswith("_test.py") for p in parts) or "test" in parts


def _is_test_symbol(q: str) -> bool:
    leaf = q.split(".")[-1]
    return leaf.startswith("test_") or leaf.endswith("_test") or "test" in q.split(".")[-2:-1]


class FaultLocalizer(BaseAgent):
    name = "fault_localizer"

    def localize(self, analysis: RepoAnalysis, graph: RepositoryGraph, issue_text: str, keywords: list[str]) -> FaultLocalization:
        keywords = [k for k in keywords if k]

        # 1. structural pre-filter on term matching (excluding test code)
        matched: set[str] = set()
        for kw in keywords:
            for sym in search_symbols(analysis, kw):
                fn = analysis.functions.get(sym)
                if fn and (_is_test_path(fn.file) or _is_test_symbol(sym)):
                    continue
                matched.add(sym)
        # 2. if nothing matched, include a breadth sample of non-test functions
        if not matched:
            matched.update(
                k for k in analysis.functions.keys()
                if not _is_test_symbol(k) and not _is_test_path(analysis.functions[k].file)
            )
        matched = set(list(matched)[:80])

        # Build compact candidate table + structural context for the top candidates
        rows: list[str] = []
        chosen: list[str] = []
        for sym in sorted(matched):
            fn = analysis.functions.get(sym)
            if not fn:
                continue
            chosen.append(sym)
        candidates = chosen[:40]

        for sym in candidates:
            fn = analysis.functions[sym]
            callers = graph.callers(sym)[:5]
            callees = graph.callees(sym)[:5]
            rows.append(
                f"- {sym} [{fn.file}:{fn.start}] params={fn.params} "
                f"callers={callers or '-'} callees={callees or '-'}"
            )

        prompt = (
            f"Bug report:\n{issue_text}\n\n"
            f"Issue keywords: {keywords}\n\n"
            f"Candidate functions (only choose from these):\n"
            + "\n".join(rows)
        )

        content, _t = self.llm.chat(SYSTEM_PROMPT, prompt, json_mode=True)
        raw = self.llm.parse_json(content)

        suspects: list[dict] = []
        for s in raw.get("suspects", []):
            q = s.get("qualified", "")
            if q not in candidates:
                continue
            suspects.append(
                {
                    "qualified": q,
                    "file": s.get("file") or analysis.functions[q].file,
                    "line": s.get("line", analysis.functions[q].start),
                    "confidence": float(s.get("confidence", 0.5)),
                    "reason": s.get("reason", ""),
                }
            )
        # fallback ordering by confidence
        suspects.sort(key=lambda x: x["confidence"], reverse=True)
        if not suspects and candidates:
            fn = analysis.functions[candidates[0]]
            suspects = [{"qualified": candidates[0], "file": fn.file, "line": fn.start, "confidence": 0.5, "reason": "fallback"}]
        return FaultLocalization(suspects=suspects)