# Adaptive Self-Healing Software Engineer

A research prototype for autonomous software bug repair with **persistent repair memory** and **ARISE-style repository graphs**. When the same (or similar) bug class reoccurs, the system remembers what worked and applies that knowledge to adapt its patching strategy.

## Research Question

> *Does persistent repository-specific repair memory + structural repository reasoning improve autonomous software repair compared to code-only repair?*

The experiment compares:

| Mode | Graph | Persistent Memory | Iterative Repair |
|------|:-----:|:-----------------:|:----------------:|
| baseline1 (plain) | ✗ | ✗ | ✓ |
| baseline2 (ARISE-style) | ✓ | ✗ | ✓ |
| **proposed** | ✓ | ✓ | ✓ |

Both baseline2 and proposed use the ARISE-style data/control-flow graph, iterative localization → patch → test loops, and failure-guided revision. Only `proposed` enables persistent memory, so the A/B comparison controls graph/loop and isolates memory as the only difference.

---

## Architecture

```
┌───────────────────────────────────────────────────────┐
│  Frontend (Next.js)                                   │
│  ┌────────────┬────────────┬────────────┬───────────┐ │
│  │ Dashboard  │ Workspace  │ Explorer   │ Memory    │ │
│  │ (metrics)  │ (timeline, │ (browse,   │ (learned  │ │
│  │            │  attempts) │  graph,    │  repairs) │ │
│  │            │            │  Monaco)   │           │ │
│  └────────────┴────────────┴────────────┴───────────┘ │
└───────────────────────┬───────────────────────────────┘
                        │ /api/* proxy → :8000
┌───────────────────────┴───────────────────────────────┐
│  Backend (FastAPI)                                     │
│                                                        │
│  RepairAgent (orchestrator)                            │
│    ├─ RepositoryAnalyzer (AST index)                   │
│    ├─ RepositoryGraph (ARISE-style, NetworkX)          │
│    ├─ IssueAnalyzer → FaultLocalizer → PatchGenerator  │
│    ├─ TestGenerator → SandboxRunner (Docker / local)   │
│    ├─ FailureAnalyzer → adaptive retry loop            │
│    └─ RepairMemory (vector retrieval + embedding)      │
│                                                        │
│  Evaluation: BenchmarkIssue → run_benchmark → metrics  │
│  DB: SQLAlchemy (PostgreSQL / SQLite)                  │
└───────────────────────────────────────────────────────┘
```

### Key ideas

1. **ARISE-style graph** — AST-extracted call/read/write relations give the LLM precise code neighbourhood for localization and patch generation.
2. **Persistent repair memory** — Each completed repair is stored with repo URL, affected functions, patch text, test text, and an embedding. On future issues in the same repo, similar memories are surfaced via cosine similarity.
3. **Adaptive revision loop** — If regression tests still fail, the system *also* regenerates tests that look broken (construction/import errors) and revised patches, looping up to 4 attempts with full feedback.
4. **Sandboxed execution** — Tests run inside Docker (or an isolated uv venv in local mode) — never on the host.
5. **Baselines** — baseline1 skips the graph (keyword file matching + LLM), baseline2 has the graph/loop but no persistent memory, proposed adds memory. Each is an honest, single config toggle.

---

## Quick start

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# .env
cat <<EOF > ../.env
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL=openai/gpt-4o-mini
LLM_API_KEY=sk-or-v1-YOUR-KEY-HERE
DATABASE_URL=sqlite:///./storage/adaptive_swe.db
EOF

