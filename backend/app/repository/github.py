"""GitHub repository cloning and metadata helpers."""

from __future__ import annotations

import shutil
from pathlib import Path
from urllib.parse import urlparse

from git import Repo

from ..config import REPOS_DIR, Settings, get_settings


def parse_github_url(url: str) -> dict:
    """Normalise a github url into owner/name/slug, or accept a local path."""
    url = url.strip()

    local = Path(url)
    if local.exists() and (local / ".git").exists():
        from ..config import STORAGE_DIR

        slug = f"local-{local.name}"
        return {
            "owner": "local",
            "name": local.name,
            "slug": slug,
            "url": url,
            "local_path": str(local),
            "scheme": "local",
        }
    if url.startswith("local://"):
        p = url.split("local://", 1)[1]
        return {
            "owner": "local",
            "name": Path(p).name,
            "slug": f"local-{Path(p).name}",
            "url": url,
            "local_path": p,
            "scheme": "local",
        }

    if url.startswith("git@"):
        # git@github.com:owner/repo.git
        url = "https://" + url.replace(":", "/").replace("git@", "", 1).replace("git", "", 1)
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2 or "github.com" not in (parsed.netloc or ""):
        raise ValueError(f"Not a valid GitHub URL or local path: {url}")
    owner, name = parts[0], parts[1]
    name = name.removesuffix(".git")
    return {
        "owner": owner,
        "name": name,
        "slug": f"{owner}/{name}",
        "url": f"https://github.com/{owner}/{name}",
        "scheme": "github",
    }


def clone_repository(url: str, settings: Settings | None = None) -> dict:
    """Clone (or fetch) a repository into the local storage dir.

    For local paths, copies the repository into storage so all downstream
    mutation happens on the copy (never on the user's checkout).
    """
    settings = settings or get_settings()
    info = parse_github_url(url)
    repo_dir = REPOS_DIR / info["slug"]
    if repo_dir.exists():
        shutil.rmtree(repo_dir)
    repo_dir.parent.mkdir(parents=True, exist_ok=True)

    if info.get("scheme") == "local":
        src = Path(info["local_path"])
        _copy_local_repo(src, repo_dir)
        from git import Repo as GitRepo
        try:
            commit = GitRepo(str(repo_dir)).head.commit.hexsha
        except Exception:  # noqa: BLE001
            commit = None
        return {
            "url": url,
            "slug": info["slug"],
            "path": str(repo_dir),
            "branch": "local",
            "commit": commit,
            "size_mb": _dir_size_mb(repo_dir),
        }

    repo = Repo.clone_from(url, str(repo_dir))
    commit = repo.head.commit.hexsha
    return {
        "url": url,
        "slug": info["slug"],
        "path": str(repo_dir),
        "branch": repo.active_branch.name,
        "commit": commit,
        "size_mb": _dir_size_mb(repo_dir),
    }


def _copy_local_repo(src: Path, dst: Path) -> None:
    """Copy a local git repo, preserving the working tree and .git."""
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))


def _dir_size_mb(path: Path) -> float:
    total = 0
    for f in path.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                pass
    return round(total / (1024 * 1024), 2)