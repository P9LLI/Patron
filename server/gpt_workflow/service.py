from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

from .config import WorkflowConfig
from .errors import WorkflowError
from .storage import WorkflowStorage


ORDERED_STATES = [
    "CREATED",
    "PLANNED",
    "DISCOVERY_OPEN",
    "CANDIDATES_REGISTERED",
    "REPOSITORY_FROZEN",
    "SEMANTIC_SELECTION_COMPLETED",
    "FINALISTS_VERIFIED",
    "SAMPLE_ADMITTED",
    "CLAIMS_RESOLVED",
    "DRAFT_SUBMITTED",
    "ANSWER_RELEASED",
]
RELEASE_KEYS = (
    "sources_release",
    "repository_release",
    "selection_release",
    "sample_release",
    "claims_release",
    "answer_release",
)
BUCKETS = {"main", "supplemental", "contextual", "excluded", "unverified"}
CLAIM_STATES = {"supported", "context_only", "abstain", "general_guidance", "not_requested"}
IDENTITY_STATUSES = {"confirmed", "unconfirmed", "conflicting", "not_applicable"}
VERIFICATION_STATUSES = {"verified", "unverified", "rejected"}
TREND_PATTERNS = (
    r"\btend[eê]ncia\b",
    r"\bpredomin(?:a|ante|ância)\b",
    r"\bmaioria\b",
    r"\bfrequent(?:e|emente)\b",
    r"\breiterad[ao]s?\b",
    r"\best[aá]vel\b",
    r"\bconsolidada?\b",
    r"\bao longo dos anos\b",
)
PROCESS_RE = re.compile(r"\b\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\b")
AMOUNT_RE = re.compile(r"\bR\$\s*\d{1,3}(?:\.\d{3})*(?:,\d{2})?\b", re.IGNORECASE)
DATE_RE = re.compile(r"\b(?:0?[1-9]|[12]\d|3[01])[/.-](?:0?[1-9]|1[0-2])[/.-](?:19|20)\d{2}\b")
SUMULA_RE = re.compile(r"\bS[úu]mula\s+(?:n[º°o]\s*)?(\d+)\b", re.IGNORECASE)
ARTICLE_RE = re.compile(r"\bart(?:igo|\.)?\s*(\d+[A-Za-z]?)\b", re.IGNORECASE)
PERCENT_RE = re.compile(r"\b\d+(?:[,.]\d+)?\s*%")
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
CHAMBER_RE = re.compile(r"\b\d{1,2}(?:a|.)?\s+C.mara(?:\s+de\s+Direito\s+[\w-]+)?\b", re.IGNORECASE)
MAGISTRATE_RE = re.compile(r"\b(?:Relator(?:a)?|Desembargador(?:a)?)\s*[:\-]?\s*([A-Z][\w.'-]+(?:\s+[A-Z][\w.'-]+){1,6})")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    raw = value if isinstance(value, str) else canonical(value)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def identifier(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16].upper()}"


def canonical_url(value: str | None) -> str | None:
    if not value:
        return None
    parts = urlsplit(value.strip())
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), parts.query, ""))


