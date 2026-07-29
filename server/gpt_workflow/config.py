from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _integer(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _floating(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


@dataclass(frozen=True)
class WorkflowConfig:
    db_path: Path
    log_path: Path
    bearer_token: str = ""
    workflow_version: str = "precedent_mapping-3.3.0"
    runtime_version: str = "3.3.0"
    contract_version: str = "1.0.0"
    candidate_max_bytes: int = 64 * 1024
    excerpt_max_bytes: int = 8 * 1024
    excerpts_max_count: int = 8
    request_max_bytes: int = 512 * 1024
    draft_max_bytes: int = 128 * 1024
    execution_max_bytes: int = 50 * 1024 * 1024
    candidates_max_count: int = 5_000
    repository_versions_max: int = 10
    batch_size: int = 15
    log_max_bytes: int = 5 * 1024 * 1024
    log_backup_count: int = 3
    temporary_retention_days: int = 7
    finalized_retention_days: int = 90
    idempotency_retention_days: int = 30
    disk_warning_percent: float = 70.0
    disk_restricted_percent: float = 85.0
    disk_critical_percent: float = 95.0
    simulated_disk_percent: float | None = None

    @classmethod
    def from_env(cls, base_dir: Path) -> "WorkflowConfig":
        data_dir = Path(os.getenv("GPT_WORKFLOW_DATA_DIR", str(base_dir / "gpt_workflow_data")))
        simulated = os.getenv("GPT_WORKFLOW_SIMULATED_DISK_PERCENT")
        batch_size = max(5, min(25, _integer("GPT_WORKFLOW_BATCH_SIZE", 15)))
        return cls(
            db_path=Path(os.getenv("GPT_WORKFLOW_DB", str(data_dir / "workflow.db"))),
            log_path=Path(os.getenv("GPT_WORKFLOW_LOG", str(data_dir / "workflow.log"))),
            bearer_token=os.getenv("GPT_WORKFLOW_API_BEARER_TOKEN", ""),
            candidate_max_bytes=_integer("GPT_WORKFLOW_CANDIDATE_MAX_BYTES", 64 * 1024),
            excerpt_max_bytes=_integer("GPT_WORKFLOW_EXCERPT_MAX_BYTES", 8 * 1024),
            excerpts_max_count=_integer("GPT_WORKFLOW_EXCERPTS_MAX_COUNT", 8),
            request_max_bytes=_integer("GPT_WORKFLOW_REQUEST_MAX_BYTES", 512 * 1024),
            draft_max_bytes=_integer("GPT_WORKFLOW_DRAFT_MAX_BYTES", 128 * 1024),
            execution_max_bytes=_integer("GPT_WORKFLOW_EXECUTION_MAX_BYTES", 50 * 1024 * 1024),
            candidates_max_count=_integer("GPT_WORKFLOW_CANDIDATES_MAX_COUNT", 5_000),
            repository_versions_max=_integer("GPT_WORKFLOW_REPOSITORY_VERSIONS_MAX", 10),
            batch_size=batch_size,
            log_max_bytes=_integer("GPT_WORKFLOW_LOG_MAX_BYTES", 5 * 1024 * 1024),
            log_backup_count=_integer("GPT_WORKFLOW_LOG_BACKUP_COUNT", 3),
            temporary_retention_days=_integer("GPT_WORKFLOW_TEMPORARY_RETENTION_DAYS", 7),
            finalized_retention_days=_integer("GPT_WORKFLOW_FINALIZED_RETENTION_DAYS", 90),
            idempotency_retention_days=_integer("GPT_WORKFLOW_IDEMPOTENCY_RETENTION_DAYS", 30),
            disk_warning_percent=_floating("GPT_WORKFLOW_DISK_WARNING_PERCENT", 70),
            disk_restricted_percent=_floating("GPT_WORKFLOW_DISK_RESTRICTED_PERCENT", 85),
            disk_critical_percent=_floating("GPT_WORKFLOW_DISK_CRITICAL_PERCENT", 95),
            simulated_disk_percent=float(simulated) if simulated is not None else None,
        )
