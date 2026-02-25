# Financial Document Analyzer

AI-powered financial document analysis system built with CrewAI, FastAPI, Celery, Redis, and SQLAlchemy.

## 1) What This Project Delivers

- Multi-agent financial analysis pipeline for uploaded PDF reports.
- Synchronous and asynchronous analysis endpoints.
- Queue worker model with Celery + Redis for concurrent requests.
- Database integration for:
  - user accounts
  - API key auth (hashed keys)
  - analysis result storage and status tracking
- Auth + ownership checks for result and user endpoints.

## 2) Architecture

- API server: `main.py`
- Crew agents: `agents.py` (factory-based, fresh agents per run)
- Crew tasks: `task.py` (factory-based, fresh tasks per run)
- Tools: `tools.py` (PDF extract + investment/risk signal extraction + search)
- Queue: `celery_config.py`, `worker.py`
- Database: `database.py` (`users`, `analysis_results`)

## 3) Setup Instructions

### Prerequisites

- Python 3.10+
- Redis (for queue worker mode)
- Provider/API keys:
  - Gemini or OpenAI key
  - Serper key (for search tool)

### Install

```bash
python -m venv venv

# Windows
.\venv\Scripts\Activate.ps1

# Linux/macOS
source venv/bin/activate

pip install -r requirements.txt
```

### Configure environment

```bash
# Windows
copy .env.example .env

# Linux/macOS
cp .env.example .env
```

Fill required keys in `.env`.

## 4) Environment Variables

| Variable | Default | Description |
|---|---|---|
| `MODEL_NAME` | `gemini/gemini-2.0-flash` | LLM model identifier |
| `GEMINI_API_KEY` | - | Gemini API key |
| `OPENAI_API_KEY` | - | OpenAI API key |
| `SERPER_API_KEY` | - | Serper search API key |
| `DATABASE_URL` | `sqlite:///financial_analyzer.db` | DB URL (relative sqlite paths are normalized to project root by code) |
| `REDIS_URL` | `redis://localhost:6379/0` | Celery broker/backend |
| `ALLOWED_ORIGINS` | `http://localhost:3000,http://localhost:8080` | CORS allowlist |
| `MAX_UPLOAD_BYTES` | `52428800` | Max upload size (bytes) |
| `MAX_EXTRACT_CHARS` | `150000` | Max extracted PDF text passed downstream |
| `ALLOW_INPROCESS_FALLBACK` | `true` | Use FastAPI background fallback when worker unavailable (set `false` in production) |
| `CELERY_STATUS_CACHE_TTL_SECONDS` | `10` | Celery health cache TTL |
| `THREAD_POOL_WORKERS` | `4` | Thread pool size for sync crew execution |
| `ADMIN_API_KEYS` | empty | Comma-separated admin keys (leave empty to disable admin routes in dev) |

## 5) Run Instructions

### Start API

