"""Evaluation metrics computed from real runs."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EvalMetrics:
    total_issues: int = 0
    success: int = 0
    failure: int = 0
    pass_at_1: float = 0.0
    success_rate: float = 0.0
    avg_attempts: float = 0.0
    avg_duration_s: float = 0.0
    avg_tokens: float = 0.0
    regression_failures_total: int = 0
    fault_localization_hits: int = 0
    fault_localization_accuracy: float = 0.0
    per_issue: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total_issues": self.total_issues,
            "success": self.success,
            "failure": self.failure,
            "pass_at_1": round(self.pass_at_1, 4),
            "success_rate": round(self.success_rate, 4),
            "avg_attempts": round(self.avg_attempts, 2),
            "avg_duration_s": round(self.avg_duration_s, 2),
            "avg_tokens": round(self.avg_tokens, 1),
            "regression_failures_total": self.regression_failures_total,
            "fault_localization_hits": self.fault_localization_hits,
            "fault_localization_accuracy": round(self.fault_localization_accuracy, 4),
            "per_issue": self.per_issue,
        }


def compute_metrics(results: list[dict]) -> EvalMetrics:
    m = EvalMetrics(total_issues=len(results))
    attempts = [r.get("attempts", 0) for r in results]
    durations = [float(r.get("duration_seconds") or 0) for r in results]
    tokens = [int(r.get("tokens_used") or 0) for r in results]

    for r in results:
        if r.get("success"):
            m.success += 1
        else:
            m.failure += 1
        m.regression_failures_total += int(r.get("regression_failures") or 0)
        if r.get("fault_localization_correct"):
            m.fault_localization_hits += 1

    n = max(len(results), 1)
    m.pass_at_1 = sum(1 for r in results if r.get("success") and r.get("attempts", 0) <= 1) / n
    m.success_rate = m.success / n
    m.avg_attempts = sum(attempts) / n
    m.avg_duration_s = sum(durations) / n
    m.avg_tokens = sum(tokens) / n
    m.fault_localization_accuracy = m.fault_localization_hits / n
    m.per_issue = results
    return m


def memory_benefit(metrics_without: EvalMetrics, metrics_with: EvalMetrics) -> dict:
    return {
        "success_rate_delta": metrics_with.success_rate - metrics_without.success_rate,
        "avg_attempts_delta": metrics_with.avg_attempts - metrics_without.avg_attempts,
        "avg_tokens_delta": metrics_with.avg_tokens - metrics_without.avg_tokens,
        "avg_duration_delta_s": metrics_with.avg_duration_s - metrics_without.avg_duration_s,
        "pass_at_1_delta": metrics_with.pass_at_1 - metrics_without.pass_at_1,
        "regression_failures_delta": metrics_with.regression_failures_total - metrics_without.regression_failures_total,
        "conclusion": (
            "memory helps"
            if metrics_with.success_rate > metrics_without.success_rate
            or metrics_with.avg_attempts < metrics_without.avg_attempts
            else "no measured benefit (or worse)"
        ),
    }