# start
uvicorn app.main:app --port 8000
```

The first run creates `storage/adaptive_swe.db`.

### Frontend

```bash
cd frontend
npm install
npm run dev        # http://localhost:3000
```

The dev server proxies `/api/*` to `localhost:8000` automatically.

### Run a repair

```bash
curl -X POST http://localhost:8000/api/repair \
  -H 'Content-Type: application/json' \
  -d '{
    "repo_url": "git@github.com:your-user/your-python-repo.git",
    "title": "Bug description",
    "description": "Detailed bug report text",
    "baseline": "proposed",
    "use_memory": true
  }'

# then poll:
curl http://localhost:8000/api/repair/{session_id}
```

Or use the **New Repair** page in the dashboard.

---

## Running the key experiment (A/B comparison)

```bash
# Experiment A: same repo set, memory OFF
curl -X POST http://localhost:8000/api/evaluate \
  -H 'Content-Type: application/json' \
  -d '{"baseline": "proposed", "use_memory": false, "limit": 4}'

# Experiment B: same repo set, memory ON
curl -X POST http://localhost:8000/api/evaluate \
  -H 'Content-Type: application/json' \
  -d '{"baseline": "proposed", "use_memory": true, "limit": 4}'

# View the comparison
curl http://localhost:8000/api/comparison
```

The comparison endpoint returns deltas for: success_rate, pass@1, avg_attempts, regression_failures, avg_tokens, avg_duration, plus a conclusion string.

---

## Docker (optional)

```bash
docker compose up --build
```

Starts the backend (port 8000), frontend (port 3000), and optionally PostgreSQL. When no Docker engine is available, the sandbox falls back to local venv mode automatically.

---

## Frontend pages

| Route | Purpose |
|-------|---------|
| `/` | Dashboard — live metrics, recent issues, quick start |
| `/repair/new` | Start a new repair job (form) |
| `/repair/{id}` | Repair workspace — live timeline, attempt cards, patch diffs, test results |
| `/explorer/{id}` | Code explorer — file tree, Monaco editor, ARISE graph visualization, symbol index |
| `/memory` | Persistent repair memory viewer — browse/delete learned repairs |
| `/evaluations` | Benchmark runs and A/B comparison (memory on vs off) |

---

## Benchmark repos

Located in `benchmark_repos/` — ten Python repos with deliberately introduced bugs
(each has at least one existing oracle test that fails on the buggy code):

| Repo | Bug | Type |
|------|-----|------|
| `discount-calc` | Negative quantity accepted, produces nonsensical discount | Missing validation |
| `csv-import` | `CSVParser.parse()` crashes with `IndexError` on empty CSV | Null/empty handling |
| `string-utils` | `truncate()` truncates short strings (`'hi'` → `'h...'`) | Missing guard |
| `task-board` | `summarize()` returns total count for every status, not per-status count | Wrong computation |
| `json-flattener` | `flatten()` never descends into lists (`{'a': [1, {'b': 2}]}` stays nested) | Incomplete recursion |
| `rate-limiter` | Window expiry resets the count but never advances the window → limiter goes unlimited | State not advanced |
| `invoice-total` | Items priced under $1.00 escape the tax rate | Wrong guard |
| `text-stats` | `count_lines()` counts a phantom trailing line on text ending with `\n` | Off-by-one |
| `search-index` | `tokenize()` keeps punctuation and case (`'Hello, world!'` → `['Hello,', 'world!']`) | Tokenization |
| `url-toolkit` | `is_valid_url('notaurl://thing')` returns True (no host validation) | Validation |

---

## Tech stack

- **Backend**: Python 3.12 + FastAPI + SQLAlchemy + NetworkX + uv
- **Frontend**: Next.js 15 + TypeScript + Tailwind CSS + shadcn/ui + Monaco Editor + Recharts
- **LLM**: OpenAI-compatible API (OpenRouter tested)
- **Sandbox**: Docker (preferred) or local uv venv per repository
- **DB**: PostgreSQL (prod) or SQLite (dev)

---

## Project structure

```
adaptive-swe/
├── .env
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app
│   │   ├── config.py            # Settings
│   │   ├── database.py          # SQLAlchemy engine
│   │   ├── models.py            # ORM models
│   │   ├── utils.py             # Diff helpers
│   │   ├── api/routes.py        # All API endpoints
│   │   ├── agents/              # LLM agents (orchestrator, localizer, patcher, tester, etc.)
│   │   ├── repository/          # Cloning, AST analysis, graph
│   │   ├── sandbox/             # Docker/local test execution
│   │   ├── memory/              # Embeddings, retrieval, persistence
│   │   └── evaluation/          # Metrics, benchmark runner
│   ├── storage/                 # SQLite DB (gitignored)
│   └── requirements.txt
├── frontend/
│   ├── src/app/                 # Next.js App Router pages
│   ├── src/components/          # Shared components (Layout, etc.)
│   ├── src/lib/api.ts           # API client
│   └── package.json
├── benchmark_repos/             # Test repos with known bugs
└── README.md
```

---

## Configuration

| Key | Default | Description |
|-----|---------|-------------|
| `LLM_BASE_URL` | `https://openrouter.ai/api/v1` | OpenAI-compatible API base |
| `LLM_MODEL` | `openai/gpt-4o-mini` | Model to use |
| `LLM_API_KEY` | — | Your API key (never commit) |
| `DATABASE_URL` | `sqlite:///./storage/adaptive_swe.db` | DB connection string |
| `DOCKER_IMAGE` | `python:3.11-slim` | Sandbox Docker image |
| `SANDBOX_MODE` | `docker` | `docker` or `local` (auto-fallback) |
| `MAX_REPO_SIZE_MB` | `10` | Reject repos larger than this |

---

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/repair` | Start repair job (async) |
| `GET` | `/api/repair/{id}` | Session detail + timeline + attempts |
| `POST` | `/api/repair/{id}/graph` | Rebuild and return ARISE graph JSON |
| `GET` | `/api/repo/{id}/browse?path=` | Browse repository file tree |
| `GET` | `/api/repo/{id}/functions?term=` | Symbol search |
| `GET` | `/api/dashboard` | Metrics summary |
| `GET` | `/api/memory` | All stored repair memories |
| `DELETE` | `/api/memory/{id}` | Delete a memory entry |
| `POST` | `/api/evaluate` | Run benchmark experiment |
| `GET` | `/api/evaluations` | List benchmark runs |
| `GET` | `/api/comparison` | Memory on vs off A/B comparison |

---

## License

Academic / research use. Benchmark repos are for experimentation only.