```bash
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### Start Celery worker (for queue mode)

```bash
celery -A worker worker --loglevel=info --pool=solo
```

To increase throughput, run multiple worker processes in separate terminals.

## 6) API Documentation

### Auth model

- `POST /users` creates a user and returns plaintext API key once.
- Most protected endpoints require header: `X-API-Key: <key>`.
- Admin-only access uses key(s) configured in `ADMIN_API_KEYS`.
- Analysis endpoints require a regular user API key (not admin key).

### Endpoints

#### `GET /`
- Description: basic service metadata.

#### `GET /health`
- Description: service health plus broker/worker status.
- Response fields include:
  - `celery_broker_connected`
  - `celery_worker_active`

#### `POST /users` (201)
- Description: create user.
- Form fields:
  - `username` (required)
  - `email` (optional)
- Returns: user profile + plaintext `api_key` (only once).

#### `POST /analyze` (sync)
- Description: synchronous analysis.
- Auth: required `X-API-Key` (user key).
- Multipart/form-data:
  - `file` (required, PDF only)
  - `query` (optional)
- Returns: `analysis_id`, analysis text, metadata.
- Errors: `400`, `401`, `403`, `500`.

#### `POST /analyze/async` (202)
- Description: asynchronous queue-based analysis.
- Auth: required `X-API-Key` (user key).
- Multipart/form-data:
  - `file` (required, PDF only)
  - `query` (optional)
- Returns:
  - `analysis_id`
  - `dispatched_via` (`celery` or `background_tasks`)
- Errors: `400`, `401`, `403`, `503`, `500`.

#### `GET /results`
- Description: paginated result listing.
- Auth: required `X-API-Key`.
- Query:
  - `limit` (1-1000, default 100)
  - `offset` (>=0, default 0)
- Behavior:
  - user key: only own results
  - admin key: all results

#### `GET /results/{analysis_id}`
- Description: fetch one analysis result.
- Auth: required `X-API-Key`.
- Ownership enforced for non-admin keys.
- Errors: `401`, `403`, `404`.

#### `GET /users`
- Description: list users.
- Auth: admin key required.
- Query: `limit`, `offset`.
- Errors: `401`, `403`.

#### `GET /users/{user_id}`
- Description: user profile + analyses.
- Auth: owner or admin key required.
- Errors: `401`, `403`, `404`.

## 7) Queue Worker Model (Concurrent Request Handling)

Implemented with Celery + Redis:

1. API stores uploaded file and creates a `pending` DB row.
2. API checks broker and active worker.
3. If available, request is enqueued to Celery (`analyze_document_task`).
4. Worker executes Crew pipeline and writes `processing/completed/failed` status.
5. If queue unavailable:
   - fallback enabled: FastAPI background task executes pipeline
   - fallback disabled: request returns `503` and status is `failed`

Concurrency scaling:

- Keep `--pool=solo` for each worker process.
- Scale by running multiple worker processes.
- `worker_prefetch_multiplier=1` reduces long-task starvation.

## 8) Database Integration

### Tables

- `users`
  - `user_id`, `username`, `email`, `api_key_hash`, `is_active`, timestamps
- `analysis_results`
  - `analysis_id`, `filename`, `query`, `result`, `status`, `user_id`, timestamps

### Security

- API keys are generated once and stored as SHA-256 hash only.
- Incoming keys are hashed for lookup.
- No plaintext key persistence.

### Compatibility/Migration

- Legacy sqlite schemas with `users.api_key` are migrated to canonical `api_key_hash`.
- Relative sqlite DB URLs are normalized to project root to avoid API/worker DB drift.

## 9) Bugs Found and How They Were Fixed

### A) Deterministic Bugs (fixed)

1. Shared state risk from global Crew task objects under concurrent requests.
- Fix: task factory returns fresh task objects per run.

2. Worker still depended on old global task symbols.
- Fix: worker now uses `build_financial_tasks(...)`.

3. In-memory sqlite could fail with missing tables across sessions.
- Fix: `StaticPool` used for sqlite `:memory:` mode.

4. Legacy user schema missing `api_key_hash` caused auth/runtime failures.
- Fix: lightweight migration/backfill added in DB init.

5. Async dispatch lost ownership context.
- Fix: `user_id` propagated through queue dispatch and worker writes.

6. Sync endpoint could fail after successful analysis if output artifact write failed.
- Fix: output file write is now best-effort (logged, non-fatal).

7. Invalid integer env vars could crash startup (`MAX_EXTRACT_CHARS`, upload/cache ints).
- Fix: safe positive-int env parsing with defaults.

8. Relative sqlite URL from env could split API/worker into different DB files.
- Fix: relative sqlite paths normalized to project-root absolute path.

9. Analysis endpoints accepted admin key and produced ownerless rows.
- Fix: analysis endpoints now require regular user API key.

10. Async writes could fail on FK constraint if task carried a stale/deleted user id.
- Fix: persistence layer validates user id existence before writing analysis rows.

### B) Inefficient Prompt/Flow Issues (fixed)

1. Prompt chains were too verbose and token-heavy.
- Fix: compact output constraints and tighter step instructions.

2. Web search usage could expand unnecessarily.
- Fix: explicit search budget constraints (`at most one query` when essential).

3. Large PDF extraction could overflow context/token budget.
- Fix: extraction hard-cap (`MAX_EXTRACT_CHARS`) with truncation marker.

4. Re-reading PDF in downstream stages increased cost.
- Fix: verifier reads source; downstream tasks consume context outputs.

## 10) Verification Notes

Validated with local smoke tests:

- Imports and route bootstrap.
- User registration and auth/ownership checks.
- Sync analysis flow.
- Async analysis flow (fallback mode and failure status path).
- Admin gating for `/users`.

For production readiness, run end-to-end tests against live LLM and live Redis/Celery infrastructure.
