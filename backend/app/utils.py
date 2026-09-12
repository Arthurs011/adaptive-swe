"""Shared utilities: unified diff parsing / applying, output helpers."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

DIFF_FILE_RE = re.compile(r"^\+\+\+\s+(?:b/)?(.*)$", re.MULTILINE)


def files_from_diff(diff: str) -> list[str]:
    """Extract file paths from a unified diff header."""
    files: list[str] = []
    for m in re.finditer(r"^diff --git a/(.+?) b/(.+)$", diff, re.MULTILINE):
        files.append(m.group(2))
    for hunk_start in re.finditer(r"^\+\+\+\s+(?:b/)?(.+)$", diff, re.MULTILINE):
        p = hunk_start.group(1)
        if p != "/dev/null" and p not in files and not p.startswith("a/"):
            files.append(p)
    return files


def apply_patch(repo_root: Path, diff: str, preferred: list[str] | None = None) -> list[str]:
    """Apply a unified diff inside repo_root with `git apply`.

    Returns list of files modified. Raises on failure.
    """
    diff = normalize_diff(diff)
    diff = correct_diff_paths(repo_root, diff, preferred)
    if not diff.strip():
        raise ValueError("empty diff")
    proc = subprocess.run(
        ["git", "apply", "--whitespace=nowarn", "-"],
        input=diff,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        env={**__import__("os").environ, "GIT_WORK_TREE": str(repo_root), "GIT_DIR": str(repo_root / ".git")},
    )
    if proc.returncode != 0:
        # fallback: try reverse-applying a /dev/null-removal-style diff via patch
        from subprocess import run as _run

        p2 = _run(
            ["patch", "-p1", "-f", "--batch"],
            input=diff,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if p2.returncode != 0:
            raise RuntimeError(f"git apply failed:\n{proc.stderr}\n---\npatch fallback:\n{p2.stderr}")
    return files_from_diff(diff)


def normalize_diff(diff: str) -> str:
    """Clean LLM-produced diffs: strip code fences, recover newlines, and drop
    obviously wrong header noise. Path correctness is handled by
    correct_diff_paths."""
    diff = diff.replace("\\n", "\n")
    lines = diff.splitlines()

    cleaned: list[str] = []
    in_fence = False
    for ln in lines:
        stripped = ln.strip()
        if stripped in {"```", "```diff", "```python", "```text", "```patch"}:
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if stripped in {"<diff>", "</diff>"}:
            continue
        if stripped.startswith("```"):
            continue
        cleaned.append(ln)

    # common leading indentation removal
    body = [l for l in cleaned if l.strip()]
    if body:
        indents = [len(l) - len(l.lstrip()) for l in body if l.startswith(" ")]
        if indents and min(indents) > 0:
            pad = min(indents)
            cleaned = [l[pad:] if l.startswith(" ") else l for l in cleaned]

    # keep only meaningful lines; drop 'index ...' noise differences are fine
    out = []
    for ln in cleaned:
        out.append(ln)
    joined = "\n".join(out).strip("\n") + "\n"
    return joined


def correct_diff_paths(repo_root: Path, diff: str, preferred: list[str] | None = None) -> str:
    """Rewrite `a/` / `b/` paths in a diff to paths that exist in the repo.

    The LLM sometimes invents prefixes (e.g. src/) or wrong nesting. We map
    every diffed path to a unique existing repo file by basename (preferring
    names in `preferred`), and rewrite the headers. If no safe mapping exists
    the original diff is returned unchanged.
    """
    preferred = preferred or []
    prefs = [p.replace("\\", "/") for p in preferred]

    existing = {
        str(p.relative_to(repo_root)).replace("\\", "/")
        for p in repo_root.rglob("*")
        if p.is_file() and not any(x in p.parts for x in {"__pycache__", ".git", ".venv", "venv", "node_modules"})
    }

    def _map(path: str) -> str | None:
        base = path.split("/")[-1]
        candidates = [e for e in existing if e.split("/")[-1] == base]
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        for pref in prefs:
            if base == pref.split("/")[-1]:
                return pref
        for c in candidates:
            if any(p2.split("/")[-1] == base for p2 in prefs):
                pass
        return candidates[0]

    def _rewrite_path(p: str, mapped: str) -> str:
        if p.startswith("a/"):
            p = p[2:]
        return p

    out: list[str] = []
    for ln in diff.splitlines():
        if ln.startswith("diff --git "):
            parts = ln.split()
            if len(parts) >= 4:
                old = parts[2][2:]
                new = parts[3][2:]
                m_old = _map(old)
                m_new = _map(new)
                if m_new:
                    ln = f"diff --git a/{m_old or new} b/{m_new}"
                elif m_old:
                    ln = f"diff --git a/{m_old} b/{new}"
        elif ln.startswith("--- ") and ln != "---":
            p = ln[4:]
            if p.startswith("a/"):
                p = p[2:]
            m = _map(p)
            if m:
                ln = f"--- a/{m}"
        elif ln.startswith("+++ ") and ln != "+++":
            p = ln[4:]
            if p.startswith("b/"):
                p = p[2:]
            m = _map(p)
            if m:
                ln = f"+++ b/{m}"
        out.append(ln)
    return "\n".join(out) + "\n"


def revert_patch(repo_root: Path, files: list[str]) -> None:
    """Restore modified files to HEAD state."""
    if not files:
        return
    subprocess.run(
        ["git", "checkout", "--", *files],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )


def format_diff_stats(diff: str) -> str:
    add = sum(1 for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++"))
    rm = sum(1 for l in diff.splitlines() if l.startswith("-") and not l.startswith("---"))
    return f"{len(files_from_diff(diff))} file(s), +{add} -{rm}"