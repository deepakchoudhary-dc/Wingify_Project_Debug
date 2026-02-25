"""
Financial Document Analyzer - Database Module.

Provides SQLAlchemy-backed persistence for:
  - analysis_results: analysis runs (id, filename, query, result, status, timestamps)
  - users: user accounts and hashed API credentials

Security:
  - API keys are never stored in plaintext.
  - Incoming API keys are SHA-256 hashed before lookup.
  - SQLite FK enforcement is enabled via PRAGMA on each connection.

Compatibility:
  - Includes lightweight migration logic for legacy SQLite schemas that still use
    `users.api_key` without `users.api_key_hash`.
"""

import os
import uuid
import hashlib
import secrets
import sqlite3
from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    create_engine,
    Column,
    String,
    Text,
    DateTime,
    Integer,
    ForeignKey,
    event,
    text,
)
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.pool import StaticPool

# ── Database Setup ───────────────────────────────────────────────────────────
# Use an absolute path so API server and Celery worker agree on the same file
# regardless of which working directory each process is launched from.
_BASE_DIR = Path(__file__).resolve().parent
_DEFAULT_DB_URL = f"sqlite:///{_BASE_DIR}/financial_analyzer.db"


def _normalize_database_url(raw_url: str) -> str:
    """Normalize DB URL so relative SQLite file paths are project-root anchored."""
    if not raw_url or not raw_url.strip():
        return _DEFAULT_DB_URL

    url = make_url(raw_url)
    if url.get_backend_name() != "sqlite":
        return raw_url

    sqlite_db = url.database
    if not sqlite_db or sqlite_db == ":memory:" or sqlite_db.startswith("file:"):
        return raw_url

    db_path = Path(sqlite_db).expanduser()
    if not db_path.is_absolute():
        db_path = (_BASE_DIR / db_path).resolve()

    return str(url.set(database=str(db_path)))


DATABASE_URL = _normalize_database_url(os.getenv("DATABASE_URL", _DEFAULT_DB_URL))

_db_url = make_url(DATABASE_URL)
_is_sqlite = _db_url.get_backend_name() == "sqlite"
_is_sqlite_memory = _is_sqlite and (_db_url.database in (None, "", ":memory:"))

_engine_kwargs = {}
if _is_sqlite:
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
    if _is_sqlite_memory:
        # Keep one shared connection so in-memory SQLite retains schema/data
        # across SQLAlchemy sessions (used in tests and local smoke checks).
        _engine_kwargs["poolclass"] = StaticPool

engine = create_engine(DATABASE_URL, **_engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ── SQLite FK enforcement ────────────────────────────────────────────────────
# SQLite silently ignores FK constraints unless PRAGMA foreign_keys=ON is set
# at every new connection. The event listener below enforces this automatically.
@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


# ── Models ───────────────────────────────────────────────────────────────────
class User(Base):
    """Stores user accounts.

    `api_key_hash` is canonical.
    `api_key` exists only for backwards-compatible SQLite migration support and
    stores a hashed value as well (never plaintext).
    """

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), unique=True, nullable=False, index=True,
                     default=lambda: str(uuid.uuid4()))
    username = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=True)
    # Legacy compatibility column: always stores hash, never plaintext.
    api_key = Column(String(64), unique=True, nullable=True, index=True)
    # Canonical API key hash (SHA-256)
    api_key_hash = Column(String(64), unique=True, nullable=False, index=True)
    is_active = Column(Integer, default=1)  # SQLite has no native BOOLEAN
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    analyses = relationship("AnalysisResult", back_populates="user", lazy="dynamic")

    def to_dict(self):
        return {
            "user_id": self.user_id,
            "username": self.username,
            "email": self.email,
            "is_active": bool(self.is_active),
            "analysis_count": self.analyses.count() if self.analyses else 0,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class AnalysisResult(Base):
    """Stores the result of each financial document analysis run."""

    __tablename__ = "analysis_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    analysis_id = Column(String(36), unique=True, nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    query = Column(Text, nullable=False)
    result = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="completed")
    # pending | processing | retrying | completed | failed
    user_id = Column(String(36), ForeignKey("users.user_id"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="analyses")

    def to_dict(self):
        return {
            "analysis_id": self.analysis_id,
            "filename": self.filename,
            "query": self.query,
            "result": self.result,
            "status": self.status,
            "user_id": self.user_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ── Database Initialisation ─────────────────────────────────────────────────
def init_db():
    """Create tables and run lightweight compatibility migrations."""
    Base.metadata.create_all(bind=engine)
    _run_legacy_migrations()


def _run_legacy_migrations():
    """Migrate legacy SQLite schemas safely in-place.

    Handles older `users` table layouts that had only `api_key` and no
    `api_key_hash`.
    """
    if not _is_sqlite:
        return

    with engine.begin() as conn:
        columns = [row[1] for row in conn.execute(text("PRAGMA table_info(users)")).fetchall()]
        if not columns:
            return

        # Ensure both columns exist.
        if "api_key_hash" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN api_key_hash VARCHAR(64)"))
        if "api_key" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN api_key VARCHAR(64)"))

        # Backfill hash from existing api_key values (legacy plaintext or hash).
        rows = conn.execute(text("SELECT id, api_key, api_key_hash FROM users")).fetchall()
        for row in rows:
            user_id = row[0]
            old_api_key = row[1]
            old_hash = row[2]
            if old_hash:
                # Keep canonical hash; mirror legacy column to hashed value.
                new_hash = old_hash
            elif old_api_key:
                new_hash = _hash_api_key(old_api_key)
            else:
                # No recoverable key found; create random hash sentinel.
                new_hash = _hash_api_key(secrets.token_hex(32))
            conn.execute(
                text("UPDATE users SET api_key_hash = :h, api_key = :h WHERE id = :id"),
                {"h": new_hash, "id": user_id},
            )

        # Ensure indexes exist after migration.
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_api_key_hash ON users(api_key_hash)"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_api_key ON users(api_key)"))


