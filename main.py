"""
Financial Document Analyzer - FastAPI Application.

Provides PDF analysis endpoints backed by a CrewAI multi-agent pipeline.
"""

import asyncio
import atexit
import hmac
import logging
import os
import uuid
from contextlib import suppress
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from threading import Lock
from time import monotonic

from fastapi import (
    BackgroundTasks,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware

from crewai import Crew, Process
from agents import build_agents
from task import build_financial_tasks
from database import (
    init_db,
    save_analysis_result,
    get_analysis_result,
    get_all_results,
    create_user,
    get_user,
    get_user_by_api_key,
    get_all_users,
)

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, min_value: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= min_value else default


def _load_admin_api_keys() -> list[str]:
    raw = os.getenv("ADMIN_API_KEYS", "")
    return [key.strip() for key in raw.split(",") if key.strip()]


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
OUTPUTS_DIR = BASE_DIR / "outputs"

UPLOAD_CHUNK_BYTES = 1024 * 1024
ALLOW_INPROCESS_FALLBACK = _env_bool("ALLOW_INPROCESS_FALLBACK", False)
MAX_UPLOAD_BYTES = _env_int("MAX_UPLOAD_BYTES", 50 * 1024 * 1024, min_value=1)
CELERY_STATUS_CACHE_TTL_SECONDS = _env_int("CELERY_STATUS_CACHE_TTL_SECONDS", 10, min_value=1)
THREAD_POOL_WORKERS = _env_int("THREAD_POOL_WORKERS", 4, min_value=1)
ADMIN_API_KEYS = _load_admin_api_keys()

app = FastAPI(
    title="Financial Document Analyzer",
    description=(
        "AI-powered financial document analysis system using a CrewAI multi-agent "
        "architecture. Upload a PDF and receive verification, financial analysis, "
        "investment insights, and risk assessment."
    ),
    version="2.1.0",
)

_raw_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:8080")
_allowed_origins = [origin.strip() for origin in _raw_origins.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()

_executor = ThreadPoolExecutor(max_workers=THREAD_POOL_WORKERS)
atexit.register(lambda: _executor.shutdown(wait=False, cancel_futures=True))
_celery_status_lock = Lock()
_celery_status_cache = {"ts": 0.0, "broker": False, "worker": False}


def _celery_available() -> bool:
    """Return True if Redis broker is reachable."""
    try:
        from celery_config import celery_app

        conn = celery_app.connection()
        conn.ensure_connection(max_retries=1, timeout=2)
        conn.close()
        return True
    except Exception:
        return False


def _celery_worker_active() -> bool:
    """Return True if at least one worker responds to ping."""
    try:
        from celery_config import celery_app

        responses = celery_app.control.inspect(timeout=2).ping() or {}
        return bool(responses)
    except Exception:
        return False


async def _run_in_pool(func, *args):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, func, *args)


async def _get_celery_status(force_refresh: bool = False) -> tuple[bool, bool]:
    """Cached broker+worker status check to avoid repeated 2s network probes."""
    now = monotonic()
    with _celery_status_lock:
        if (
            not force_refresh
            and now - _celery_status_cache["ts"] < CELERY_STATUS_CACHE_TTL_SECONDS
        ):
            return _celery_status_cache["broker"], _celery_status_cache["worker"]

    broker_ok, worker_ok = await asyncio.gather(
        _run_in_pool(_celery_available),
        _run_in_pool(_celery_worker_active),
    )

    with _celery_status_lock:
        _celery_status_cache["ts"] = monotonic()
        _celery_status_cache["broker"] = broker_ok
        _celery_status_cache["worker"] = worker_ok

    return broker_ok, worker_ok


def _is_admin_api_key(api_key: str | None) -> bool:
    if not api_key or not ADMIN_API_KEYS:
        return False
    return any(hmac.compare_digest(api_key, admin_key) for admin_key in ADMIN_API_KEYS)


def _resolve_user_id(api_key: str | None) -> str | None:
    """Return user_id for a valid user key; None when key is absent."""
    if not api_key:
        return None
    if not isinstance(api_key, str):
        raise HTTPException(status_code=401, detail="Invalid API key.")
    user = get_user_by_api_key(api_key)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API key.")
    return user["user_id"]


def _require_auth(api_key: str | None) -> tuple[str | None, bool]:
    """Authenticate request. Returns (user_id_or_none, is_admin)."""
    if not api_key:
        raise HTTPException(status_code=401, detail="X-API-Key is required.")
    if _is_admin_api_key(api_key):
        return None, True
    user_id = _resolve_user_id(api_key)
    return user_id, False


def _require_user_auth(api_key: str | None) -> str:
    """Require a non-admin user API key and return its user_id."""
    user_id, is_admin = _require_auth(api_key)
    if is_admin:
        raise HTTPException(status_code=403, detail="User API key required for this endpoint.")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid API key.")
    return user_id


async def _persist_upload_pdf(uploaded: UploadFile, destination: Path) -> None:
    """Stream upload to disk with strict size guard."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    total_bytes = 0

    try:
        with destination.open("wb") as out:
            while True:
                chunk = await uploaded.read(UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "File too large. Maximum allowed size is "
                            f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
                        ),
                    )
                out.write(chunk)
        if total_bytes == 0:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    except Exception:
        if destination.exists():
            destination.unlink(missing_ok=True)
        raise
    finally:
        await uploaded.close()


def run_crew(query: str, file_path: str) -> str:
    """Run one full crew execution."""
    verifier, financial_analyst, investment_advisor, risk_assessor = build_agents()
    tasks = build_financial_tasks(verifier, financial_analyst, investment_advisor, risk_assessor)
    financial_crew = Crew(
        agents=[verifier, financial_analyst, investment_advisor, risk_assessor],
        tasks=tasks,
        process=Process.sequential,
        verbose=False,
    )
    result = financial_crew.kickoff(inputs={"query": query, "file_path": file_path})
    result_text = str(result)
    if "TOOL_ERROR:" in result_text:
        raise RuntimeError("Analysis pipeline encountered tool failure.")
    return result_text


def _cleanup_file(path: str) -> None:
    with suppress(OSError):
        if os.path.exists(path):
            os.remove(path)


def _fallback_background_analysis(
    file_id: str, file_path: str, filename: str, query: str, user_id: str | None
) -> None:
    """In-process fallback worker."""
    try:
        result = run_crew(query=query, file_path=file_path)
        save_analysis_result(
            analysis_id=file_id,
            filename=filename,
            query=query,
            result=result,
            status="completed",
            user_id=user_id,
        )
    except Exception as exc:
        logger.exception("Fallback analysis failed")
        save_analysis_result(
            analysis_id=file_id,
            filename=filename,
            query=query,
            result=f"Analysis failed: {exc}",
            status="failed",
            user_id=user_id,
        )
    finally:
        _cleanup_file(file_path)


@app.get("/")
async def root():
    return {
        "message": "Financial Document Analyzer API is running",
        "version": "2.1.0",
        "endpoints": {
            "POST /analyze": "Upload a PDF and get synchronous analysis (requires X-API-Key)",
            "POST /analyze/async": "Upload a PDF for queue-worker analysis (requires X-API-Key)",
            "GET /results": "List analysis results (requires X-API-Key)",
            "GET /results/{analysis_id}": "Get one analysis result (requires X-API-Key)",
            "POST /users": "Create a new user account",
            "GET /users": "List users (admin API key required)",
            "GET /users/{user_id}": "Get one user profile and analyses (owner/admin key required)",
            "GET /health": "Service and worker health",
        },
    }


@app.get("/health")
async def health_check():
    broker_ok, worker_ok = await _get_celery_status()
    return {
        "status": "healthy",
        "service": "Financial Document Analyzer",
        "version": "2.1.0",
        "celery_broker_connected": broker_ok,
        "celery_worker_active": worker_ok,
    }


@app.post(
    "/analyze",
    responses={
        400: {"description": "Invalid file input"},
        401: {"description": "Invalid API key"},
        403: {"description": "User API key required"},
        500: {"description": "Analysis failure"},
    },
)
async def analyze_document(
    file: UploadFile = File(...),
    query: str = Form(default="Analyze this financial document and provide comprehensive investment insights"),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    user_id = _require_user_auth(x_api_key)
    file_id = str(uuid.uuid4())
    file_path = str(DATA_DIR / f"financial_document_{file_id}.pdf")

    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        await _persist_upload_pdf(file, Path(file_path))

        normalized_query = query.strip() if query and query.strip() else (
            "Analyze this financial document and provide comprehensive investment insights"
        )

        analysis_result = await _run_in_pool(run_crew, normalized_query, file_path)

        save_analysis_result(
            analysis_id=file_id,
            filename=file.filename,
            query=normalized_query,
            result=analysis_result,
            user_id=user_id,
        )

        output_path = OUTPUTS_DIR / f"analysis_{file_id}.txt"
        try:
            OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
            with output_path.open("w", encoding="utf-8") as out:
                out.write(f"Query: {normalized_query}\n")
                out.write(f"File: {file.filename}\n")
                out.write(f"Date: {datetime.utcnow().isoformat()}\n")
                out.write(f"{'=' * 80}\n\n")
                out.write(analysis_result)
        except Exception:
            logger.warning("Failed to write analysis artifact to %s", output_path, exc_info=True)

        return {
            "status": "success",
            "analysis_id": file_id,
            "query": normalized_query,
            "analysis": analysis_result,
            "file_processed": file.filename,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Synchronous analysis failed")
        raise HTTPException(
            status_code=500,
            detail="Error processing financial document.",
        )
    finally:
        _cleanup_file(file_path)


@app.post(
    "/analyze/async",
    status_code=202,
    responses={
        400: {"description": "Invalid file input"},
        401: {"description": "Invalid API key"},
        403: {"description": "User API key required"},
        503: {"description": "Queue worker unavailable"},
        500: {"description": "Internal queue error"},
    },
)
async def analyze_document_async(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    query: str = Form(default="Analyze this financial document and provide comprehensive investment insights"),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    user_id = _require_user_auth(x_api_key)
    file_id = str(uuid.uuid4())
    file_path = str(DATA_DIR / f"financial_document_{file_id}.pdf")

    normalized_query = query.strip() if query and query.strip() else (
        "Analyze this financial document and provide comprehensive investment insights"
    )

    dispatch_ready = False
    try:
        await _persist_upload_pdf(file, Path(file_path))

        save_analysis_result(
            analysis_id=file_id,
            filename=file.filename,
            query=normalized_query,
            result="Analysis queued - waiting for worker.",
            status="pending",
            user_id=user_id,
        )

        broker_ok, worker_ok = await _get_celery_status()
        dispatched_via = "celery"

        if broker_ok and worker_ok:
            try:
                from worker import analyze_document_task

                analyze_document_task.delay(
                    query=normalized_query,
                    file_path=file_path,
                    analysis_id=file_id,
                    filename=file.filename,
                    user_id=user_id,
                )
                dispatch_ready = True
            except Exception:
                logger.exception("Celery dispatch failed")
                if not ALLOW_INPROCESS_FALLBACK:
                    save_analysis_result(
                        analysis_id=file_id,
                        filename=file.filename,
                        query=normalized_query,
                        result="Queue dispatch failed. No fallback worker enabled.",
                        status="failed",
                        user_id=user_id,
                    )
                    _cleanup_file(file_path)
                    raise HTTPException(status_code=503, detail="Queue worker unavailable.")
                dispatched_via = "background_tasks"
                background_tasks.add_task(
                    _fallback_background_analysis,
                    file_id,
                    file_path,
                    file.filename,
                    normalized_query,
                    user_id,
                )
                dispatch_ready = True
        else:
            if not ALLOW_INPROCESS_FALLBACK:
                save_analysis_result(
                    analysis_id=file_id,
                    filename=file.filename,
                    query=normalized_query,
                    result="No active queue worker available.",
                    status="failed",
                    user_id=user_id,
                )
                _cleanup_file(file_path)
                raise HTTPException(status_code=503, detail="Queue worker unavailable.")
            dispatched_via = "background_tasks"
            background_tasks.add_task(
                _fallback_background_analysis,
                file_id,
                file_path,
                file.filename,
                normalized_query,
                user_id,
            )
            dispatch_ready = True

        return {
            "status": "accepted",
            "analysis_id": file_id,
            "dispatched_via": dispatched_via,
            "message": "Analysis queued. Poll GET /results/{analysis_id} for the result.",
        }
    except HTTPException:
        if not dispatch_ready:
            _cleanup_file(file_path)
        raise
    except Exception:
        logger.exception("Async analysis request failed before dispatch")
        with suppress(Exception):
            save_analysis_result(
                analysis_id=file_id,
                filename=file.filename or "unknown.pdf",
                query=normalized_query,
                result="Async analysis setup failed due to internal error.",
                status="failed",
                user_id=user_id,
            )
        if not dispatch_ready:
            _cleanup_file(file_path)
        raise HTTPException(status_code=500, detail="Error queueing financial document.")


@app.get(
    "/results",
    responses={
        401: {"description": "X-API-Key required or invalid"},
        403: {"description": "Forbidden"},
    },
)
async def list_results(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    user_id, is_admin = _require_auth(x_api_key)
    filter_user_id = None if is_admin else user_id
    results = get_all_results(limit=limit, offset=offset, user_id=filter_user_id)
    return {
        "status": "success",
        "limit": limit,
        "offset": offset,
        "count": len(results),
        "results": results,
    }


@app.get(
    "/results/{analysis_id}",
    responses={
        401: {"description": "X-API-Key required or invalid"},
        403: {"description": "Forbidden"},
        404: {"description": "Result not found"},
    },
)
async def get_result(
    analysis_id: str,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    user_id, is_admin = _require_auth(x_api_key)
    result = get_analysis_result(analysis_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Analysis result '{analysis_id}' not found.")

    owner_user_id = result.get("user_id")
    if not is_admin and owner_user_id != user_id:
        raise HTTPException(status_code=403, detail="Access denied for this analysis result.")

    return {"status": "success", "result": result}


@app.post(
    "/users",
    status_code=201,
    responses={
        409: {"description": "Username/email already exists"},
        500: {"description": "Internal user creation error"},
    },
)
async def register_user(
    username: str = Form(...),
    email: str = Form(default=None),
):
    try:
        user = create_user(username=username, email=email)
        return {"status": "success", "user": user}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception:
        logger.exception("User creation failed")
        raise HTTPException(status_code=500, detail="Failed to create user.")


@app.get(
    "/users",
    responses={
        401: {"description": "X-API-Key required or invalid"},
        403: {"description": "Admin API key required"},
    },
)
async def list_users(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    _, is_admin = _require_auth(x_api_key)
    if not is_admin:
        raise HTTPException(status_code=403, detail="Admin API key required.")

    users = get_all_users(limit=limit, offset=offset)
    return {
        "status": "success",
        "limit": limit,
        "offset": offset,
        "count": len(users),
        "users": users,
    }


@app.get(
    "/users/{user_id}",
    responses={
        401: {"description": "X-API-Key required or invalid"},
        403: {"description": "Forbidden"},
        404: {"description": "User not found"},
    },
)
async def get_user_profile(
    user_id: str,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    requester_user_id, is_admin = _require_auth(x_api_key)
    if not is_admin and requester_user_id != user_id:
        raise HTTPException(status_code=403, detail="Access denied for this user profile.")

    user = get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"User '{user_id}' not found.")

    analyses = get_all_results(user_id=user_id, limit=1000, offset=0)
    return {"status": "success", "user": user, "analyses": analyses}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
