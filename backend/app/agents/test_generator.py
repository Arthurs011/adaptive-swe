"""Regression Test Generation agent.

Creates pytest regression tests that reproduce the reported bug. The test is
written against the repository's public surface and must FAIL on the original
code (proving reproduction) and PASS on the fixed code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .base import BaseAgent

SYSTEM_PROMPT = """You are a Python test engineer. Write a focused pytest regression
test that reproduces a bug.

Given:
- bug description
- the suspect function sources
- repository test conventions hint (one existing test snippet)

Requirements:
- Use a real file path for a NEW test file (e.g. tests/test_<case>_regression.py).
- Only import from the repository's own modules.
- Keep it self-contained; guard imports so collection errors are detectable.
- The test MUST fail (assert False / raise / wrong result) when the bug exists.

Reply ONLY with JSON:
{
  "path": "relative/path/to/test_file.py",
  "content": "<full python test file>",
  "test_names": ["test_...", "..."]
}"""


@dataclass
class GeneratedTest:
    path: str
    content: str
    test_names: list[str]


class TestGenerator(BaseAgent):
    name = "test_generator"

    def generate(
        self, issue_text: str, suspects: list[dict], analysis,
        existing_test_hint: str = "", test_failure_context: str | None = None,
    ) -> GeneratedTest:
        parts = [f"Bug description:\n{issue_text}"]
        if test_failure_context:
            parts.append(f"\nThe previous regression test was faulty; fix it using this feedback:\n{test_failure_context}")
        for s in suspects[:3]:
            fn = analysis.functions.get(s.get("qualified"))
            if fn:
                parts.append(f"\nSuspect {s['qualified']} ({s['file']}):\n{fn.source}")
        # show an existing test to mirror its construction/import style
        if existing_test_hint:
            parts.append(f"\nExisting test style hint (mirror how objects are constructed/imported):\n{existing_test_hint[:1200]}")
        if not existing_test_hint:
            parts.append(
                "\nNote: construct objects exactly as the module API requires. If a "
                "constructor needs arguments, pass them."
            )

        content, _t = self.llm.chat(SYSTEM_PROMPT, "\n\n".join(parts), json_mode=True)
        raw = self.llm.parse_json(content)
        path = raw.get("path", "tests/test_regression.py")
        code = raw.get("content", "# no test generated")
        # extract test function names
        names = re.findall(r"^def (test_\w+)\s*\(", code, re.MULTILINE)
        return GeneratedTest(path=path, content=code, test_names=names or ["test_"])

    @staticmethod
    def has_test_functions(code: str) -> bool:
        return bool(re.search(r"^def (test_\w+)\s*\(", code, re.MULTILINE))