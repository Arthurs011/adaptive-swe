"""Repair orchestration agent.

Runs the full adaptive self-healing loop:

    clone -> analyze -> graph -> issue understanding -> fault localization
    -> memory retrieval -> regression test generation -> original-run
    -> [patch -> verify -> failure analysis -> revise]* -> success
    -> memory store -> final report

Supports three baselines via configuration:
    baseline1 : plain LLM (issue + selected files, no graph, no memory)
    baseline2 : AutoCodeRover-style iterative repair (graph, no persistent memory)
    proposed  : full system (graph + dataflow + persistent memory + adaptive loop)
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from .. import utils
from ..agents.failure_analyzer import FailureAnalyzer
from ..agents.fault_localizer import FaultLocalizer
from ..agents.issue_analyzer import IssueAnalyzer
from ..agents.llm import LLMClient
from ..agents.patch_generator import PatchGenerator
from ..agents.test_generator import TestGenerator
from ..config import REPOS_DIR, get_settings
from ..database import SessionLocal, init_db
from ..memory.repair_memory import RepairMemory, MemoryRecord
from ..models import (
    EvaluationResult,
    Issue,
    Patch,
    RepairAttempt,
    RepairMemoryEntry,
    RepairSession,
    RepairStatus,
    Repository,
    TestFile,
    TestResult,
    TimelineEvent,
)
from ..repository.analyzer import analyze_repository
from ..repository.github import parse_github_url
from ..repository.graph import build_graph
from ..sandbox.docker_runner import SandboxRunner
from ..sandbox.test_executor import TestExecutor, discover_python_tests


class RepairAgent:
    def __init__(self, settings=None) -> None:
        self.settings = settings or get_settings()
        self.llm = LLMClient(self.settings)
        self.issue_analyzer = IssueAnalyzer(self.llm)
        self.fault_localizer = FaultLocalizer(self.llm)
        self.patch_generator = PatchGenerator(self.llm)
        self.test_generator = TestGenerator(self.llm)
        self.failure_analyzer = FailureAnalyzer(self.llm)
        self.executor = TestExecutor(self.settings)
        self.memory = RepairMemory(SessionLocal, embedder=None)
        self._analysis = None
        self._graph = None
        self.repo_path: Path | None = None
        self._session_id: str | None = None

    # ------------------------------------------------------------------ setup

    def _event(self, session_id: str, step: str, message: str, detail: dict | None = None) -> None:
        db = SessionLocal()
        try:
            db.add(TimelineEvent(session_id=session_id, step=step, message=message, detail=detail or {}))
            db.commit()
        finally:
            db.close()

    @property
    def token_count(self) -> int:
        return self.llm.total_tokens

    def _set_status(self, session_id: str, status: RepairStatus) -> None:
        db = SessionLocal()
        try:
            s = db.query(RepairSession).get(session_id)
            if s:
                s.status = status
                if status == RepairStatus.SUCCESS:
                    s.completed_at = datetime.now(timezone.utc)
                if not s.started_at and status not in (RepairStatus.PENDING,):
                    s.started_at = datetime.now(timezone.utc)
                db.commit()
            else:
                # sessions may not exist yet if pre-created; create placeholder
                pass
        finally:
            db.close()

    # ------------------------------------------------------------------- main

    def run(
        self,
        repo_url: str,
        title: str,
        description: str,
        session_id: str,
        use_memory: bool = True,
        baseline: str = "proposed",
        eval_result: EvaluationResult | None = None,
        memory_mode_override: bool | None = None,
    ) -> dict:
        self.llm.total_tokens = 0
        self._session_id = session_id
        self._event(session_id, "start", "Repair session started")

        try:
            return self._run_inner(
                repo_url, title, description, session_id,
                use_memory=use_memory, baseline=baseline,
                eval_result=eval_result,
                memory_mode_override=memory_mode_override,
            )
        except Exception as exc:  # noqa: BLE001
            self._event(session_id, "error", f"Repair error: {exc}")
            self._set_status(session_id, RepairStatus.FAILED)
            return {
                "status": "failed",
                "error": str(exc),
                "tokens_used": self.token_count,
                "session_id": session_id,
                "timeline": self._load_timeline(session_id),
            }

    def _run_inner(
        self,
        repo_url: str,
        title: str,
        description: str,
        session_id: str,
        use_memory: bool,
        baseline: str,
        eval_result: EvaluationResult | None,
        memory_mode_override=None,
    ) -> dict:
        start = time.time()
        self._set_status(session_id, RepairStatus.ANALYZING)

        # 1. Clone -----------------------------------------------------------
        self._event(session_id, "repository", f"Cloning {repo_url}")
        info = parse_github_url(repo_url)
        from ..repository.github import clone_repository

        meta = clone_repository(repo_url, self.settings)
        repo_dir = Path(meta["path"])
        self._event(
            session_id, "repository",
            f"Repository ready: {info['slug']} @ {meta.get('commit', 'local')} ({meta['size_mb']} MB)",
            {"slug": info["slug"], "commit": meta.get("commit")},
        )
        self.repo_path = repo_dir
        for gen in (self.patch_generator, self.test_generator, self.fault_localizer, self.issue_analyzer, self.failure_analyzer):
            gen._root = str(repo_dir)

        # register repository/issue in DB
        repo_id, issue_id = self._register_repo_issue(repo_url, info, repo_dir, title, description)

        # link session to repo + issue
        db_l = SessionLocal()
        try:
            s = db_l.query(RepairSession).get(session_id)
            if s:
                s.repository_id = repo_id
                s.issue_id = issue_id
                db_l.commit()
        finally:
            db_l.close()

        # 2. Analyze repository ----------------------------------------------
        self._event(session_id, "analysis", "Running AST repository analysis")
        analysis = analyze_repository(repo_dir)
        self._analysis = analysis
        n_fn = len(analysis.functions)
        n_cls = len(analysis.classes)
        self._event(
            session_id,
            "analysis",
            f"Indexed {len(analysis.py_files)} python files, {n_fn} functions, {n_cls} classes",
            {"files": len(analysis.py_files), "functions": n_fn, "classes": n_cls},
        )

        # 3. Graph -------------------------------------------------------------
        if baseline == "baseline1":
            self._graph = None
            self._event(session_id, "graph", "Baseline 1: graph disabled")
        else:
            self._event(session_id, "graph", "Building repository graph (ARISE-style)")
            graph = build_graph(analysis)
            self._graph = graph
            stats = graph.statistics()
            self._event(
                session_id,
                "graph",
                f"Graph built: {stats['n_nodes']} nodes, {stats['n_edges']} edges",
                stats,
            )

        # 4. Issue understanding ------------------------------------------------
        self._set_status(session_id, RepairStatus.ANALYZING)
        self._event(session_id, "issue", "Analyzing issue report")
        issue_analysis = self.issue_analyzer.analyze(title, description)
        self._event(
            session_id,
            "issue",
            f"Category: {issue_analysis.category} — {issue_analysis.summary}",
            {"category": issue_analysis.category, "keywords": issue_analysis.keywords},
        )
        issue_text = description or title

        # 5. Memory retrieval ----------------------------------------------------
        memory_context = ""
        memory_used = 0
        if use_memory and baseline != "baseline1":
            self._event(session_id, "memory", "Retrieving similar past repairs")
            hits = self.memory.retrieve(
                issue_text=issue_text,
                issue_category=issue_analysis.category,
                repository_url=info["url"],
                k=3,
            )
            memory_used = hits.count
            memory_context = hits.to_prompt()
            self._event(
                session_id,
                "memory",
                f"{hits.count} historical repair(s) retrieved"
                if hits.count else "No similar repair found in memory",
                {"count": hits.count, "scores": [e.get("score") for e in hits.entries]},
            )

        # 6. Fault localization ---------------------------------------------------
        self._set_status(session_id, RepairStatus.LOCALIZING)
        self._event(session_id, "localization", "Localizing suspicious code")

        if baseline == "baseline1":
            suspects = self._baseline1_localize(issue_text, analysis, issue_analysis.keywords)
        else:
            loc = self.fault_localizer.localize(analysis, graph, issue_text, issue_analysis.keywords)
            suspects = loc.suspects
            if loc.top:
                self._event(
                    session_id, "localization",
                    f"Top suspect: {loc.top['qualified']} (confidence {round(loc.top['confidence'], 2)})",
                    {"suspects": suspects},
                )

        self._event(
            session_id, "localization",
            f"{len(suspects)} suspicious location(s) identified",
        )

        # 7. Regression test generation ---------------------------------------------
        self._event(session_id, "tests", "Generating regression test")
        existing_hint = self._existing_test_hint(analysis)
        reg_test = self.test_generator.generate(
            issue_text,
            suspects,
            analysis,
            existing_test_hint=existing_hint,
        )
        reg_test_path = reg_test.path
        self._event(
            session_id, "tests",
            f"Regression test written to {reg_test_path}: {reg_test.test_names}",
            {"path": reg_test_path, "test_names": reg_test.test_names},
        )

        # 8. Repro on original code ---------------------------------------------------
        self._event(session_id, "tests", "Running regression test against original code")
        self._write_test_file(reg_test)
        original_run = self.executor.run_regression_on_original(repo_dir, reg_test_path)
        self._event(
            session_id, "tests",
            f"Original code: {len(original_run.failed)} failing / {original_run.passed} passing test(s)",
            {"failures": original_run.failed[:3] and [f.test_name for f in original_run.failed[:3]], "passed": original_run.passed},
        )
        reg_failed_original = len(original_run.failed) > 0

        # 9. Existing test suite discovery ---------------------------------------------
        existing_tests = discover_python_tests(repo_dir)
        existing_tests = [t for t in existing_tests if t != reg_test_path and "regression" not in t]
        self._event(session_id, "tests", f"Discovered {len(existing_tests)} existing test file(s)")

        # 10. Repair loop --------------------------------------------------------------
        self._set_status(session_id, RepairStatus.REPAIRING)
        max_attempts = self.settings.max_repair_attempts
        failure_history: list[str] = []
        attempt_results = []
        success = False
        last_patch = None
        reg_test_repaired = False
        attempts_used = 0
        final_report_data: dict = {}

        for attempt_no in range(1, max_attempts + 1):
            self._event(session_id, "repair", f"Beginning repair attempt {attempt_no}", {"attempt": attempt_no})
            attempt_start = time.time()

            # 10a. generate patch
            failure_context = ""
            if failure_history:
                failure_context = (
                    f"The previous attempt(s) failed with:\n" + "\n---\n".join(failure_history[-2:])
                )
            patch_result = self.patch_generator.generate(
                issue_text=issue_text,
                suspects=suspects,
                analysis=analysis,
                graph=self._graph if self._graph is not None else _NullGraph(),
                memory_context=memory_context,
                failure_context=failure_context,
            )
            last_patch = patch_result

            # guard: no edits produced
            edit_errors = self.patch_generator.validate_edits(patch_result.edits)
            if edit_errors or not patch_result.edits:
                msg = "No valid edits produced: " + "; ".join(edit_errors or ["empty edit list"])
                self._event(session_id, "repair", msg)
                failure_history.append(msg)
                attempts_used = attempt_no
                attempt_results.append({"attempt": attempt_no, "status": "invalid-edits", "reason": msg})
                continue

            patch_attempt_row = self._create_attempt_row(session_id, attempt_no, patch_result.strategy)

            # 10b. reset working tree, then apply edits (full-file writes), then
            #      derive the unified diff from git.
            utils.revert_patch(repo_dir, [f for f in _git_tracked_files(repo_dir)])
            try:
                diff = self._apply_edits(repo_dir, patch_result.edits)
            except RuntimeError as exc:
                self._event(session_id, "repair", f"Patch application failed: {exc}")
                failure_history.append(f"Patch did not apply cleanly:\n{exc}")
                self._update_attempt_failure(patch_attempt_row.id, str(exc))
                attempts_used = attempt_no
                attempt_results.append({"attempt": attempt_no, "status": "apply-error", "reason": str(exc)})
                self._set_attempt_done(patch_attempt_row, attempt_no, attempt_start)
                utils.revert_patch(repo_dir, [f for f in _git_tracked_files(repo_dir)])
                continue
            patch_result.diff = diff
            patch_result.files = utils.files_from_diff(diff)
            self._store_patch(patch_attempt_row.id, patch_result)

            # 10c. write regression test, run verification (regression + existing)
            self._write_test_file(reg_test)
            self._store_test(patch_attempt_row.id, reg_test_path, reg_test.content, "regression")

            self._event(session_id, "repair", f"Verifying patch (regression + {len(existing_tests)} existing file(s))")
            verif = self.executor.run_verification(repo_dir, reg_test_path, existing_tests)

            # persist test results
            self._store_test_results(patch_attempt_row.id, verif.as_dicts)

            reg_failures = [r for r in verif.results if r.outcome in ("failed", "error") and _is_regression(r, reg_test_path)]
            existing_failures = [r for r in verif.results if r.outcome in ("failed", "error") and not _is_regression(r, reg_test_path)]

            self._event(
                session_id, "repair",
                f"Attempt {attempt_no}: regression {'PASS' if not reg_failures else 'FAIL'} · "
                f"existing {len(existing_failures)} fail · {verif.passed} pass total",
                {
                    "regression_fail": [r.test_name for r in reg_failures[:5]],
                    "existing_fail": [r.test_name for r in existing_failures[:5]],
                    "passed": verif.passed,
                },
            )

            attempts_used = attempt_no
            attempt_results.append(
                {
                    "attempt": attempt_no,
                    "regression_fail": [r.test_name for r in reg_failures[:8]],
                    "existing_fail": [r.test_name for r in existing_failures[:8]],
                    "passed": verif.passed,
                    "failed": len(reg_failures) + len(existing_failures),
                    "strategy": patch_result.strategy,
                    "tokens_snapshot": self.token_count,
                }
            )

            if not reg_failures and not existing_failures:
                # 10d. SUCCESS
                success = True
                self._set_attempt_done(patch_attempt_row, attempt_no, attempt_start)

                self._event(
                    session_id, "repair",
                    f"Attempt {attempt_no} verified — all tests pass",
                    {"regression": reg_test.test_names, "existing_pass": verif.passed},
                )

                # mark attempt verified
                db = SessionLocal()
                try:
                    row = db.query(RepairAttempt).get(patch_attempt_row.id)
                    if row:
                        row.verified = True
                        row.regression_test_count = len(reg_test.test_names)
                        row.regression_passed = len(reg_failures) == 0 and 1 or 0
                        row.existing_test_count = verif.collected
                        row.existing_passed = verif.passed
                    db.commit()
                finally:
                    db.close()
                break

            # 10e. analyse failure
            self._event(session_id, "repair", f"Attempt {attempt_no} failed — analyzing failure")
            fail_analysis = self.failure_analyzer.analyze(
                regression_results=[r for r in verif.as_dicts if _is_regression(r, reg_test_path)],
                existing_results=[r for r in verif.as_dicts if not _is_regression(r, reg_test_path)],
                patch_strategy=patch_result.strategy,
                regression_test_names=reg_test.test_names,
            )
            self._event(
                session_id, "repair",
                f"Failure analysis: {fail_analysis.diagnosis}",
                {"fault_class": fail_analysis.fault_class, "root_causes": fail_analysis.likely_root_causes},
            )
            failure_history.append(
                f"Attempt {attempt_no} [{fail_analysis.fault_class}]: "
                f"{fail_analysis.diagnosis}\nRevision advice: {fail_analysis.revision_strategy}"
            )

            # 10f. if the regression test itself looks broken while existing
            #      tests all pass, regenerate the regression test and re-confirm
            #      reproduction against the original. Two triggers:
            #        (a) construction/import error in the test itself;
            #        (b) the test keeps failing across attempts even though every
            #            existing (oracle) test passes -> the test likely asserts
            #            the buggy behaviour or impossible semantics.
            reg_messages = " ".join((r.message or "") for r in reg_failures)
            test_construction_error = _looks_like_test_error(reg_messages)
            test_semantics_suspect = (
                not existing_failures
                and attempt_no >= 2
                and not test_construction_error
                and reg_failures
            )
            if not existing_failures and reg_failures and not reg_test_repaired and (
                test_construction_error or test_semantics_suspect
            ):
                if test_construction_error:
                    feedback = reg_messages[:2000]
                    self._event(
                        session_id, "repair",
                        "Regression test appears malformed (construction/import error); regenerating it",
                        {"messages": reg_messages[:400]},
                    )
                else:
                    feedback = (
                        "The previous regression test kept failing while ALL existing tests "
                        "pass, so the test itself is likely wrong — it may assert the buggy "
                        "behaviour or impossible semantics. Rewrite it to assert the CORRECT "
                        f"behaviour described in the bug report.\nFailing output:\n{reg_messages[:2000]}"
                    )
                    self._event(
                        session_id, "repair",
                        "Regression test disagrees with existing passing tests; regenerating it",
                        {"messages": reg_messages[:400]},
                    )
                utils.revert_patch(repo_dir, [f for f in _git_tracked_files(repo_dir)])
                reg_test = self.test_generator.generate(
                    issue_text,
                    suspects,
                    analysis,
                    existing_test_hint=existing_hint,
                    test_failure_context=feedback,
                )
                reg_test_path = reg_test.path
                reg_test_repaired = True
                self._write_test_file(reg_test)
                reg_rerun = self.executor.run_regression_on_original(repo_dir, reg_test_path)
                self._event(
                    session_id, "tests",
                    f"Regenerated regression test against original: {len(reg_rerun.failed)} failing / {reg_rerun.passed} passing",
                    {"test_names": reg_test.test_names},
                )
                self._set_attempt_done(patch_attempt_row, attempt_no, attempt_start)
                continue

            self._set_attempt_done(patch_attempt_row, attempt_no, attempt_start)

        # reset working tree at end
        utils.revert_patch(repo_dir, [f for f in _git_tracked_files(repo_dir)])

        # 11. store memory ------------------------------------------------------------
        status = "success" if success else "failed"
        if success and use_memory and baseline != "baseline1":
            try:
                record = MemoryRecord(
                    repository_url=info["url"],
                    issue_description=issue_text,
                    issue_category=issue_analysis.category,
                    affected_files=suspects and [s["file"] for s in suspects[:5]] or [],
                    affected_functions=[s["qualified"] for s in suspects[:5]] or [],
                    fault_pattern=issue_analysis.symptom,
                    generated_patch=last_patch.diff if last_patch else "",
                    generated_tests=[reg_test_path],
                    test_results={"regression": "pass", "existing_fail": 0},
                    num_attempts=attempts_used,
                    successful=True,
                    failure_reasons=[],
                    solution_pattern=(last_patch.strategy if last_patch else ""),
                    session_id=session_id,
                )
                entry = self.memory.store(record)
                self._event(session_id, "memory", f"Repair stored in memory ({entry.id})", {"memory_id": entry.id})
            except Exception as exc:  # noqa: BLE001
                self._event(session_id, "memory", f"Memory store failed: {exc}")

        # 12. report ------------------------------------------------------------------
        elapsed = time.time() - start
        total_existing_pass = 0
        total_existing_count = 0
        for a in attempt_results:
            total_existing_pass += a.get("passed", 0)
            total_existing_count += a.get("passed", 0) + a.get("failed", 0)

        timeline = self._load_timeline(session_id)
        report = self._build_report(
            session_id=session_id,
            repo_url=repo_url,
            title=title,
            description=description,
            success=success,
            attempts=attempts_used,
            elapsed=elapsed,
            memory_used=memory_used,
            suspects=suspects,
            timeline=timeline,
            reg_test=reg_test,
            attempt_results=attempt_results,
            existing_pass=total_existing_pass,
            existing_count=total_existing_count,
            graph_stats=self._graph.statistics() if self._graph else None,
        )
        self._event(session_id, "done", "Repair session complete" if success else "Repair session ended (not successful)")
        self._set_status(session_id, RepairStatus.SUCCESS if success else RepairStatus.FAILED)

        if eval_result is not None:
            db = SessionLocal()
            try:
                er = db.query(EvaluationResult).filter_by(id=eval_result.id).first()
                if er:
                    er.success = success
                    er.attempts = attempts_used
                    er.duration_seconds = round(elapsed, 2)
                    er.tokens_used = self.token_count
                    er.regression_failures = len(attempt_results)
                    db.commit()
            except Exception:  # noqa: BLE001
                db.rollback()
            finally:
                db.close()

        return {
            "status": status,
            "success": success,
            "attempts": attempts_used,
            "duration_seconds": round(elapsed, 2),
            "tokens_used": self.token_count,
            "memory_used": memory_used,
            "report": report,
            "session_id": session_id,
        }

    # -------------------------------------------------------------- baselines

    def _baseline1_localize(self, issue_text: str, analysis, keywords: list[str]) -> list[dict]:
        """Baseline 1: no graph, no memory — plain keyword-matched code + LLM."""
        from ..agents.fault_localizer import FaultLocalizer

        # keyword -> file matching only
        matched_files: set[str] = set()
        for kw in keywords:
            low = kw.lower()
            for fn in analysis.functions.values():
                if low in fn.file.lower() or low in fn.qualified.lower():
                    matched_files.add(fn.file)
        if not matched_files:
            matched_files.update(f for f in analysis.modules)
        rows = []
        for file in list(matched_files)[:15]:
            symbols = [k for k, v in analysis.functions.items() if v.file == file]
            rows.append(f"- {file}: {symbols[:10]}")
        loc = FaultLocalizer(self.llm)
        suspects = loc.localize(analysis, _NullGraph(), issue_text, keywords)
        return suspects.suspects

    # ------------------------------------------------------------- persistence

    def _register_repo_issue(self, repo_url: str, info: dict, repo_dir: Path, title: str, description: str) -> tuple[str, str]:
        db = SessionLocal()
        try:
            from ..models import Project

            project = db.query(Project).filter_by(name=info["owner"]).first()
            if not project:
                project = Project(name=info["owner"], description=f"Research project for {info['owner']}")
                db.add(project)
                db.commit()
            repo = (
                db.query(Repository)
                .filter_by(url=info["url"], project_id=project.id)
                .first()
            )
            if not repo:
                repo = Repository(project_id=project.id, url=info["url"], local_path=str(repo_dir))
                db.add(repo)
                db.commit()
            issue = Issue(
                repository_id=repo.id,
                title=title,
                description=description,
                source="manual",
            )
            db.add(issue)
            db.commit()
            return repo.id, issue.id
        finally:
            db.close()

    def _existing_test_hint(self, analysis) -> str:
        """Return a snippet from an existing test file for construction style."""
        for t in analysis.test_files[:1]:
            try:
                text = t.read_text(encoding="utf-8", errors="replace")
                lines = text.splitlines()
                # show imports + the first test function
                head = [l for l in lines if not l.startswith(" ")][:24]
                return "\n".join(head)
            except OSError:
                continue
        return ""

    def _write_test_file(self, reg_test) -> None:
        target = self.repo_path / reg_test.path.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(reg_test.content, encoding="utf-8")

    def _apply_edits(self, repo_dir: Path, edits) -> str:
        """Write full-file edits into the working copy, then produce a diff.

        Returns the unified diff of the changes. Raises RuntimeError on a
        write failure. Used by the repair loop to always get a well-formed diff.
        The working copy is made a git worktree on demand (baseline commit) so
        locally-copied repos without a .git directory still produce diffs.
        """
        import subprocess as _sp

        if not (repo_dir / ".git").exists():
            for cmd in (
                ["git", "init", "-q"],
                ["git", "add", "-A"],
                ["git", "-c", "user.email=swe@adaptive", "-c", "user.name=swe", "commit", "-q", "-m", "baseline"],
            ):
                proc = _sp.run(cmd, cwd=str(repo_dir), capture_output=True, text=True)
                if cmd[0] == "git" and cmd[1] == "commit" and proc.returncode != 0:
                    raise RuntimeError(f"cannot baseline working copy: {proc.stderr.strip()}")

        for e in edits:
            target = repo_dir / e.path.lstrip("/")
            if not str(target.resolve()).startswith(str(repo_dir.resolve())):
                raise RuntimeError(f"edit path escapes repository: {e.path}")
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                target.write_text(e.new_content, encoding="utf-8")
            except OSError as exc:
                raise RuntimeError(f"cannot write {e.path}: {exc}") from exc

        _sp.run(["git", "add", "-A"], cwd=str(repo_dir), capture_output=True, text=True)
        proc = _sp.run(
            ["git", "diff", "--cached", "--", *[e.path for e in edits]],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
        )
        diff = proc.stdout or ""
        if not diff.strip():
            raise RuntimeError("edits produced no changes vs baseline")
        return diff

    def _create_attempt_row(self, session_id: str, attempt_no: int, strategy: str) -> RepairAttempt:
        db = SessionLocal()
        try:
            row = RepairAttempt(session_id=session_id, attempt_number=attempt_no, strategy_note=strategy)
            db.add(row)
            db.commit()
            db.refresh(row)
            return row
        finally:
            db.close()

    def _set_attempt_done(self, row: RepairAttempt, attempt_no: int, started: float) -> None:
        db = SessionLocal()
        try:
            r = db.query(RepairAttempt).get(row.id)
            if r:
                r.duration_seconds = round(time.time() - started, 2)
                r.tokens_used = self.token_count
                r.completed_at = datetime.now(timezone.utc)
            db.commit()
        finally:
            db.close()

    def _update_attempt_failure(self, attempt_id: str, reason: str) -> None:
        db = SessionLocal()
        try:
            r = db.query(RepairAttempt).get(attempt_id)
            if r:
                r.failure_reason = reason
            db.commit()
        finally:
            db.close()

    def _store_patch(self, attempt_id: str, patch_result) -> None:
        db = SessionLocal()
        try:
            db.add(
                Patch(
                    attempt_id=attempt_id,
                    content=patch_result.diff,
                    applied=False,
                    applied_files=patch_result.files,
                    description=patch_result.strategy,
                )
            )
            db.commit()
        finally:
            db.close()

    def _store_test(self, attempt_id: str, path: str, content: str, role: str) -> None:
        db = SessionLocal()
        try:
            db.add(TestFile(attempt_id=attempt_id, path=path, content=content, role=role))
            db.commit()
        finally:
            db.close()

    def _store_test_results(self, attempt_id: str, results: list[dict]) -> None:
        db = SessionLocal()
        try:
            for r in results:
                db.add(
                    TestResult(
                        attempt_id=attempt_id,
                        test_name=r["test"],
                        outcome=r["outcome"],
                        duration_ms=float(r.get("duration_ms", 0) or 0),
                        message=r.get("message", ""),
                        role=_role_from_test_name(r["test"]),
                    )
                )
            db.commit()
        finally:
            db.close()

    def _load_timeline(self, session_id: str) -> list[dict]:
        db = SessionLocal()
        try:
            rows = (
                db.query(TimelineEvent)
                .filter_by(session_id=session_id)
                .order_by(TimelineEvent.at.asc())
                .all()
            )
            return [
                {
                    "step": r.step,
                    "message": r.message,
                    "detail": r.detail,
                    "at": r.at.strftime("%H:%M:%S") if r.at else "",
                }
                for r in rows
            ]
        finally:
            db.close()

    def _build_report(self, **kw) -> dict:
        return kw


# ---------------------------------------------------------------------------

def _is_regression(r, reg_path: str) -> bool:
    if isinstance(r, dict):
        name = r.get("test", "")
    else:
        name = getattr(r, "test_name", "") or ""
    return reg_path.split("/")[-1].replace(".py", "") in name or "regression" in name


def _role_from_test_name(name: str) -> str:
    return "regression" if "regression" in name else "existing"


def _looks_like_test_error(messages: str) -> bool:
    """Heuristic: does the failure message indicate a broken test harness
    (construction/attribute/import errors) rather than a wrong assertion?"""
    low = messages.lower()
    markers = [
        "typeerror", "missing 1 required positional argument",
        "missing 2 required positional arguments",
        "attributeerror", "importerror", "modulenotfounderror",
        "valueerror: not enough values", "unexpected keyword",
        "takes 0 positional arguments", "cannot import",
        "nameerror: name", "fixture '", "no such file or directory",
    ]
    return any(m in low for m in markers)


def _git_tracked_files(repo_dir: Path) -> list[str]:
    import subprocess

    try:
        out = subprocess.run(
            ["git", "ls-files"],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
        )
        return out.stdout.splitlines()
    except Exception:  # noqa: BLE001
        return []


class _NullGraph:
    """Minimal stand-in so baseline1 can share the patch generator path."""

    def callers(self, _q: str) -> list[str]:
        return []

    def callees(self, _q: str) -> list[str]:
        return []


def _repo_root(slug: str) -> Path:
    return REPOS_DIR / slug