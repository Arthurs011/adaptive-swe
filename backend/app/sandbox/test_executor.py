"""Test executor: runs pytest inside the chosen sandbox and parses results.

Supports two stages:
1. Regression test against ORIGINAL code  (expect FAIL = reproduction)
2. Regression test + existing suite against PATCHED code (expect PASS)
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from .docker_runner import SandboxRunner

EXCLUDE_PATTERNS = ['__pycache__', 'node_modules', '.venv', 'venv']


@dataclass
class ParsedTestResult:
    test_name: str
    outcome: str  # passed | failed | error | skipped
    duration_ms: float = 0.0
    message: str = ""


@dataclass
class TestRunReport:
    results: list[ParsedTestResult] = field(default_factory=list)
    returncode: int = 0
    timed_out: bool = False
    runner: str = "local"
    raw_stdout: str = ""
    raw_meta: str = ""
    collected: int = 0

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.outcome == "passed")

    @property
    def failed(self) -> list[ParsedTestResult]:
        return [r for r in self.results if r.outcome in ("failed", "error")]

    @property
    def as_dicts(self) -> list[dict]:
        return [
            {"test": r.test_name, "outcome": r.outcome, "duration_ms": r.duration_ms, "message": r.message[:2000]}
            for r in self.results
        ]


class TestExecutor:
    def __init__(self, settings=None) -> None:
        self.runner = SandboxRunner(settings)

    # -- main entry points -----------------------------------------------------

    def run_regression_on_original(self, repo_root: Path, test_path: str) -> TestRunReport:
        """Run only the regression test against unpatched code."""
        return self._execute(repo_root, [test_path])

    def run_verification(self, repo_root: Path, regression_path: str, existing_paths: list[str]) -> TestRunReport:
        paths = [regression_path] + existing_paths
        return self._execute(repo_root, paths)

    # -- internals -------------------------------------------------------------

    def _execute(self, repo_root: Path, test_paths: list[str]) -> TestRunReport:
        repo_root = Path(repo_root)
        test_paths = [p for p in test_paths if p]
        if not test_paths:
            return TestRunReport(results=[], returncode=0)

        # docker runner gets pyproject_dir (the repo itself)
        result = self.runner.run_pytest(repo_root, test_paths, repo_root)

        # prefer junit XML produced by the runner
        results = _parse_junit(result.junit_xml) if result.junit_xml else []

        # fallback: junit.xml left in the repo working tree
        if not results:
            junit_path = repo_root / "junit.xml"
            if junit_path.exists():
                results = _parse_junit(junit_path.read_text(errors="replace"))
                junit_path.unlink()

        if not results:
            results = _parse_stdout(result.stdout)

        report = TestRunReport(
            results=results,
            returncode=result.returncode,
            timed_out=result.timed_out,
            runner=result.runner,
            raw_stdout=(result.stdout or "")[:3000],
            raw_meta=result.message,
            collected=len(results),
        )
        # mark skip/error entries from tracebacks on stderr
        if results and report.returncode != 0 and not results:
            pass
        return report


def _parse_junit(xml_text: str) -> list[ParsedTestResult]:
    results: list[ParsedTestResult] = []
    try:
        root = ET.fromstring(xml_text)
        for suite in root.iter("testsuite"):
            for case in suite.iter("testcase"):
                name = case.get("name", "")
                classname = case.get("classname", "")
                full = f"{classname}::{name}" if classname and name else (name or classname or "unknown")
                dur = float(case.get("time", "0") or 0) * 1000
                outcome = "passed"
                msg = ""
                for child in case:
                    if child.tag == "failure":
                        outcome = "failed"
                        msg = (child.get("message") or "")[:2000]
                    elif child.tag == "error":
                        outcome = "error"
                        msg = (child.get("message") or "")[:2000]
                    elif child.tag == "skipped":
                        outcome = "skipped"
                if outcome == "passed" and dur < 0.0001:
                    pass
                results.append(ParsedTestResult(test_name=full, outcome=outcome, duration_ms=round(dur, 2), message=msg))
    except ET.ParseError:
        return []
    return results


def _parse_stdout(text: str) -> list[ParsedTestResult]:
    """Fallback: parse `-q` output lines like `tests/test_x.py::test_abc FAILED`."""
    results: list[ParsedTestResult] = []
    partial = re.compile(r"^(.*?::(.+?)) (PASSED|FAILED|ERROR|SKIPPED)")
    for line in text.splitlines():
        m = partial.match(line)
        if not m:
            if line.startswith("F") and "::" in line:
                # possible failure line is already on previous line
                continue
            continue
        test_name, leaf, status = m.group(1), m.group(2), m.group(3)
        results.append(
            ParsedTestResult(
                test_name=test_name,
                outcome={"PASSED": "passed", "FAILED": "failed", "ERROR": "error", "SKIPPED": "skipped"}[status],
            )
        )
    return results


def discover_python_tests(repo_root: Path) -> list[str]:
    """Find pytest files (excluding vendored/venv dirs)."""
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_PATTERNS and not d.startswith(".")]
        for fn in filenames:
            if fn.startswith("test_") and fn.endswith(".py"):
                rel = os.path.relpath(os.path.join(dirpath, fn), str(repo_root))
                found.append(rel)
            elif fn.endswith("_test.py"):
                rel = os.path.relpath(os.path.join(dirpath, fn), str(repo_root))
                found.append(rel)
    return found