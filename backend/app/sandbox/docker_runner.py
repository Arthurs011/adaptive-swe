"""Sandbox runners.

Two backends, selected by config:
- docker : run inside a container with CPU/memory/network limits.
- local  : run in a per-repository virtualenv via subprocess with timeout and
           resource limits (used when Docker is unavailable).

Both perform REAL execution and return structured results.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..config import get_settings, REPOS_DIR


@dataclass
class SandboxResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    runner: str = "local"
    message: str = ""
    junit_xml: str = ""


def _docker_available() -> bool:
    try:
        import docker  # noqa: F401

        client = docker.from_env()
        client.ping()
        return True
    except Exception:  # noqa: BLE001
        return False


class SandboxRunner:
    def __init__(self, settings=None) -> None:
        self.settings = settings or get_settings()
        self.runner = self._choose_runner()
        if self.runner == "docker":
            import docker

            self.docker = docker.from_env()

    def _choose_runner(self) -> str:
        mode = self.settings.sandbox_mode
        if mode == "docker":
            if not _docker_available():
                raise RuntimeError("SANDBOX_MODE=docker but no Docker engine is reachable")
            return "docker"
        if mode == "local":
            return "local"
        return "docker" if _docker_available() else "local"

    # -- public API -----------------------------------------------------------

    def run_pytest(self, repo_root: Path, test_paths: list[str], pyproject_dir: Path) -> SandboxResult:
        """Run pytest against repo_root inside the sandbox."""
        repo_root = Path(repo_root)
        if self.runner == "docker":
            return self._run_docker(repo_root, test_paths, pyproject_dir)
        return self._run_local(repo_root, test_paths)

    # -- local runner -----------------------------------------------------------

    def _venv(self, repo_root: Path) -> Path:
        venv = REPOS_DIR / ".deps" / repo_root.name / "venv"
        marker = venv / "bin" / "python"
        if marker.exists() and _venv_usable(marker):
            return venv
        # stale or broken venv: rebuild it
        venv.parent.mkdir(parents=True, exist_ok=True)
        import shutil as _sh

        _sh.rmtree(venv, ignore_errors=True)
        if _uv_available():
            _run_quiet(["uv", "venv", str(venv)])
            _run_quiet(
                ["uv", "pip", "install", "--python", str(venv / "bin" / "python"),
                 "-q", "pytest", "--no-cache-dir"]
            )
        else:
            import venv as _venv

            _venv.EnvBuilder(with_pip=True).create(str(venv))
            self._pip(venv, "install", "-q", "pytest", "--no-cache-dir")
        return venv

    def _pip(self, venv: Path, *args: str) -> None:
        subprocess.run(
            [str(venv / "bin" / "python"), "-m", "pip", *args],
            capture_output=True,
            text=True,
            timeout=360,
        )

    def _run_local(self, repo_root: Path, test_paths: list[str]) -> SandboxResult:
        start = time.time()
        venv = self._venv(repo_root)

        # install the repository as editable if it declares packaging; otherwise
        # rely on PYTHONPATH pointing at the repo root.
        has_pkg = (repo_root / "setup.py").exists() or (repo_root / "pyproject.toml").exists()
        if has_pkg and not (repo_root / "pyproject.toml").exists():
            try:
                self._pip(venv, "install", "-q", "-e", str(repo_root), "--no-cache-dir")
            except Exception:  # noqa: BLE001
                pass

        tmp = tempfile.mkdtemp(prefix="adapted-swe-")
        junit = os.path.join(tmp, "junit.xml")
        cov = os.path.join(tmp, "coverage.xml")
        env = {
            **os.environ,
            "PYTHONPATH": str(repo_root) + os.pathsep + os.environ.get("PYTHONPATH", ""),
            "COVERAGE_FILE": os.path.join(tmp, "cov"),
            "JUNIT_XML": junit,
            "COVERAGE_XML": cov,
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        cmd = [
            str(venv / "bin" / "python"), "-m", "pytest",
            *test_paths,
            "--junitxml=" + junit,
            "-p", "no:cacheprovider", "-q", "--tb=short",
            "-p", "no:cov",
        ]
        cfg = self.settings
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(repo_root),
                env=env,
                capture_output=True,
                text=True,
                timeout=cfg.sandbox_timeout_seconds,
            )
            timed_out = False
        except subprocess.TimeoutExpired as exc:
            proc = exc
            timed_out = True

        elapsed = time.time() - start
        junit_text = ""
        try:
            junit_text = Path(junit).read_text(encoding="utf-8", errors="replace")
        except OSError:
            junit_text = ""
        shutil.rmtree(tmp, ignore_errors=True)
        return SandboxResult(
            returncode=getattr(proc, "returncode", -1),
            stdout=(getattr(proc, "stdout", "") or ""),
            stderr=(getattr(proc, "stderr", "") or ""),
            timed_out=timed_out,
            runner="local",
            message=f"local venv run in {elapsed:.1f}s (timeout={cfg.sandbox_timeout_seconds}s)",
            junit_xml=junit_text,
        )

    # -- docker runner -----------------------------------------------------------

    def _run_docker(self, repo_root: Path, test_paths: list[str], pyproject_dir: Path) -> SandboxResult:
        import tempfile as _tf

        cfg = self.settings
        junit_dir = _tf.mkdtemp(prefix="adapted-junit-")
        quoted = " ".join(shlex_quote(t) for t in test_paths)
        inner = f"/workspace/repo"

        script = f"""
