"""Issue Understanding agent.

Classifies the bug report into a category, extracts report details and memory
search keywords, without looking at any code. Pure issue-side analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .base import BaseAgent

SYSTEM_PROMPT = """You are an expert bug-triage analyst. Given a software bug report
(title + description), classify the bug and extract structured information.

Reply ONLY with JSON matching this schema:
{
  "category": "one of: validation, null/empty handling, logic error, crash/exception, boundary/off-by-one, concurrency, type mismatch, performance, regression, formatting, state/leak, other",
  "summary": "one-sentence summary of the bug",
  "keywords": ["up to 10 low-level identifiers, function/method/variable names or domain terms the user mentions"],
  "symptom": "what fails for the user (exception type, wrong output, etc.)",
  "expectation": "what correct behaviour should be"
}"""


@dataclass
class IssueAnalysis:
    category: str
    summary: str
    keywords: list[str] = field(default_factory=list)
    symptom: str = ""
    expectation: str = ""
    raw: dict = field(default_factory=dict)


class IssueAnalyzer(BaseAgent):
    name = "issue_analyzer"

    def analyze(self, title: str, description: str) -> IssueAnalysis:
        content, _tokens = self.llm.chat(
            SYSTEM_PROMPT,
            f"Title: {title}\n\nDescription:\n{description}",
            json_mode=True,
        )
        raw = self.llm.parse_json(content)
        return IssueAnalysis(
            category=raw.get("category", "other"),
            summary=raw.get("summary", title),
            keywords=raw.get("keywords", []),
            symptom=raw.get("symptom", ""),
            expectation=raw.get("expectation", ""),
            raw=raw,
        )