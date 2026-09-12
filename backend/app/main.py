"""Adaptive-SWE backend entry point (FastAPI)."""

from __future__ import annotations

import sys
from pathlib import Path

_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .database import init_db
from .api.routes import router

settings = get_settings()

app = FastAPI(
    title="Adaptive Self-Healing Software Engineer",
    description=(
        "Autonomous bug repair with repository-level reasoning, "
        "persistent repair memory, and adaptive revision."
    ),
    version="0.1.0",
    docs_url="/docs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    settings.ensure_dirs()
    init_db()


app.include_router(router)


@app.get("/")
def root():
    return {
        "name": "Adaptive Self-Healing Software Engineer",
        "status": "running",
        "docs": "/docs",
        "api": "/api",
    }


@app.get("/health")
def health():
    return {"status": "ok"}