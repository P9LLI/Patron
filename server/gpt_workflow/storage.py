from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import uuid
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Iterator

from .config import WorkflowConfig
from .errors import WorkflowError


SCHEMA = """
CREATE TABLE IF NOT EXISTS gptwf_executions (
    execution_id TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    workflow_version TEXT NOT NULL,
    runtime_version TEXT NOT NULL,
    contract_version TEXT NOT NULL,
    task_type TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    receipt_json TEXT NOT NULL,
    receipt_hash TEXT NOT NULL,
    releases_json TEXT NOT NULL,
    storage_bytes INTEGER NOT NULL DEFAULT 0,
    retention_state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT
);
CREATE TABLE IF NOT EXISTS gptwf_queries (
    execution_id TEXT NOT NULL,
    query_id TEXT NOT NULL,
    query_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (execution_id, query_id),
    FOREIGN KEY (execution_id) REFERENCES gptwf_executions(execution_id)
);
CREATE TABLE IF NOT EXISTS gptwf_repositories (
    repository_id TEXT NOT NULL,
    execution_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    status TEXT NOT NULL,
    candidate_count INTEGER NOT NULL DEFAULT 0,
    unique_process_count INTEGER NOT NULL DEFAULT 0,
    content_hash TEXT,
    created_at TEXT NOT NULL,
    frozen_at TEXT,
    PRIMARY KEY (repository_id, version),
    FOREIGN KEY (execution_id) REFERENCES gptwf_executions(execution_id)
);
CREATE TABLE IF NOT EXISTS gptwf_documents (
    content_hash TEXT PRIMARY KEY,
    normalized_json TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gptwf_candidates (
    repository_id TEXT NOT NULL,
    repository_version INTEGER NOT NULL,
    candidate_id TEXT NOT NULL,
    execution_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    process_number TEXT,
    final_url TEXT,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (repository_id, repository_version, candidate_id),
    FOREIGN KEY (content_hash) REFERENCES gptwf_documents(content_hash)
);
CREATE TABLE IF NOT EXISTS gptwf_candidate_queries (
    repository_id TEXT NOT NULL,
    repository_version INTEGER NOT NULL,
    candidate_id TEXT NOT NULL,
    query_id TEXT NOT NULL,
    PRIMARY KEY (repository_id, repository_version, candidate_id, query_id)
);
CREATE TABLE IF NOT EXISTS gptwf_batches (
    batch_id TEXT PRIMARY KEY,
    repository_id TEXT NOT NULL,
    repository_version INTEGER NOT NULL,
    batch_index INTEGER NOT NULL,
    total_batches INTEGER NOT NULL,
    candidate_ids_json TEXT NOT NULL,
    repository_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gptwf_selections (
    repository_id TEXT NOT NULL,
    repository_version INTEGER NOT NULL,
    batch_id TEXT NOT NULL,
    selection_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (repository_id, repository_version, batch_id)
);
CREATE TABLE IF NOT EXISTS gptwf_verifications (
    execution_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    verification_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (execution_id, candidate_id)
);
CREATE TABLE IF NOT EXISTS gptwf_samples (
    execution_id TEXT PRIMARY KEY,
    repository_id TEXT NOT NULL,
    repository_version INTEGER NOT NULL,
    sample_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gptwf_claims (
    execution_id TEXT NOT NULL,
    claim_id TEXT NOT NULL,
    claim_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (execution_id, claim_id)
);
CREATE TABLE IF NOT EXISTS gptwf_drafts (
    execution_id TEXT NOT NULL,
    draft_hash TEXT NOT NULL,
    repository_id TEXT NOT NULL,
    repository_version INTEGER NOT NULL,
    draft_text TEXT NOT NULL,
    audit_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (execution_id, draft_hash)
);
CREATE TABLE IF NOT EXISTS gptwf_receipts (
    receipt_id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    receipt_hash TEXT NOT NULL,
    receipt_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gptwf_idempotency (
    idempotency_key TEXT PRIMARY KEY,
    operation TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gptwf_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id TEXT,
    event_type TEXT NOT NULL,
    from_state TEXT,
    to_state TEXT,
    summary_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gptwf_deletions (
    deletion_id INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id TEXT,
    deleted_categories_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gptwf_candidates_execution
    ON gptwf_candidates(execution_id);
CREATE INDEX IF NOT EXISTS idx_gptwf_candidates_hash
    ON gptwf_candidates(content_hash);
CREATE INDEX IF NOT EXISTS idx_gptwf_events_execution
    ON gptwf_events(execution_id);
"""


class WorkflowStorage:
    def __init__(self, config: WorkflowConfig) -> None:
        self.config = config
        config.db_path.parent.mkdir(parents=True, exist_ok=True)
        config.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger(f"gpt_workflow.{uuid.uuid4().hex}")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        handler = RotatingFileHandler(
            config.log_path,
            maxBytes=config.log_max_bytes,
            backupCount=config.log_backup_count,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        self.logger.addHandler(handler)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.config.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.session() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def disk_status(self) -> dict[str, Any]:
        usage = shutil.disk_usage(self.config.db_path.parent)
        percent = (
            self.config.simulated_disk_percent
            if self.config.simulated_disk_percent is not None
            else (usage.used / usage.total * 100 if usage.total else 0.0)
        )
        if percent >= self.config.disk_critical_percent:
            status = "critical"
        elif percent >= self.config.disk_restricted_percent:
            status = "restricted"
        elif percent >= self.config.disk_warning_percent:
            status = "warning"
        else:
            status = "ok"
        return {
            "capacity_bytes": usage.total,
            "used_bytes": usage.used,
            "available_bytes": usage.free,
            "usage_percent": round(percent, 2),
            "status": status,
        }

    def _safe_warning_cleanup(self) -> None:
        """Prune only expired integration metadata and unreferenced documents."""
        from datetime import datetime, timezone

        try:
            with self.transaction() as conn:
                conn.execute(
                    "DELETE FROM gptwf_idempotency WHERE expires_at < ?",
                    (datetime.now(timezone.utc).isoformat(),),
                )
                conn.execute(
                    """
                    DELETE FROM gptwf_documents WHERE content_hash NOT IN
                    (SELECT DISTINCT content_hash FROM gptwf_candidates)
                    """
                )
        except sqlite3.Error as exc:
            self.logger.warning("storage_warning_cleanup_failed error_type=%s", type(exc).__name__)

    def guard_growth(self, operation: str) -> None:
        status = self.disk_status()
        if status["status"] in {"restricted", "critical"}:
            code = "DISK_HARD_LIMIT_REACHED"
            raise WorkflowError(
                code,
                "Persistent storage is in preventive restriction mode.",
                status_code=507,
                details={
                    "storage_usage_percent": status["usage_percent"],
                    "operation": operation,
                    "allowed_operations": ["get_execution", "get_release", "cleanup", "health"],
                },
            )
        if status["status"] == "warning":
            self._safe_warning_cleanup()
            self.logger.warning("storage_warning operation=%s usage_percent=%s", operation, status["usage_percent"])

    @staticmethod
    def json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