class WorkflowService:
    def __init__(self, config: WorkflowConfig) -> None:
        self.config = config
        self.storage = WorkflowStorage(config)

    def _bounded(self, payload: Any) -> int:
        size = len(canonical(payload).encode("utf-8"))
        if size > self.config.request_max_bytes:
            raise WorkflowError(
                "PAYLOAD_TOO_LARGE",
                "Request exceeds the configured payload limit.",
                status_code=413,
                details={"limit_bytes": self.config.request_max_bytes, "actual_bytes": size},
            )
        return size

    def _mutate(
        self,
        operation: str,
        idempotency_key: str,
        payload: Any,
        callback: Callable[[sqlite3.Connection], tuple[dict[str, Any], int]],
    ) -> tuple[dict[str, Any], int, bool]:
        if not idempotency_key or len(idempotency_key) > 200:
            raise WorkflowError("IDEMPOTENCY_KEY_REQUIRED", "A valid Idempotency-Key header is required.", status_code=400)
        self._bounded(payload)
        request_hash = digest({"operation": operation, "payload": payload})
        with self.storage.transaction() as conn:
            row = conn.execute(
                "SELECT request_hash,status_code,response_json FROM gptwf_idempotency WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if row:
                if row["request_hash"] != request_hash:
                    raise WorkflowError(
                        "IDEMPOTENCY_CONFLICT",
                        "The idempotency key was already used with a different request.",
                        status_code=409,
                    )
                return json.loads(row["response_json"]), row["status_code"], True
            response, status_code = callback(conn)
            expires_at = (
                datetime.now(timezone.utc) + timedelta(days=self.config.idempotency_retention_days)
            ).isoformat()
            conn.execute(
                """
                INSERT INTO gptwf_idempotency
                (idempotency_key,operation,request_hash,status_code,response_json,created_at,expires_at)
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    idempotency_key,
                    operation,
                    request_hash,
                    status_code,
                    canonical(response),
                    utc_now(),
                    expires_at,
                ),
            )
            return response, status_code, False

    @staticmethod
    def _execution(conn: sqlite3.Connection, execution_id: str) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM gptwf_executions WHERE execution_id=?", (execution_id,)
        ).fetchone()
        if not row:
            raise WorkflowError("EXECUTION_NOT_FOUND", "Execution does not exist.", status_code=404)
        return row

    @staticmethod
    def _repository(
        conn: sqlite3.Connection, execution_id: str, version: int | None = None
    ) -> sqlite3.Row:
        params: list[Any] = [execution_id]
        clause = ""
        if version is not None:
            clause = " AND version=?"
            params.append(version)
        row = conn.execute(
            f"SELECT * FROM gptwf_repositories WHERE execution_id=?{clause} ORDER BY version DESC LIMIT 1",
            params,
        ).fetchone()
        if not row:
            raise WorkflowError("REPOSITORY_NOT_FOUND", "Repository does not exist.", status_code=404)
        return row

    def _event(
        self,
        conn: sqlite3.Connection,
        execution_id: str | None,
        event_type: str,
        *,
        from_state: str | None = None,
        to_state: str | None = None,
        summary: dict[str, Any] | None = None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO gptwf_events
            (execution_id,event_type,from_state,to_state,summary_json,created_at)
            VALUES (?,?,?,?,?,?)
            """,
            (execution_id, event_type, from_state, to_state, canonical(summary or {}), utc_now()),
        )
        self.storage.logger.info(
            "event=%s execution_id=%s from=%s to=%s",
            event_type,
            execution_id,
            from_state,
            to_state,
        )

    def _transition(
        self,
        conn: sqlite3.Connection,
        execution_id: str,
        target: str,
        *,
        revision: bool = False,
    ) -> None:
        row = self._execution(conn, execution_id)
        current = row["state"]
        if current == target:
            return
        if not revision:
            expected = ORDERED_STATES[ORDERED_STATES.index(current) + 1]
            if target != expected:
                raise WorkflowError(
                    "INVALID_STATE_TRANSITION",
                    f"Cannot transition from {current} to {target}.",
                    details={"current_state": current, "expected_state": expected},
                )
        conn.execute(
            "UPDATE gptwf_executions SET state=?,updated_at=? WHERE execution_id=?",
            (target, utc_now(), execution_id),
        )
        self._event(
            conn,
            execution_id,
            "state_transition" if not revision else "repository_revision",
            from_state=current,
            to_state=target,
        )

    def _set_release(self, conn: sqlite3.Connection, execution_id: str, key: str, value: int = 1) -> None:
        row = self._execution(conn, execution_id)
        releases = json.loads(row["releases_json"])
        releases[key] = value
        conn.execute(
            "UPDATE gptwf_executions SET releases_json=?,updated_at=? WHERE execution_id=?",
            (canonical(releases), utc_now(), execution_id),
        )

    def create_execution(
        self, payload: dict[str, Any], idempotency_key: str
    ) -> tuple[dict[str, Any], int, bool]:
        self.storage.guard_growth("create_execution")

        def create(conn: sqlite3.Connection) -> tuple[dict[str, Any], int]:
            execution_id = identifier("exec")
            created = utc_now()
            input_hash = digest(payload.get("input", payload))
            receipt = {
                "execution_id": execution_id,
                "workflow_version": self.config.workflow_version,
                "runtime_version": self.config.runtime_version,
                "api_contract_version": self.config.contract_version,
                "task_type": "precedent_mapping",
                "sample_required": True,
                "repository_required": True,
                "required_gates": [
                    "source_gate",
                    "repository_freeze_gate",
                    "semantic_selection_gate",
                    "finalist_verification_gate",
                    "sample_admission_gate",
                    "claim_resolution_gate",
                    "final_release_gate",
                ],
                "input_hash": input_hash,
                "created_at": created,
            }
            receipt["receipt_hash"] = digest(receipt)
            releases = {key: 0 for key in RELEASE_KEYS}
            expires_at = (
                datetime.now(timezone.utc) + timedelta(days=self.config.finalized_retention_days)
            ).isoformat()
            conn.execute(
                """
                INSERT INTO gptwf_executions
                (execution_id,state,workflow_version,runtime_version,contract_version,task_type,
                 input_hash,receipt_json,receipt_hash,releases_json,storage_bytes,retention_state,
                 created_at,updated_at,expires_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    execution_id,
                    "CREATED",
                    self.config.workflow_version,
                    self.config.runtime_version,
                    self.config.contract_version,
                    "precedent_mapping",
                    input_hash,
                    canonical(receipt),
                    receipt["receipt_hash"],
                    canonical(releases),
                    len(canonical(receipt).encode("utf-8")),
                    "ACTIVE",
                    created,
                    created,
                    expires_at,
                ),
            )
            conn.execute(
                """
                INSERT INTO gptwf_receipts
                (receipt_id,execution_id,kind,receipt_hash,receipt_json,created_at)
                VALUES (?,?,?,?,?,?)
                """,
                (identifier("RCT"), execution_id, "workflow", receipt["receipt_hash"], canonical(receipt), created),
            )
            self._event(conn, execution_id, "execution_created", to_state="CREATED")
            return {"execution": {"execution_id": execution_id, "state": "CREATED"}, "workflow_receipt": receipt, "releases": releases}, 201

        return self._mutate("create_execution", idempotency_key, payload, create)

    def submit_queries(
        self, execution_id: str, payload: dict[str, Any], idempotency_key: str
    ) -> tuple[dict[str, Any], int, bool]:
        queries = payload.get("queries")
        if not isinstance(queries, list) or not queries:
            raise WorkflowError("INVALID_QUERY_BATCH", "queries must be a non-empty array.", status_code=422)

        def submit(conn: sqlite3.Connection) -> tuple[dict[str, Any], int]:
            execution = self._execution(conn, execution_id)
            if execution["state"] not in {"CREATED", "PLANNED", "DISCOVERY_OPEN"}:
                raise WorkflowError("DISCOVERY_CLOSED", "Queries cannot be changed in the current state.")
            if execution["state"] == "CREATED":
                self._transition(conn, execution_id, "PLANNED")
            if self._execution(conn, execution_id)["state"] == "PLANNED":
                self._transition(conn, execution_id, "DISCOVERY_OPEN")
            seen: set[str] = set()
            for query in queries:
                query_id = str(query.get("query_id", "")).strip()
                text = str(query.get("text", "")).strip()
                if not query_id or not text or query_id in seen:
                    raise WorkflowError("INVALID_QUERY", "Each query requires a unique query_id and text.", status_code=422)
                seen.add(query_id)
                conn.execute(
                    "INSERT OR REPLACE INTO gptwf_queries VALUES (?,?,?,?)",
                    (execution_id, query_id, canonical(query), utc_now()),
                )
            self._event(conn, execution_id, "queries_registered", summary={"count": len(queries)})
            return {"execution_id": execution_id, "state": "DISCOVERY_OPEN", "query_count": len(queries)}, 200

        return self._mutate("submit_queries", idempotency_key, {"execution_id": execution_id, **payload}, submit)

    def _validate_candidate(self, candidate: dict[str, Any]) -> tuple[dict[str, Any], str, int]:
        if not isinstance(candidate, dict):
            raise WorkflowError("INVALID_CANDIDATE", "Candidate must be an object.", status_code=422)
        candidate_id = str(candidate.get("candidate_id", "")).strip()
        source_url = str(candidate.get("source_url", "")).strip()
        if not candidate_id or not source_url:
            raise WorkflowError("INVALID_CANDIDATE", "candidate_id and source_url are required.", status_code=422)
        excerpts = candidate.get("excerpts") or {}
        if not isinstance(excerpts, dict) or len(excerpts) > self.config.excerpts_max_count:
            raise WorkflowError("CANDIDATE_STORAGE_LIMIT", "Candidate has too many evidence excerpts.", status_code=413)
        for excerpt in excerpts.values():
            if excerpt is not None and len(str(excerpt).encode("utf-8")) > self.config.excerpt_max_bytes:
                raise WorkflowError("CANDIDATE_STORAGE_LIMIT", "An evidence excerpt exceeds its size limit.", status_code=413)
        normalized = dict(candidate)
        normalized["final_url"] = canonical_url(candidate.get("final_url") or source_url)
        normalized.pop("content_hash", None)
        size = len(canonical(normalized).encode("utf-8"))
        if size > self.config.candidate_max_bytes:
            raise WorkflowError(
                "CANDIDATE_STORAGE_LIMIT",
                "Candidate exceeds its configured storage limit.",
                status_code=413,
                details={"limit_bytes": self.config.candidate_max_bytes, "actual_bytes": size},
            )
        document_view = {
            key: value
            for key, value in normalized.items()
            if key not in {"candidate_id", "query_ids"}
        }
        content_hash = digest(document_view)
        normalized["content_hash"] = content_hash
        return normalized, content_hash, size

    def _start_repository_revision(
        self, conn: sqlite3.Connection, execution_id: str, repository: sqlite3.Row
    ) -> sqlite3.Row:
        new_version = repository["version"] + 1
        if new_version > self.config.repository_versions_max:
            raise WorkflowError("REPOSITORY_VERSION_LIMIT", "Repository version limit reached.", status_code=409)
        created = utc_now()
        conn.execute(
            """
            INSERT INTO gptwf_repositories
            (repository_id,execution_id,version,status,candidate_count,unique_process_count,created_at)
            VALUES (?,?,?,'open',?,?,?)
            """,
            (
                repository["repository_id"],
                execution_id,
                new_version,
                repository["candidate_count"],
                repository["unique_process_count"],
                created,
            ),
        )
        conn.execute(
            """
            INSERT INTO gptwf_candidates
            SELECT repository_id,?,candidate_id,execution_id,content_hash,process_number,final_url,metadata_json,?
            FROM gptwf_candidates WHERE repository_id=? AND repository_version=?
            """,
            (new_version, created, repository["repository_id"], repository["version"]),
        )
        conn.execute(
            """
            INSERT INTO gptwf_candidate_queries
            SELECT repository_id,?,candidate_id,query_id
            FROM gptwf_candidate_queries WHERE repository_id=? AND repository_version=?
            """,
            (new_version, repository["repository_id"], repository["version"]),
        )
        for table in ("gptwf_verifications", "gptwf_claims"):
            conn.execute(f"DELETE FROM {table} WHERE execution_id=?", (execution_id,))
        conn.execute("DELETE FROM gptwf_samples WHERE execution_id=?", (execution_id,))
        releases = {key: 0 for key in RELEASE_KEYS}
        conn.execute(
            "UPDATE gptwf_executions SET releases_json=? WHERE execution_id=?",
            (canonical(releases), execution_id),
        )
        self._transition(conn, execution_id, "CANDIDATES_REGISTERED", revision=True)
        return self._repository(conn, execution_id, new_version)

    def submit_candidates(
        self, execution_id: str, payload: dict[str, Any], idempotency_key: str
    ) -> tuple[dict[str, Any], int, bool]:
        self.storage.guard_growth("submit_candidates")
        candidates = payload.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise WorkflowError("INVALID_CANDIDATE_BATCH", "candidates must be a non-empty array.", status_code=422)
        validated = [self._validate_candidate(item) for item in candidates]

        def submit(conn: sqlite3.Connection) -> tuple[dict[str, Any], int]:
            execution = self._execution(conn, execution_id)
            if execution["state"] not in {
                "DISCOVERY_OPEN",
                "CANDIDATES_REGISTERED",
                "REPOSITORY_FROZEN",
                "SEMANTIC_SELECTION_COMPLETED",
                "FINALISTS_VERIFIED",
                "SAMPLE_ADMITTED",
                "CLAIMS_RESOLVED",
                "DRAFT_SUBMITTED",
                "ANSWER_RELEASED",
            }:
                raise WorkflowError("DISCOVERY_INCOMPLETE", "Candidates cannot be registered before discovery.")
            try:
                repository = self._repository(conn, execution_id)
            except WorkflowError as exc:
                if exc.code != "REPOSITORY_NOT_FOUND":
                    raise
                repository_id = identifier("REP")
                conn.execute(
                    """
                    INSERT INTO gptwf_repositories
                    (repository_id,execution_id,version,status,candidate_count,unique_process_count,created_at)
                    VALUES (?,?,1,'open',0,0,?)
                    """,
                    (repository_id, execution_id, utc_now()),
                )
                repository = self._repository(conn, execution_id)
            if repository["status"] == "frozen":
                repository = self._start_repository_revision(conn, execution_id, repository)
            current_count = conn.execute(
                "SELECT COUNT(*) FROM gptwf_candidates WHERE execution_id=? AND repository_id=? AND repository_version=?",
                (execution_id, repository["repository_id"], repository["version"]),
            ).fetchone()[0]
            if current_count + len(validated) > self.config.candidates_max_count:
                raise WorkflowError("EXECUTION_STORAGE_LIMIT", "Candidate count limit would be exceeded.", status_code=413)
            inserted = 0
            reused = 0
            added_bytes = 0
            for normalized, content_hash, size in validated:
                candidate_id = normalized["candidate_id"]
                existing_id = conn.execute(
                    """
                    SELECT candidate_id FROM gptwf_candidates
                    WHERE repository_id=? AND repository_version=? AND
                          (content_hash=? OR (? IS NOT NULL AND final_url=?))
                    LIMIT 1
                    """,
                    (
                        repository["repository_id"],
                        repository["version"],
                        content_hash,
                        normalized.get("final_url"),
                        normalized.get("final_url"),
                    ),
                ).fetchone()
                if existing_id:
                    reused += 1
                    link_candidate_id = existing_id["candidate_id"]
                else:
                    conflicting = conn.execute(
                        """
                        SELECT content_hash FROM gptwf_candidates
                        WHERE repository_id=? AND repository_version=? AND candidate_id=?
                        """,
                        (repository["repository_id"], repository["version"], candidate_id),
                    ).fetchone()
                    if conflicting and conflicting["content_hash"] != content_hash:
                        raise WorkflowError("CANDIDATE_ID_CONFLICT", "candidate_id identifies different content.")
                    document_payload = {
                        key: value
                        for key, value in normalized.items()
                        if key not in {"candidate_id", "query_ids", "content_hash"}
                    }
                    conn.execute(
                        "INSERT OR IGNORE INTO gptwf_documents VALUES (?,?,?,?)",
                        (
                            content_hash,
                            canonical(document_payload),
                            len(canonical(document_payload).encode("utf-8")),
                            utc_now(),
                        ),
                    )
                    conn.execute(
                        """
                        INSERT INTO gptwf_candidates
                        (repository_id,repository_version,candidate_id,execution_id,content_hash,
                         process_number,final_url,metadata_json,created_at)
                        VALUES (?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            repository["repository_id"],
                            repository["version"],
                            candidate_id,
                            execution_id,
                            content_hash,
                            normalized.get("process_number"),
                            normalized.get("final_url"),
                            canonical({
                                "candidate_id": candidate_id,
                                "query_ids": normalized.get("query_ids") or [],
                                "content_hash": content_hash,
                            }),
                            utc_now(),
                        ),
                    )
                    inserted += 1
                    added_bytes += size
                    link_candidate_id = candidate_id
                for query_id in normalized.get("query_ids") or []:
                    if not conn.execute(
                        "SELECT 1 FROM gptwf_queries WHERE execution_id=? AND query_id=?",
                        (execution_id, query_id),
                    ).fetchone():
                        raise WorkflowError("QUERY_NOT_FOUND", f"Unknown query_id: {query_id}", status_code=422)
                    conn.execute(
                        "INSERT OR IGNORE INTO gptwf_candidate_queries VALUES (?,?,?,?)",
                        (repository["repository_id"], repository["version"], link_candidate_id, query_id),
                    )
            execution_bytes = execution["storage_bytes"] + added_bytes
            if execution_bytes > self.config.execution_max_bytes:
                raise WorkflowError("EXECUTION_STORAGE_LIMIT", "Execution byte limit would be exceeded.", status_code=413)
            counts = conn.execute(
                """
                SELECT COUNT(*) AS candidates,COUNT(DISTINCT NULLIF(process_number,'')) AS processes
                FROM gptwf_candidates WHERE repository_id=? AND repository_version=?
                """,
                (repository["repository_id"], repository["version"]),
            ).fetchone()
            conn.execute(
                """
                UPDATE gptwf_repositories SET candidate_count=?,unique_process_count=?
                WHERE repository_id=? AND version=?
                """,
                (counts["candidates"], counts["processes"], repository["repository_id"], repository["version"]),
            )
            conn.execute(
                "UPDATE gptwf_executions SET storage_bytes=?,updated_at=? WHERE execution_id=?",
                (execution_bytes, utc_now(), execution_id),
            )
            if self._execution(conn, execution_id)["state"] == "DISCOVERY_OPEN":
                self._transition(conn, execution_id, "CANDIDATES_REGISTERED")
            self._set_release(conn, execution_id, "sources_release")
            self._event(conn, execution_id, "candidates_registered", summary={"inserted": inserted, "reused": reused})
            return {
                "execution_id": execution_id,
                "state": "CANDIDATES_REGISTERED",
                "repository": {
                    "repository_id": repository["repository_id"],
                    "repository_version": repository["version"],
                    "status": "open",
                    "candidate_count": counts["candidates"],
                    "unique_process_count": counts["processes"],
                },
                "inserted": inserted,
                "deduplicated": reused,
            }, 200

        return self._mutate("submit_candidates", idempotency_key, {"execution_id": execution_id, **payload}, submit)

    def freeze_repository(
        self, execution_id: str, payload: dict[str, Any], idempotency_key: str
    ) -> tuple[dict[str, Any], int, bool]:
        def freeze(conn: sqlite3.Connection) -> tuple[dict[str, Any], int]:
            execution = self._execution(conn, execution_id)
            if execution["state"] != "CANDIDATES_REGISTERED":
                raise WorkflowError("INVALID_STATE_TRANSITION", "Repository can only be frozen after candidates are registered.")
            repository = self._repository(conn, execution_id)
            rows = conn.execute(
                """
                SELECT candidate_id,content_hash,process_number,final_url FROM gptwf_candidates
                WHERE repository_id=? AND repository_version=?
                ORDER BY candidate_id,content_hash,COALESCE(process_number,''),COALESCE(final_url,'')
                """,
                (repository["repository_id"], repository["version"]),
            ).fetchall()
            if not rows:
                raise WorkflowError("EMPTY_REPOSITORY", "An empty repository cannot be frozen.")
            manifest = [dict(row) for row in rows]
            content_hash = digest(manifest)
            frozen_at = utc_now()
            conn.execute(
                """
                UPDATE gptwf_repositories SET status='frozen',content_hash=?,frozen_at=?
                WHERE repository_id=? AND version=?
                """,
                (content_hash, frozen_at, repository["repository_id"], repository["version"]),
            )
            total = (len(rows) + self.config.batch_size - 1) // self.config.batch_size
            batches = []
            for index in range(total):
                candidate_ids = [row["candidate_id"] for row in rows[index * self.config.batch_size:(index + 1) * self.config.batch_size]]
                batch_id = f"BATCH-{digest([repository['repository_id'], repository['version'], index, candidate_ids])[:16].upper()}"
                conn.execute(
                    "INSERT INTO gptwf_batches VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        batch_id,
                        repository["repository_id"],
                        repository["version"],
                        index + 1,
                        total,
                        canonical(candidate_ids),
                        content_hash,
                        "pending",
                        frozen_at,
                    ),
                )
                batches.append({"batch_id": batch_id, "index": index + 1, "candidate_ids": candidate_ids})
            receipt = {
                "repository_id": repository["repository_id"],
                "execution_id": execution_id,
                "repository_version": repository["version"],
                "candidate_count": len(rows),
                "content_hash": content_hash,
                "batch_count": total,
                "frozen_at": frozen_at,
            }
            receipt["receipt_hash"] = digest(receipt)
            conn.execute(
                "INSERT INTO gptwf_receipts VALUES (?,?,?,?,?,?)",
                (identifier("RCT"), execution_id, "repository", receipt["receipt_hash"], canonical(receipt), frozen_at),
            )
            self._transition(conn, execution_id, "REPOSITORY_FROZEN")
            self._set_release(conn, execution_id, "repository_release")
            return {"repository_receipt": receipt, "batches": batches, "state": "REPOSITORY_FROZEN"}, 200

        return self._mutate("freeze_repository", idempotency_key, {"execution_id": execution_id, **payload}, freeze)

    def get_batch(self, repository_id: str, batch_id: str) -> dict[str, Any]:
        with self.storage.session() as conn:
            batch = conn.execute(
                "SELECT * FROM gptwf_batches WHERE repository_id=? AND batch_id=?",
                (repository_id, batch_id),
            ).fetchone()
            if not batch:
                raise WorkflowError("BATCH_NOT_FOUND", "Batch does not exist.", status_code=404)
            candidates = conn.execute(
                f"""
                SELECT c.metadata_json,d.normalized_json,c.content_hash
                FROM gptwf_candidates c
                JOIN gptwf_documents d ON d.content_hash=c.content_hash
                WHERE c.repository_id=? AND c.repository_version=? AND c.candidate_id IN
                ({','.join('?' for _ in json.loads(batch['candidate_ids_json']))})
                ORDER BY c.candidate_id
                """,
                (repository_id, batch["repository_version"], *json.loads(batch["candidate_ids_json"])),
            ).fetchall()
            return {
                "batch_id": batch_id,
                "repository_id": repository_id,
                "repository_version": batch["repository_version"],
                "index": batch["batch_index"],
                "total_batches": batch["total_batches"],
                "repository_hash": batch["repository_hash"],
                "status": batch["status"],
                "candidates": [
                    {
                        **json.loads(row["normalized_json"]),
                        **json.loads(row["metadata_json"]),
                        "content_hash": row["content_hash"],
                    }
                    for row in candidates
                ],
            }

    def submit_selection(
        self, repository_id: str, payload: dict[str, Any], idempotency_key: str
    ) -> tuple[dict[str, Any], int, bool]:
        def submit(conn: sqlite3.Connection) -> tuple[dict[str, Any], int]:
            batch_id = str(payload.get("batch_id", ""))
            version = int(payload.get("repository_version", 0))
            if payload.get("repository_id") != repository_id:
                raise WorkflowError("REPOSITORY_MISMATCH", "Repository path and body do not match.", status_code=422)
            batch = conn.execute(
                "SELECT * FROM gptwf_batches WHERE batch_id=? AND repository_id=? AND repository_version=?",
                (batch_id, repository_id, version),
            ).fetchone()
            if not batch:
                raise WorkflowError("BATCH_REPOSITORY_MISMATCH", "Batch does not belong to the repository/version.")
            repository = conn.execute(
                "SELECT * FROM gptwf_repositories WHERE repository_id=? AND version=?",
                (repository_id, version),
            ).fetchone()
            execution_id = repository["execution_id"]
            execution = self._execution(conn, execution_id)
            if execution["state"] not in {"REPOSITORY_FROZEN", "SEMANTIC_SELECTION_COMPLETED"}:
                raise WorkflowError("REPOSITORY_NOT_FROZEN", "Semantic selection requires a frozen repository.")
            assessments = payload.get("assessments")
            if not isinstance(assessments, list):
                raise WorkflowError("SELECTION_INCOMPLETE", "assessments must be an array.", status_code=422)
            expected = set(json.loads(batch["candidate_ids_json"]))
            observed = [str(item.get("candidate_id", "")) for item in assessments]
            if set(observed) != expected or len(observed) != len(set(observed)):
                raise WorkflowError(
                    "SELECTION_INCOMPLETE",
                    "Assessments must cover every batch candidate exactly once.",
                    status_code=422,
                    details={"expected_candidate_ids": sorted(expected)},
                )
            for item in assessments:
                if item.get("identity_status") not in IDENTITY_STATUSES:
                    raise WorkflowError("INVALID_SELECTION_ENUM", "Invalid identity_status.", status_code=422)
                if not item.get("reason") or not item.get("evidence_excerpt_ids"):
                    raise WorkflowError("SELECTION_EVIDENCE_REQUIRED", "Selection reason and evidence are required.", status_code=422)
            conn.execute(
                "INSERT INTO gptwf_selections VALUES (?,?,?,?,?)",
                (repository_id, version, batch_id, canonical(payload), utc_now()),
            )
            conn.execute("UPDATE gptwf_batches SET status='processed' WHERE batch_id=?", (batch_id,))
            remaining = conn.execute(
                "SELECT COUNT(*) FROM gptwf_batches WHERE repository_id=? AND repository_version=? AND status!='processed'",
                (repository_id, version),
            ).fetchone()[0]
            completed = remaining == 0
            if completed and execution["state"] == "REPOSITORY_FROZEN":
                self._transition(conn, execution_id, "SEMANTIC_SELECTION_COMPLETED")
                self._set_release(conn, execution_id, "selection_release")
            self._event(conn, execution_id, "semantic_selection_registered", summary={"batch_id": batch_id, "complete": completed})
            return {
                "execution_id": execution_id,
                "repository_id": repository_id,
                "repository_version": version,
                "batch_id": batch_id,
                "selection_complete": completed,
                "remaining_batches": remaining,
                "state": "SEMANTIC_SELECTION_COMPLETED" if completed else "REPOSITORY_FROZEN",
            }, 200

        return self._mutate("submit_selection", idempotency_key, payload, submit)

    def submit_verifications(
        self, execution_id: str, payload: dict[str, Any], idempotency_key: str
    ) -> tuple[dict[str, Any], int, bool]:
        items = payload.get("verifications")
        if not isinstance(items, list) or not items:
            raise WorkflowError("INVALID_VERIFICATION_BATCH", "verifications must be a non-empty array.", status_code=422)

        def submit(conn: sqlite3.Connection) -> tuple[dict[str, Any], int]:
            execution = self._execution(conn, execution_id)
            if execution["state"] not in {"SEMANTIC_SELECTION_COMPLETED", "FINALISTS_VERIFIED"}:
                raise WorkflowError("SELECTION_INCOMPLETE", "Finalists cannot be verified before semantic selection completes.")
            repository = self._repository(conn, execution_id)
            for item in items:
                candidate_id = str(item.get("candidate_id", ""))
                if item.get("verification_status") not in VERIFICATION_STATUSES:
                    raise WorkflowError("INVALID_VERIFICATION", "Invalid verification_status.", status_code=422)
                if not conn.execute(
                    """
                    SELECT 1 FROM gptwf_candidates WHERE repository_id=? AND repository_version=? AND candidate_id=?
                    """,
                    (repository["repository_id"], repository["version"], candidate_id),
                ).fetchone():
                    raise WorkflowError("CANDIDATE_NOT_IN_REPOSITORY", f"Unknown candidate: {candidate_id}", status_code=422)
                conn.execute(
                    "INSERT OR REPLACE INTO gptwf_verifications VALUES (?,?,?,?)",
                    (execution_id, candidate_id, canonical(item), utc_now()),
                )
            main_candidates: set[str] = set()
            selections = conn.execute(
                "SELECT selection_json FROM gptwf_selections WHERE repository_id=? AND repository_version=?",
                (repository["repository_id"], repository["version"]),
            ).fetchall()
            for selection in selections:
                for assessment in json.loads(selection["selection_json"])["assessments"]:
                    if assessment.get("preliminary_bucket") == "main_candidate":
                        main_candidates.add(assessment["candidate_id"])
            verified = {
                row["candidate_id"]
                for row in conn.execute(
                    "SELECT candidate_id,verification_json FROM gptwf_verifications WHERE execution_id=?",
                    (execution_id,),
                ).fetchall()
                if json.loads(row["verification_json"]).get("verification_status") == "verified"
            }
            missing = sorted(main_candidates - verified)
            completed = not missing
            if completed and execution["state"] == "SEMANTIC_SELECTION_COMPLETED":
                self._transition(conn, execution_id, "FINALISTS_VERIFIED")
            self._event(conn, execution_id, "finalist_verifications_registered", summary={"complete": completed, "missing_count": len(missing)})
            return {
                "execution_id": execution_id,
                "verification_complete": completed,
                "missing_candidate_ids": missing,
                "state": "FINALISTS_VERIFIED" if completed else "SEMANTIC_SELECTION_COMPLETED",
            }, 200

        return self._mutate("submit_verifications", idempotency_key, {"execution_id": execution_id, **payload}, submit)

    def admit_sample(
        self, execution_id: str, payload: dict[str, Any], idempotency_key: str
    ) -> tuple[dict[str, Any], int, bool]:
        entries = payload.get("candidates")
        if not isinstance(entries, list):
            raise WorkflowError("INVALID_SAMPLE", "candidates must be an array.", status_code=422)

        def admit(conn: sqlite3.Connection) -> tuple[dict[str, Any], int]:
            execution = self._execution(conn, execution_id)
            if execution["state"] != "FINALISTS_VERIFIED":
                raise WorkflowError("FINALIST_NOT_VERIFIED", "Sample admission requires completed finalist verification.")
            repository = self._repository(conn, execution_id)
            ids: set[str] = set()
            for entry in entries:
                candidate_id = str(entry.get("candidate_id", ""))
                bucket = entry.get("bucket")
                if bucket not in BUCKETS or not candidate_id or candidate_id in ids:
                    raise WorkflowError("INVALID_SAMPLE", "Candidate IDs and buckets must be valid and unique.", status_code=422)
                ids.add(candidate_id)
                if not conn.execute(
                    "SELECT 1 FROM gptwf_candidates WHERE repository_id=? AND repository_version=? AND candidate_id=?",
                    (repository["repository_id"], repository["version"], candidate_id),
                ).fetchone():
                    raise WorkflowError("CANDIDATE_NOT_IN_REPOSITORY", f"Unknown candidate: {candidate_id}", status_code=422)
                if bucket == "main":
                    row = conn.execute(
                        "SELECT verification_json FROM gptwf_verifications WHERE execution_id=? AND candidate_id=?",
                        (execution_id, candidate_id),
                    ).fetchone()
                    verification = json.loads(row["verification_json"]) if row else {}
                    if verification.get("verification_status") != "verified":
                        raise WorkflowError("FINALIST_NOT_VERIFIED", f"Main candidate is not verified: {candidate_id}")
                    if (verification.get("relator") or {}).get("status") != "confirmed":
                        raise WorkflowError("MAIN_RELATOR_NOT_CONFIRMED", f"Main candidate has no confirmed relator: {candidate_id}")
            stored = {
                "repository_id": repository["repository_id"],
                "repository_version": repository["version"],
                **payload,
            }
            conn.execute(
                "INSERT OR REPLACE INTO gptwf_samples VALUES (?,?,?,?,?)",
                (execution_id, repository["repository_id"], repository["version"], canonical(stored), utc_now()),
            )
            self._transition(conn, execution_id, "SAMPLE_ADMITTED")
            self._set_release(conn, execution_id, "sample_release")
            receipt = {"execution_id": execution_id, "sample_hash": digest(stored), "admitted_at": utc_now()}
            receipt["receipt_hash"] = digest(receipt)
            conn.execute(
                "INSERT INTO gptwf_receipts VALUES (?,?,?,?,?,?)",
                (identifier("RCT"), execution_id, "sample", receipt["receipt_hash"], canonical(receipt), utc_now()),
            )
            return {"execution_id": execution_id, "state": "SAMPLE_ADMITTED", "sample_receipt": receipt}, 200

        return self._mutate("admit_sample", idempotency_key, {"execution_id": execution_id, **payload}, admit)

    def resolve_claims(
        self, execution_id: str, payload: dict[str, Any], idempotency_key: str
    ) -> tuple[dict[str, Any], int, bool]:
        claims = payload.get("claims")
        if not isinstance(claims, list) or not claims:
            raise WorkflowError("INVALID_CLAIMS", "claims must be a non-empty array.", status_code=422)

        def resolve(conn: sqlite3.Connection) -> tuple[dict[str, Any], int]:
            execution = self._execution(conn, execution_id)
            if execution["state"] != "SAMPLE_ADMITTED":
                raise WorkflowError("SAMPLE_BLOCKED", "Claims require an admitted sample.")
            seen: set[str] = set()
            required = {
                "claim_id",
                "status",
                "allowed_scope",
                "evidence_ids",
                "authorized_processes",
                "authorized_amounts",
                "authorized_dates",
                "authorized_summulas",
                "forbidden_inferences",
            }
            for claim in claims:
                if not required.issubset(claim):
                    raise WorkflowError("INVALID_CLAIM", "Claim is missing required authorization fields.", status_code=422)
                if claim["status"] not in CLAIM_STATES or claim["claim_id"] in seen:
                    raise WorkflowError("INVALID_CLAIM", "Claim state or identifier is invalid.", status_code=422)
                if claim["status"] in {"supported", "context_only"} and not claim["evidence_ids"]:
                    raise WorkflowError("CLAIM_EVIDENCE_REQUIRED", "Supported claims require evidence.", status_code=422)
                seen.add(claim["claim_id"])
                conn.execute(
                    "INSERT INTO gptwf_claims VALUES (?,?,?,?)",
                    (execution_id, claim["claim_id"], canonical(claim), utc_now()),
                )
            self._transition(conn, execution_id, "CLAIMS_RESOLVED")
            self._set_release(conn, execution_id, "claims_release")
            receipt = {"execution_id": execution_id, "claims_hash": digest(claims), "claim_count": len(claims), "resolved_at": utc_now()}
            receipt["receipt_hash"] = digest(receipt)
            conn.execute(
                "INSERT INTO gptwf_receipts VALUES (?,?,?,?,?,?)",
                (identifier("RCT"), execution_id, "claims", receipt["receipt_hash"], canonical(receipt), utc_now()),
            )
            return {"execution_id": execution_id, "state": "CLAIMS_RESOLVED", "claims_receipt": receipt}, 200

        return self._mutate("resolve_claims", idempotency_key, {"execution_id": execution_id, **payload}, resolve)

    @staticmethod
    def _entities(text: str) -> dict[str, list[str]]:
        return {
            "processes": sorted(set(PROCESS_RE.findall(text))),
            "amounts": sorted(set(AMOUNT_RE.findall(text))),
            "dates": sorted(set(DATE_RE.findall(text))),
            "summulas": sorted(set(SUMULA_RE.findall(text))),
            "articles": sorted(set(ARTICLE_RE.findall(text))),
            "percentages": sorted(set(PERCENT_RE.findall(text))),
            "years": sorted(set(YEAR_RE.findall(text))),
            "chambers": sorted(set(CHAMBER_RE.findall(text))),
            "magistrates": sorted(set(MAGISTRATE_RE.findall(text))),
            "trend_language": sorted({pattern for pattern in TREND_PATTERNS if re.search(pattern, text, re.IGNORECASE)}),
        }

    def audit_draft(
        self, execution_id: str, payload: dict[str, Any], idempotency_key: str
    ) -> tuple[dict[str, Any], int, bool]:
        draft_text = str(payload.get("draft_text", ""))
        if not draft_text:
            raise WorkflowError("INVALID_DRAFT", "draft_text is required.", status_code=422)
        draft_size = len(draft_text.encode("utf-8"))
        if draft_size > self.config.draft_max_bytes:
            raise WorkflowError("PAYLOAD_TOO_LARGE", "Draft exceeds its configured limit.", status_code=413)

        def audit(conn: sqlite3.Connection) -> tuple[dict[str, Any], int]:
            execution = self._execution(conn, execution_id)
            draft_hash = digest(draft_text)
            if execution["state"] == "ANSWER_RELEASED":
                existing = conn.execute(
                    "SELECT draft_hash FROM gptwf_drafts WHERE execution_id=? ORDER BY created_at DESC LIMIT 1",
                    (execution_id,),
                ).fetchone()
                if not existing or existing["draft_hash"] != draft_hash:
                    raise WorkflowError("DRAFT_CHANGED_AFTER_RELEASE", "Released draft is immutable.")
            elif execution["state"] not in {"CLAIMS_RESOLVED", "DRAFT_SUBMITTED"}:
                raise WorkflowError("CLAIMS_INCOMPLETE", "Draft audit requires resolved claims.")
            repository = self._repository(conn, execution_id)
            if payload.get("repository_id") != repository["repository_id"] or int(payload.get("repository_version", 0)) != repository["version"]:
                raise WorkflowError("REPOSITORY_MISMATCH", "Draft references a different repository/version.")
            claims = {
                row["claim_id"]: json.loads(row["claim_json"])
                for row in conn.execute(
                    "SELECT claim_id,claim_json FROM gptwf_claims WHERE execution_id=?", (execution_id,)
                ).fetchall()
            }
            violations: list[dict[str, Any]] = []
            statements = payload.get("statements") or []
            referenced_claims: list[dict[str, Any]] = []
            for statement in statements:
                claim_id = statement.get("claim_id")
                if claim_id not in claims:
                    violations.append({"code": "UNREGISTERED_CLAIM", "statement_id": statement.get("statement_id")})
                    continue
                claim = claims[claim_id]
                referenced_claims.append(claim)
                if not set(statement.get("evidence_ids") or []).issubset(set(claim.get("evidence_ids") or [])):
                    violations.append({"code": "UNAUTHORIZED_EVIDENCE", "claim_id": claim_id})
                if claim["status"] in {"abstain", "not_requested"}:
                    violations.append({"code": "CLAIM_SCOPE_VIOLATION", "claim_id": claim_id})
                statement_entities = self._entities(str(statement.get("text", "")))
                declared = statement.get("entities") or {}
                checks = (
                    ("processes", "authorized_processes", "UNAUTHORIZED_PROCESS"),
                    ("amounts", "authorized_amounts", "UNAUTHORIZED_AMOUNT"),
                    ("dates", "authorized_dates", "UNAUTHORIZED_DATE"),
                    ("summulas", "authorized_summulas", "UNAUTHORIZED_SUMULA"),
                    ("chambers", "authorized_chambers", "UNAUTHORIZED_CHAMBER"),
                    ("magistrates", "authorized_magistrates", "UNAUTHORIZED_MAGISTRATE"),
                )
                for entity_key, authorization_key, code in checks:
                    observed = set(statement_entities[entity_key]) | {str(x) for x in declared.get(entity_key, [])}
                    authorized = {str(x) for x in claim.get(authorization_key, [])}
                    for value in sorted(observed - authorized):
                        violations.append({"code": code, "claim_id": claim_id, "value": value})
                if statement_entities["trend_language"] or statement_entities["percentages"]:
                    scope = str(claim.get("allowed_scope", "")).lower()
                    if claim["status"] != "supported" or not any(word in scope for word in ("trend", "frequency", "percentage", "temporal")):
                        violations.append({"code": "UNAUTHORIZED_TREND", "claim_id": claim_id})
                if claim["status"] == "context_only" and (
                    statement_entities["percentages"] or statement_entities["trend_language"]
                ):
                    violations.append({"code": "CONTEXT_USED_AS_SAMPLE", "claim_id": claim_id})
            all_entities = self._entities(draft_text)
            authorizations = {
                "processes": {str(x) for claim in referenced_claims for x in claim.get("authorized_processes", [])},
                "amounts": {str(x) for claim in referenced_claims for x in claim.get("authorized_amounts", [])},
                "dates": {str(x) for claim in referenced_claims for x in claim.get("authorized_dates", [])},
                "summulas": {str(x) for claim in referenced_claims for x in claim.get("authorized_summulas", [])},
                "chambers": {str(x) for claim in referenced_claims for x in claim.get("authorized_chambers", [])},
                "magistrates": {str(x) for claim in referenced_claims for x in claim.get("authorized_magistrates", [])},
            }
            for entity_key, code in (
                ("processes", "UNAUTHORIZED_PROCESS"),
                ("amounts", "UNAUTHORIZED_AMOUNT"),
                ("dates", "UNAUTHORIZED_DATE"),
                ("summulas", "UNAUTHORIZED_SUMULA"),
                ("chambers", "UNAUTHORIZED_CHAMBER"),
                ("magistrates", "UNAUTHORIZED_MAGISTRATE"),
            ):
                for value in sorted(set(all_entities[entity_key]) - authorizations[entity_key]):
                    finding = {"code": code, "value": value}
                    if finding not in violations:
                        violations.append(finding)
            if all_entities["trend_language"] and not any(
                claim["status"] == "supported"
                and any(word in str(claim.get("allowed_scope", "")).lower() for word in ("trend", "frequency", "temporal"))
                for claim in referenced_claims
            ):
                violations.append({"code": "UNAUTHORIZED_TREND"})
            released = not violations
            result = {
                "execution_id": execution_id,
                "repository_id": repository["repository_id"],
                "repository_version": repository["version"],
                "draft_hash": draft_hash,
                "status": "released" if released else "blocked",
                "violations": violations,
                "extracted_entities": all_entities,
                "releases": {**json.loads(execution["releases_json"]), "answer_release": 1 if released else 0},
                "audited_at": utc_now(),
            }
            conn.execute(
                "INSERT INTO gptwf_drafts VALUES (?,?,?,?,?,?,?)",
                (execution_id, draft_hash, repository["repository_id"], repository["version"], draft_text, canonical(result), utc_now()),
            )
            self._transition(conn, execution_id, "DRAFT_SUBMITTED")
            if released:
                self._transition(conn, execution_id, "ANSWER_RELEASED")
                self._set_release(conn, execution_id, "answer_release")
                conn.execute(
                    "UPDATE gptwf_executions SET retention_state='FINALIZED' WHERE execution_id=?",
                    (execution_id,),
                )
            self._event(conn, execution_id, "draft_audited", summary={"released": released, "violation_count": len(violations), "draft_hash": draft_hash})
            return result, 200

        return self._mutate("audit_draft", idempotency_key, {"execution_id": execution_id, **payload}, audit)

    def get_execution(self, execution_id: str) -> dict[str, Any]:
        with self.storage.session() as conn:
            execution = self._execution(conn, execution_id)
            repository = conn.execute(
                "SELECT * FROM gptwf_repositories WHERE execution_id=? ORDER BY version DESC LIMIT 1",
                (execution_id,),
            ).fetchone()
            blockers: list[str] = []
            state = execution["state"]
            if state in {"CREATED", "PLANNED"}:
                blockers.append("DISCOVERY_INCOMPLETE")
            if state in {"DISCOVERY_OPEN", "CANDIDATES_REGISTERED"}:
                blockers.append("REPOSITORY_NOT_FROZEN")
            if state == "REPOSITORY_FROZEN":
                blockers.append("SELECTION_INCOMPLETE")
            if state == "SEMANTIC_SELECTION_COMPLETED":
                blockers.append("FINALIST_NOT_VERIFIED")
            if state == "FINALISTS_VERIFIED":
                blockers.append("SAMPLE_BLOCKED")
            if state == "SAMPLE_ADMITTED":
                blockers.append("CLAIMS_INCOMPLETE")
            if state in {"CLAIMS_RESOLVED", "DRAFT_SUBMITTED"}:
                blockers.append("DRAFT_BLOCKED")
            return {
                "execution_id": execution_id,
                "state": state,
                "retention_state": execution["retention_state"],
                "workflow_receipt": json.loads(execution["receipt_json"]),
                "releases": json.loads(execution["releases_json"]),
                "repository": dict(repository) if repository else None,
                "blockers": blockers,
                "storage_bytes": execution["storage_bytes"],
                "created_at": execution["created_at"],
                "updated_at": execution["updated_at"],
            }

    def get_release(self, execution_id: str) -> dict[str, Any]:
        with self.storage.session() as conn:
            execution = self._execution(conn, execution_id)
            latest = conn.execute(
                "SELECT audit_json FROM gptwf_drafts WHERE execution_id=? ORDER BY created_at DESC LIMIT 1",
                (execution_id,),
            ).fetchone()
            return {
                "execution_id": execution_id,
                "state": execution["state"],
                "releases": json.loads(execution["releases_json"]),
                "latest_audit": json.loads(latest["audit_json"]) if latest else None,
            }

    def health(self) -> dict[str, Any]:
        try:
            with self.storage.session() as conn:
                conn.execute("SELECT 1").fetchone()
            database = "ok"
        except sqlite3.Error:
            database = "error"
        return {
            "status": "ok" if database == "ok" else "degraded",
            "database": database,
            "storage": self.storage.disk_status(),
            "time": utc_now(),
        }

    def cleanup(
        self, payload: dict[str, Any], idempotency_key: str
    ) -> tuple[dict[str, Any], int, bool]:
        def clean(conn: sqlite3.Connection) -> tuple[dict[str, Any], int]:
            now = utc_now()
            conn.execute(
                """
                UPDATE gptwf_executions SET retention_state='EXPIRED',updated_at=?
                WHERE retention_state='FINALIZED' AND expires_at IS NOT NULL AND expires_at < ?
                """,
                (now, now),
            )
            expired_keys = conn.execute(
                "DELETE FROM gptwf_idempotency WHERE expires_at < ?", (now,)
            ).rowcount
            candidates = conn.execute(
                """
                SELECT execution_id FROM gptwf_executions
                WHERE retention_state IN ('EXPIRED','TEMPORARY') AND state NOT IN
                ('CREATED','PLANNED','DISCOVERY_OPEN','CANDIDATES_REGISTERED',
                 'REPOSITORY_FROZEN','SEMANTIC_SELECTION_COMPLETED','FINALISTS_VERIFIED',
                 'SAMPLE_ADMITTED','CLAIMS_RESOLVED','DRAFT_SUBMITTED')
                """
            ).fetchall()
            cleaned: list[str] = []
            for row in candidates:
                execution_id = row["execution_id"]
                for table in (
                    "gptwf_candidate_queries",
                    "gptwf_batches",
                    "gptwf_selections",
                    "gptwf_verifications",
                    "gptwf_samples",
                    "gptwf_claims",
                    "gptwf_drafts",
                ):
                    if table in {"gptwf_candidate_queries", "gptwf_batches", "gptwf_selections"}:
                        repository_ids = [
                            item["repository_id"]
                            for item in conn.execute(
                                "SELECT repository_id FROM gptwf_repositories WHERE execution_id=?",
                                (execution_id,),
                            ).fetchall()
                        ]
                        for repository_id in repository_ids:
                            conn.execute(f"DELETE FROM {table} WHERE repository_id=?", (repository_id,))
                    else:
                        conn.execute(f"DELETE FROM {table} WHERE execution_id=?", (execution_id,))
                conn.execute("DELETE FROM gptwf_candidates WHERE execution_id=?", (execution_id,))
                conn.execute(
                    "UPDATE gptwf_executions SET retention_state='AUDIT_MINIMUM',storage_bytes=0,updated_at=? WHERE execution_id=?",
                    (now, execution_id),
                )
                conn.execute(
                    "INSERT INTO gptwf_deletions(execution_id,deleted_categories_json,created_at) VALUES (?,?,?)",
                    (
                        execution_id,
                        canonical(["candidates", "batches", "selections", "verifications", "sample", "claims", "drafts"]),
                        now,
                    ),
                )
                cleaned.append(execution_id)
            conn.execute(
                """
                DELETE FROM gptwf_documents WHERE content_hash NOT IN
                (SELECT DISTINCT content_hash FROM gptwf_candidates)
                """
            )
            self.storage.logger.info("event=cleanup cleaned_executions=%s expired_idempotency=%s", len(cleaned), expired_keys)
            return {"cleaned_execution_ids": cleaned, "expired_idempotency_keys": expired_keys, "completed_at": now}, 200

        return self._mutate("cleanup", idempotency_key, payload, clean)
