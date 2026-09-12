"""Benchmark runner.

Executes a set of (repo_url, issue) pairs under a given baseline / memory
configuration, mirroring the key experiment:

    Experiment A: no repair memory
    Experiment B: repair memory enabled

Deliberately designed so the hypothesis can be disproved: results come purely
from real executions and are aggregated honestly.
"""

from __future__ import annotations

import csv
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..agents.repair_agent import RepairAgent
from ..config import RESULTS_DIR
from ..database import SessionLocal
from ..models import EvaluationResult, EvaluationRun
from .metrics import compute_metrics, EvalMetrics


@dataclass
class BenchmarkIssue:
    key: str
    repo_url: str
    title: str
    description: str


_REPOS = "benchmark_repos"


def _local(repo: str) -> str:
    return str(Path(__file__).resolve().parents[2].parent / _REPOS / repo)


DEFAULT_ISSUES: list[BenchmarkIssue] = [
    BenchmarkIssue(
        key="discount-negative-qty",
        repo_url=_local("discount-calc"),
        title="Negative quantity produces incorrect total",
        description=(
            "Calling calculate_discount() with a negative quantity produces an "
            "incorrect total. A negative quantity should be rejected (e.g. raise "
            "ValueError or clamp) instead of producing a nonsensical discount."
        ),
    ),
    BenchmarkIssue(
        key="csv-empty-input",
        repo_url=_local("csv-import"),
        title="Empty CSV causes server error",
        description=(
            "CSVParser.parse() crashes with IndexError when the CSV input is empty "
            "(no rows). It should handle the empty-input case gracefully instead of raising."
        ),
    ),
    BenchmarkIssue(
        key="string-truncate-short",
        repo_url=_local("string-utils"),
        title="truncate() truncates short text",
        description=(
            "truncate('hi', 2) returns 'h...' instead of 'hi' because the length check "
            "is missing. Text shorter than max_width must be returned unchanged."
        ),
    ),
    BenchmarkIssue(
        key="taskboard-status-counts",
        repo_url=_local("task-board"),
        title="Task status counts are all wrong",
        description=(
            "summarize() returns for every status the total number of tasks instead of "
            "the per-status count. Three tasks (1 todo, 2 done) should produce "
            "{'todo': 1, 'done': 2} but currently produce {'todo': 3, 'done': 3}."
        ),
    ),
    BenchmarkIssue(
        key="flatten-list-descend",
        repo_url=_local("json-flattener"),
        title="flatten() does not descend into lists",
        description=(
            "flatten() stores list values untouched instead of indexing them. "
            "flatten({'a': [1, 2, {'b': 3}]}) should produce {'a.0': 1, 'a.1': 2, "
            "'a.2.b': 3} but currently keeps the list verbatim."
        ),
    ),
    BenchmarkIssue(
        key="ratelimiter-window-reset",
        repo_url=_local("rate-limiter"),
        title="Rate limiter becomes unlimited after first window",
        description=(
            "is_allowed() resets the request count when a window expires but never "
            "advances the window start, so after the first window every request "
            "gets a fresh bucket and the limit is never enforced again."
        ),
    ),
    BenchmarkIssue(
        key="invoice-untaxed-items",
        repo_url=_local("invoice-total"),
        title="Cheap items are not taxed",
        description=(
            "calculate_total() skips line items priced under $1.00 when computing "
            "the taxable base. An item at $0.50 x2 with 10% tax should total $1.10, "
            "currently it returns $1.00."
        ),
    ),
    BenchmarkIssue(
        key="textstats-trailing-newline",
        repo_url=_local("text-stats"),
        title="count_lines() miscounts trailing newlines",
        description=(
            "count_lines() counts a phantom extra line when text ends with a "
            "newline: count_lines('one\\ntwo\\n') returns 3 instead of 2."
        ),
    ),
    BenchmarkIssue(
        key="search-punctuation",
        repo_url=_local("search-index"),
        title="Tokenizer keeps punctuation and case",
        description=(
            "tokenize() does not strip punctuation or lower-case words, so "
            "'Hello, world!' tokenizes to ['Hello,', 'world!'] instead of "
            "['hello', 'world']."
        ),
    ),
    BenchmarkIssue(
        key="url-fake-scheme",
        repo_url=_local("url-toolkit"),
        title="is_valid_url() accepts made-up URLs",
        description=(
            "is_valid_url() returns True for any '<scheme>://<text>' string such as "
            "'notaurl://thing', even though the host has no valid domain or address. "
            "It must validate the host portion."
        ),
    ),
]


