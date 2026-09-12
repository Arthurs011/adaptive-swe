"""Failure Analysis agent.

Given a failed test run (regression test + existing suite), decide WHAT went
wrong and recommend a revised strategy for the next patch attempt.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .base import BaseAgent

SYSTEM_PROMPT = """You are an expert debugger. A repair attempt produced these test
results. Analyse the failures and advise the next attempt.

Input: JSON with regression test results and existing test results, plus the
patch strategy used.

Determine:
1. Did the regression test still fail (patch did not fix) OR did existing tests
   break (patch changed shared behaviour)?
2. The most likely root cause of each failure (read the assertion/traceback text).
3. A concrete revision strategy for the next patch.

Reply ONLY with JSON:
{
  "diagnosis": "one paragraph explaining the situation",
  "fault_class": "no-fix | regression-broke-existing | collect-error | other",
  "likely_root_causes": ["..."],
  "revision_strategy": "specific advised change for the next patch",
  "suggested_focus": "which function/file the next attempt should modify"
}"""


@dataclass
class FailureAnalysis:
    diagnosis: str = ""
    fault_class: str = "other"
    likely_root_causes: list[str] = field(default_factory=list)
    revision_strategy: str = ""
    suggested_focus: str = ""
    raw: dict = field(default_factory=dict)


class FailureAnalyzer(BaseAgent):
    name = "failure_analyzer"

    def analyze(
        self,
        regression_results: list[dict],
        existing_results: list[dict],
        patch_strategy: str,
        regression_test_names: list[str],
    ) -> FailureAnalysis:
        payload = {
            "regression_tests": regression_results,
            "existing_tests": existing_results[:60],
            "patch_strategy": patch_strategy,
            "expected_regression_tests": regression_test_names,
        }
        content, _t = self.llm.chat(
            SYSTEM_PROMPT,
            ("Test results:\n" + str(payload)[:9000]),
            json_mode=True,
        )
        raw = self.llm.parse_json(content)
        return FailureAnalysis(
            diagnosis=raw.get("diagnosis", ""),
            fault_class=raw.get("fault_class", "other"),
            likely_root_causes=raw.get("likely_root_causes", []),
            revision_strategy=raw.get("revision_strategy", ""),
            suggested_focus=raw.get("suggested_focus", ""),
            raw=raw,
        )