set -o pipefail
cd {inner} || exit 90
python -m pip install -q pytest 2>/dev/null
if [ -f pyproject.toml ] || [ -f setup.py ]; then
  python -m pip install -q -e . --no-cache-dir 2>/dev/null || true
fi
python -m pytest {quoted} --junitxml=/workspace/junit.xml -p no:cacheprovider -q --tb=short
exit $?
"""
        cmd = ["/bin/sh", "-c", script]
        container = None
        try:
            container = self.docker.containers.run(
                cfg.docker_image,
                cmd,
                working_dir="/workspace",
                detach=True,
                mem_limit=f"{cfg.sandbox_memory_limit_mb}m",
                nano_cpus=None if platform.system() == "Darwin" else int(cfg.sandbox_cpu_limit * 1e9),
                network_disabled=cfg.sandbox_network_disabled,
                volumes={
                    str(repo_root): {"bind": inner, "mode": "rw"},
                    junit_dir: {"bind": "/workspace", "mode": "rw"},
                },
                environment={
                    "PYTHONPATH": inner,
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                },
                stderr=True,
            )
            res = container.wait(timeout=cfg.sandbox_timeout_seconds)
            returncode = res.get("StatusCode", -1)
            logs = container.logs(stdout=True, stderr=True).decode(errors="replace")
            container.remove(force=True)
            container = None

            junit = Path(junit_dir) / "junit.xml"
            stdout = logs
            junit_xml = ""
            if junit.exists():
                junit_xml = junit.read_text(errors="replace")
            return SandboxResult(
                returncode=returncode,
                stdout=stdout,
                stderr="",
                timed_out=False,
                runner="docker",
                message="docker execution",
                junit_xml=junit_xml,
            )
        except Exception as exc:  # noqa: BLE001
            if container is not None:
                try:
                    container.remove(force=True)
                except Exception:  # noqa: BLE001
                    pass
            raise
        finally:
            shutil.rmtree(junit_dir, ignore_errors=True)


def shlex_quote(s: str) -> str:
    import shlex

    return shlex.quote(s)


def _uv_available() -> bool:
    import shutil

    return shutil.which("uv") is not None


def _venv_usable(python: Path) -> bool:
    try:
        proc = subprocess.run(
            [str(python), "-c", "import sys; print(sys.version)"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return proc.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _run_quiet(args: list[str]) -> None:
    subprocess.run(args, capture_output=True, text=True, timeout=360, check=False)


__all__ = ["SandboxRunner", "SandboxResult"]