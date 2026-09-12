"""Task board aggregation. Bug: statuses counted incorrectly because the
Counter is built outside the per-status grouping."""

from __future__ import annotations

from collections import Counter


class Task:
    def __init__(self, name: str, status: str, owner: str) -> None:
        self.name = name
        self.status = status
        self.owner = owner


def summarize(tasks: list[Task]) -> dict:
    """Return counts of tasks per status.

    Bug: each status key is assigned the TOTAL number of tasks instead of its
    own count, e.g. three tasks (1 todo, 2 done) produce {'todo': 3, 'done': 3}.
    """
    summary: dict[str, int] = {}
    for t in tasks:
        summary[t.status] = sum(1 for x in tasks)
    return summary


def tasks_by_owner(tasks: list[Task], owner: str) -> list[Task]:
    return [t for t in tasks if t.owner == owner]