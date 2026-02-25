"""
Financial Document Analyzer - Celery Configuration (Bonus Feature)

Provides Celery app configuration for asynchronous task processing.
Requires a running Redis server (default: redis://localhost:6379/0).

Usage:
    # Start the Celery worker (Issue #5: entry-point module is `worker`, not `celery_app`):
    celery -A worker worker --loglevel=info --pool=solo

    # Or on Windows:
    celery -A worker worker --loglevel=info --pool=solo

    # To scale throughput (Issue #4), run multiple worker *processes* rather
    # than increasing --concurrency.  Each CrewAI job already saturates one
    # CPU/LLM quota; adding threads inside one process does not help:
    celery -A worker worker --loglevel=info --pool=solo  # process 1
    celery -A worker worker --loglevel=info --pool=solo  # process 2 (separate terminal)
"""

import os
from celery import Celery
from dotenv import load_dotenv

load_dotenv()

# Redis connection URL (defaults to local Redis)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# ── Celery App ───────────────────────────────────────────────────────────────
celery_app = Celery(
    "financial_analyzer",
    broker=REDIS_URL,
    backend=REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,  # Intentionally 1 — LLM-bound tasks are long-running;
                                   # prefetching more tasks would starve other workers.
                                   # To scale throughput, run multiple worker processes.
    result_expires=86400,  # Results expire after 24 hours
)
