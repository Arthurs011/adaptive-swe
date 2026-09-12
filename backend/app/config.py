"""Application configuration loaded from environment / .env file."""

from __future__ import annotations

from pathlib import Path
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_ROOT.parent
STORAGE_DIR = BACKEND_ROOT / "storage"
REPOS_DIR = STORAGE_DIR / "repos"
RESULTS_DIR = STORAGE_DIR / "results"
REPO_WORKDIR = Path("/workspace/repo")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_embeddings_model: str = "text-embedding-3-small"

    # Database
    database_url: str = "sqlite:///./storage/adaptive_swe.db"

    # Sandbox
    sandbox_mode: str = "auto"  # auto | docker | local
    sandbox_timeout_seconds: int = 300
    sandbox_memory_limit_mb: int = 2048
    sandbox_cpu_limit: float = 1.0
    sandbox_network_disabled: bool = True
    docker_image: str = "python:3.11-slim"

    # Repair loop
    max_repair_attempts: int = 5
    max_repo_size_mb: int = 200

    def ensure_dirs(self) -> None:
        STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        REPOS_DIR.mkdir(parents=True, exist_ok=True)
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s