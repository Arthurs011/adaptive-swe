"""FastAPI routes for the Adaptive-SWE system."""

from __future__ import annotations

import threading
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models
from ..agents.repair_agent import RepairAgent
from ..config import REPOS_DIR, get_settings
from ..database import SessionLocal, get_db
from ..evaluation.benchmark import BenchmarkIssue, run_benchmark
from ..memory.repair_memory import RepairMemory
from ..models import RepairSession, RepairStatus

router = APIRouter(prefix="/api")

# in-process job registry: session_id -> threading.Thread
_JOBS: dict[str, threading.Thread] = {}


class RepairRequest(BaseModel):
    repo_url: str
    title: str
    description: str
    use_memory: bool = True
    baseline: str = "proposed"  # baseline1 | baseline2 | proposed


class RepairStatusRequest(BaseModel):
    pass


# ------------------------------------------------------------------ repair

@router.post("/repair")
def start_repair(req: RepairRequest):
    settings = get_settings()
    db = SessionLocal()
    try:
        session = RepairSession(
            name=req.title[:240],
            status=RepairStatus.PENDING,
            use_memory=req.use_memory,
            baseline=req.baseline,
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        session_id = session.id
    finally:
        db.close()

    def _worker() -> None:
        agent = RepairAgent(settings)
        agent.run(
            repo_url=req.repo_url,
            title=req.title,
            description=req.description,
            session_id=session_id,
            use_memory=req.use_memory,
            baseline=req.baseline,
        )

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    _JOBS[session_id] = t
    return {"session_id": session_id, "status": "started"}


@router.get("/repair/{session_id}")
def repair_session(session_id: str, db: Session = Depends(get_db)):
    session = db.query(models.RepairSession).filter_by(id=session_id).first()
    if not session:
        raise HTTPException(404, "session not found")

    timeline = [
        {"step": e.step, "message": e.message, "detail": e.detail, "at": str(e.at)}
        for e in db.query(models.TimelineEvent)
        .filter_by(session_id=session_id)
        .order_by(models.TimelineEvent.at.asc())
        .all()
    ]
    attempts = []
    for a in db.query(models.RepairAttempt).filter_by(session_id=session_id).order_by(models.RepairAttempt.attempt_number.asc()).all():
        attempts.append(
            {
                "id": a.id,
                "attempt": a.attempt_number,
                "story": a.strategy_note,
                "failure_reason": a.failure_reason,
                "verified": a.verified,
                "regression_passed": a.regression_passed,
                "existing_passed": a.existing_passed,
                "existing_count": a.existing_test_count,
                "duration_s": a.duration_seconds,
                "tokens": a.tokens_used,
                "patches": [
                    {"content": p.content, "files": p.applied_files, "description": p.description}
                    for p in a.patches
                ],
                "tests": [
                    {"path": t.path, "content": t.content, "role": t.role} for t in a.tests
                ],
                "test_results": [
                    {
                        "test": r.test_name,
                        "outcome": r.outcome,
                        "duration_ms": r.duration_ms,
                        "message": r.message,
                    }
                    for r in a.test_results
                ],
            }
        )

    return {
        "id": session.id,
        "name": session.name,
        "status": session.status.value if hasattr(session.status, "value") else session.status,
        "baseline": session.baseline,
        "use_memory": session.use_memory,
        "started_at": str(session.started_at) if session.started_at else None,
        "completed_at": str(session.completed_at) if session.completed_at else None,
        "result_summary": session.result_summary,
        "timeline": timeline,
        "attempts": attempts,
        "jobs_pending": Thread_all_alive(session_id),
    }


def Thread_all_alive(session_id: str) -> bool:
    t = _JOBS.get(session_id)
    return bool(t and t.is_alive())


@router.post("/repair/{session_id}/graph")
def get_session_graph(session_id: str):
    """Return graph neighbourhood for a session (built during analysis)."""
    db = SessionLocal()
    try:
        session = db.query(models.RepairSession).get(session_id)
    finally:
        db.close()

    repo_dir = _repo_for_session(session_id)
    if not repo_dir:
        raise HTTPException(404, "no repository for session")
    from ..repository.analyzer import analyze_repository
    from ..repository.graph import build_graph

    analysis = analyze_repository(repo_dir)
    graph = build_graph(analysis)
    return graph.to_json()


@router.get("/repo/{session_id}/browse")
def browse(session_id: str, path: str = "."):
    repo_dir = _repo_for_session(session_id)
    if not repo_dir:
        raise HTTPException(404, "no repository for session")
    base = (repo_dir / path.lstrip("/")).resolve()
    if not str(base).startswith(str(repo_dir.resolve())):
        raise HTTPException(403, "path escapes repository")

    entries = []
    if base.is_dir():
        for child in sorted(base.iterdir()):
            name = child.name
            if name.startswith(".") or name in {"__pycache__"}:
                continue
            entries.append(
                {
                    "name": name,
                    "path": str(child.relative_to(repo_dir)),
                    "type": "dir" if child.is_dir() else "file",
                }
            )
        return {"path": str(base.relative_to(repo_dir)), "entries": entries}
    try:
        content = base.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise HTTPException(400, f"cannot read file: {exc}") from exc
    return {"path": str(base.relative_to(repo_dir)), "content": content, "file": True}


@router.get("/repo/{session_id}/functions")
def functions_index(session_id: str, term: str = ""):
    repo_dir = _repo_for_session(session_id)
    if not repo_dir:
        raise HTTPException(404, "no repository for session")
    from ..repository.analyzer import analyze_repository, search_symbols

    analysis = analyze_repository(repo_dir)
    if term:
        keys = search_symbols(analysis, term)
    else:
        keys = list(analysis.functions.keys())
    keys = keys[:300]
    out = []
    for k in keys:
        fn = analysis.functions[k]
        out.append(
            {
                "qualified": k,
                "file": fn.file,
                "start": fn.start,
                "end": fn.end,
                "params": fn.params,
            }
        )
    return {"functions": out}


# ------------------------------------------------------------------ dashboard

@router.get("/dashboard")
def dashboard():
    db = SessionLocal()
    try:
        sessions = db.query(models.RepairSession).all()
        total = len(sessions)
        success = sum(1 for s in sessions if s.status == RepairStatus.SUCCESS)
        failed = sum(1 for s in sessions if s.status == RepairStatus.FAILED)
        running = sum(
            1
            for s in sessions
            if s.status in (RepairStatus.PENDING, RepairStatus.REPAIRING, RepairStatus.VERIFYING)
            or Thread_all_alive(s.id)
        )
        attempts = [a for s in sessions for a in s.attempts]
        avg_attempts = round(sum(a.attempt_number for a in attempts) / max(len(attempts), 1), 2)
        memory_count = db.query(models.RepairMemoryEntry).count()

        recent = []
        for s in sessions[-10:][::-1]:
            recent.append(
                {
                    "id": s.id,
                    "name": s.name,
                    "status": s.status.value if hasattr(s.status, "value") else s.status,
                    "baseline": s.baseline,
                    "use_memory": s.use_memory,
                    "created_at": str(s.created_at),
                }
            )

        return {
            "total_sessions": total,
            "success": success,
            "failed": failed,
            "running": running,
            "success_rate": round(success / max(total, 1), 4),
            "avg_attempts": avg_attempts,
            "memory_entries": memory_count,
            "recent": recent,
        }
    finally:
        db.close()


# ------------------------------------------------------------------ memory

@router.get("/memory")
def memory_list(limit: int = Query(50, le=500)):
    mem = RepairMemory(SessionLocal)
    entries = mem.load_all()
    return {"count": len(entries), "entries": entries[-limit:][::-1]}


@router.delete("/memory/{entry_id}")
def memory_delete(entry_id: str):
    db = SessionLocal()
    try:
        row = db.query(models.RepairMemoryEntry).get(entry_id)
        if not row:
            raise HTTPException(404, "memory entry not found")
        db.delete(row)
        db.commit()
        return {"deleted": entry_id}
    finally:
        db.close()


# ------------------------------------------------------------------ evaluation

class EvalRequest(BaseModel):
    baseline: str = "proposed"
    use_memory: bool = True
    limit: int = 1
    issues: list[dict] = []


@router.post("/evaluate")
def evaluate(req: EvalRequest):
    if req.issues:
        issues = [
            BenchmarkIssue(
                key=i["key"],
                repo_url=i["repo_url"],
                title=i["title"],
                description=i["description"],
            )
            for i in req.issues
        ]
    else:
        from ..evaluation.benchmark import DEFAULT_ISSUES

        issues = DEFAULT_ISSUES
    metrics = run_benchmark(
        issues=issues,
        baseline=req.baseline,
        use_memory=req.use_memory,
        limit=req.limit,
    )
    return metrics.to_dict()


@router.get("/evaluations")
def evaluations():
    db = SessionLocal()
    try:
        runs = (
            db.query(models.EvaluationRun)
            .order_by(models.EvaluationRun.started_at.desc())
            .limit(20)
            .all()
        )
        return [
            {
                "id": r.id,
                "name": r.name,
                "baseline": r.baseline,
                "use_memory": r.use_memory,
                "metrics": r.metrics,
                "started_at": str(r.started_at),
                "completed_at": str(r.completed_at) if r.completed_at else None,
            }
            for r in runs
        ]
    finally:
        db.close()


@router.get("/comparison")
def memory_comparison():
    db = SessionLocal()
    try:
        nomem = (
            db.query(models.EvaluationRun)
            .filter_by(use_memory=False)
            .order_by(models.EvaluationRun.created_at.desc())
            .first()
        )
        wmem = (
            db.query(models.EvaluationRun)
            .filter_by(use_memory=True)
            .order_by(models.EvaluationRun.created_at.desc())
            .first()
        )
        if not nomem or not wmem:
            return {
                "available": False,
                "message": "Run one evaluation with use_memory=false and one with use_memory=true.",
            }
        from ..evaluation.metrics import EvalMetrics, memory_benefit

        a = EvalMetrics(**nomem.metrics) if nomem.metrics else EvalMetrics()
        b = EvalMetrics(**wmem.metrics) if wmem.metrics else EvalMetrics()
        return {"available": True, "no_memory": a.to_dict(), "with_memory": b.to_dict(), "benefit": memory_benefit(a, b)}
    finally:
        db.close()


# ------------------------------------------------------------------ helpers

def _repo_for_session(session_id: str) -> Path | None:
    session = None
    db = SessionLocal()
    try:
        session = db.query(models.RepairSession).get(session_id)
    finally:
        db.close()
    if not session or not session.repository_id:
        # fallback: use most recently cloned repo
        paths = sorted(REPOS_DIR.iterdir()) if REPOS_DIR.exists() else []
        newest = sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)
        return newest[0] if newest else None
    db2 = SessionLocal()
    try:
        repo = db2.query(models.Repository).get(session.repository_id)
        if repo and repo.local_path:
            return Path(repo.local_path)
    finally:
        db2.close()
    return None