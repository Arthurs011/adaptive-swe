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


DEFAULT_ISSUES: list[BenchmarkIssue] = [
    BenchmarkIssue(
        key="calc-divide-zero",
        repo_url="https://github.com/harm-dev/calculator-demo",
        title="Division by zero crashes calculator",
        description=(
            "Calling calculate('/') or divide() with a zero divisor raises "
            "ZeroDivisionError instead of returning a friendly error. Handle "
            "the zero-divisor edge case."
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