def run_benchmark(
    issues: list[BenchmarkIssue],
    baseline: str,
    use_memory: bool,
    name: str | None = None,
    limit: int | None = None,
) -> EvalMetrics:
    """Run a benchmark configuration; returns aggregated metrics."""
    run_name = name or f"{baseline}-{'mem' if use_memory else 'nomem'}-{int(time.time())}"

    db = SessionLocal()
    try:
        run = EvaluationRun(
            name=run_name,
            config={"baseline": baseline, "use_memory": use_memory, "issues": len(issues)},
            baseline=baseline,
            use_memory=use_memory,
        )
        db.add(run)
        db.commit()
        run_id = run.id
    finally:
        db.close()

    agent = RepairAgent()
    results: list[dict] = []

    for issue in issues[:limit]:
        key = issue.key
        item = {
            "key": key,
            "repo_url": issue.repo_url,
            "title": issue.title,
            "description": issue.description,
        }
        eval_row = _create_eval_result(run_id, key, item)

        start = time.time()
        outcome = agent.run(
            repo_url=issue.repo_url,
            title=issue.title,
            description=issue.description,
            session_id=_make_session(run_id, key, item, baseline, use_memory),
            use_memory=use_memory,
            baseline=baseline,
            eval_result=eval_row,
        )
        elapsed = time.time() - start

        result = {
            "key": key,
            "success": outcome.get("success", False),
            "attempts": outcome.get("attempts", 0),
            "duration_seconds": elapsed,
            "tokens_used": outcome.get("tokens_used", 0),
            "regression_failures": outcome.get("attempts", 0),
            "fault_localization_correct": None,
            "detail": {"error": outcome.get("error")},
        }
        results.append(result)

    metrics = compute_metrics(results)

    db = SessionLocal()
    try:
        run = db.query(EvaluationRun).get(run_id)
        if run:
            run.metrics = metrics.to_dict()
            run.completed_at = datetime.now(timezone.utc)
            run.items = [i.__dict__ for i in issues[:limit]]
        db.commit()
    finally:
        db.close()

    export_csv(run_name, metrics)
    return metrics


def _create_eval_result(run_id: str, key: str, item: dict) -> EvaluationResult:
    db = SessionLocal()
    try:
        row = EvaluationResult(
            evaluation_run_id=run_id,
            issue_key=key,
            detail={"title": item["title"], "description": item["description"]},
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    finally:
        db.close()


def _make_session(run_id: str, key: str, item: dict, baseline: str, use_memory: bool) -> str:
    from ..models import RepairSession, RepairStatus
    from ..repository.github import parse_github_url

    info = parse_github_url(item["repo_url"])
    db = SessionLocal()
    try:
        row = RepairSession(
            name=f"bench: {baseline} mem={use_memory} {key}",
            repository_id=None,
            issue_id=None,
            status=RepairStatus.PENDING,
            baseline=baseline,
            use_memory=use_memory,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    finally:
        db.close()


def export_csv(name: str, metrics: EvalMetrics) -> str:
    path = RESULTS_DIR / f"{name}.csv"
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["metric", "value"])
        for k, v in metrics.to_dict().items():
            if k != "per_issue":
                writer.writerow([k, v])
    return str(path)


def compare_runs(metrics_a: EvalMetrics, metrics_b: EvalMetrics) -> dict:
    from .metrics import memory_benefit

    return memory_benefit(metrics_a, metrics_b)