# ── Analysis Result Operations ───────────────────────────────────────────────
def save_analysis_result(
    analysis_id: str,
    filename: str,
    query: str,
    result: str,
    status: str = "completed",
    user_id: str | None = None,
):
    """Insert or update an analysis result record."""
    db = SessionLocal()
    try:
        resolved_user_id = user_id
        if user_id and not db.query(User).filter_by(user_id=user_id).first():
            resolved_user_id = None

        existing = db.query(AnalysisResult).filter_by(analysis_id=analysis_id).first()
        if existing:
            existing.result = result
            existing.status = status
            existing.updated_at = datetime.utcnow()
            if resolved_user_id:
                existing.user_id = resolved_user_id
        else:
            record = AnalysisResult(
                analysis_id=analysis_id,
                filename=filename,
                query=query,
                result=result,
                status=status,
                user_id=resolved_user_id,
            )
            db.add(record)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_analysis_result(analysis_id: str):
    """Retrieve a single analysis result by its UUID."""
    db = SessionLocal()
    try:
        record = db.query(AnalysisResult).filter_by(analysis_id=analysis_id).first()
        return record.to_dict() if record else None
    finally:
        db.close()


def get_all_results(limit: int = 100, offset: int = 0, user_id: str | None = None):
    """Return analysis results with pagination. Pass limit=None to retrieve all."""
    db = SessionLocal()
    try:
        q = db.query(AnalysisResult)
        if user_id:
            q = q.filter_by(user_id=user_id)
        q = q.order_by(AnalysisResult.created_at.desc()).offset(offset)
        if limit is not None:
            q = q.limit(limit)
        return [r.to_dict() for r in q.all()]
    finally:
        db.close()


# ── User Operations ──────────────────────────────────────────────────────────
def _hash_api_key(plaintext: str) -> str:
    """Return the SHA-256 hex digest of a plaintext API key."""
    return hashlib.sha256(plaintext.encode()).hexdigest()


def _generate_api_key() -> tuple:
    """Return (plaintext_key, key_hash).

    The plaintext key (64 hex chars) is shown to the user ONCE at creation.
    Only the hash is persisted in the database.
    """
    plaintext = secrets.token_hex(32)       # 64 cryptographically-random hex chars
    return plaintext, _hash_api_key(plaintext)


def create_user(username: str, email: str | None = None) -> dict:
    """Create a new user account. Returns a dict that includes the API key ONCE."""
    db = SessionLocal()
    try:
        if db.query(User).filter_by(username=username).first():
            raise ValueError(f"Username '{username}' already exists.")
        if email and db.query(User).filter_by(email=email).first():
            raise ValueError(f"Email '{email}' is already registered.")

        plaintext_key, key_hash = _generate_api_key()
        user = User(
            user_id=str(uuid.uuid4()),
            username=username,
            email=email,
            api_key=key_hash,       # legacy-compatible hashed mirror
            api_key_hash=key_hash,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        # Include the plaintext key IN CREATION RESPONSE ONLY — not stored in DB
        result = user.to_dict()
        result["api_key"] = plaintext_key
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_user(user_id: str | None) -> dict | None:
    """Retrieve a user by their user_id (does not expose the API key hash)."""
    db = SessionLocal()
    try:
        record = db.query(User).filter_by(user_id=user_id).first()
        return record.to_dict() if record else None
    finally:
        db.close()


def get_user_by_api_key(api_key: str) -> dict | None:
    """Authenticate a user by hashing the provided key and looking up the hash."""
    key_hash = _hash_api_key(api_key)
    db = SessionLocal()
    try:
        record = db.query(User).filter_by(api_key_hash=key_hash, is_active=1).first()
        return record.to_dict() if record else None
    finally:
        db.close()


def get_all_users(limit: int = 100, offset: int = 0) -> list:
    """Return registered users with pagination. Pass limit=None to retrieve all."""
    db = SessionLocal()
    try:
        q = db.query(User).order_by(User.created_at.desc()).offset(offset)
        if limit is not None:
            q = q.limit(limit)
        return [u.to_dict() for u in q.all()]
    finally:
        db.close()
