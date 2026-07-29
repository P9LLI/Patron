from __future__ import annotations

import hmac
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import WorkflowConfig
from .service import WorkflowService


BASE_DIR = Path(__file__).resolve().parents[1]
config = WorkflowConfig.from_env(BASE_DIR)
service = WorkflowService(config)
bearer = HTTPBearer(auto_error=False)
router = APIRouter(prefix="/gpt-workflow/v1", tags=["GPT Workflow v1"])


def authorize(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> None:
    if not config.bearer_token:
        raise HTTPException(status_code=503, detail={"error": "SERVICE_TOKEN_NOT_CONFIGURED"})
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not hmac.compare_digest(credentials.credentials, config.bearer_token)
    ):
        raise HTTPException(
            status_code=401,
            detail={"error": "INVALID_SERVICE_TOKEN"},
            headers={"WWW-Authenticate": "Bearer"},
        )


def mutation_response(
    response: Response,
    result: tuple[dict[str, Any], int, bool],
) -> dict[str, Any]:
    body, status_code, replayed = result
    response.status_code = status_code
    response.headers["X-GPT-Workflow-Idempotent-Replay"] = "true" if replayed else "false"
    return body


@router.post("/executions", operation_id="createGPTWorkflowExecution", dependencies=[Depends(authorize)])
def create_execution(
    payload: dict[str, Any],
    response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
) -> dict[str, Any]:
    return mutation_response(response, service.create_execution(payload, idempotency_key))


@router.post("/executions/{execution_id}/queries", operation_id="registerGPTWorkflowQueries", dependencies=[Depends(authorize)])
def register_queries(
    execution_id: str,
    payload: dict[str, Any],
    response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
) -> dict[str, Any]:
    return mutation_response(response, service.submit_queries(execution_id, payload, idempotency_key))


@router.post("/executions/{execution_id}/candidates", operation_id="registerGPTWorkflowCandidates", dependencies=[Depends(authorize)])
def register_candidates(
    execution_id: str,
    payload: dict[str, Any],
    response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
) -> dict[str, Any]:
    return mutation_response(response, service.submit_candidates(execution_id, payload, idempotency_key))


@router.post("/executions/{execution_id}/repositories/freeze", operation_id="freezeGPTWorkflowRepository", dependencies=[Depends(authorize)])
def freeze_repository(
    execution_id: str,
    payload: dict[str, Any],
    response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
) -> dict[str, Any]:
    return mutation_response(response, service.freeze_repository(execution_id, payload, idempotency_key))


@router.get("/repositories/{repository_id}/batches/{batch_id}", operation_id="getGPTWorkflowBatch", dependencies=[Depends(authorize)])
def get_batch(repository_id: str, batch_id: str) -> dict[str, Any]:
    return service.get_batch(repository_id, batch_id)


@router.post("/repositories/{repository_id}/semantic-selections", operation_id="submitGPTWorkflowSemanticSelection", dependencies=[Depends(authorize)])
def submit_semantic_selection(
    repository_id: str,
    payload: dict[str, Any],
    response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
) -> dict[str, Any]:
    return mutation_response(response, service.submit_selection(repository_id, payload, idempotency_key))


@router.post("/executions/{execution_id}/finalist-verifications", operation_id="submitGPTWorkflowFinalistVerifications", dependencies=[Depends(authorize)])
def submit_finalist_verifications(
    execution_id: str,
    payload: dict[str, Any],
    response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
) -> dict[str, Any]:
    return mutation_response(response, service.submit_verifications(execution_id, payload, idempotency_key))


@router.post("/executions/{execution_id}/sample", operation_id="admitGPTWorkflowSample", dependencies=[Depends(authorize)])
def admit_sample(
    execution_id: str,
    payload: dict[str, Any],
    response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
) -> dict[str, Any]:
    return mutation_response(response, service.admit_sample(execution_id, payload, idempotency_key))


@router.post("/executions/{execution_id}/claims", operation_id="resolveGPTWorkflowClaims", dependencies=[Depends(authorize)])
def resolve_claims(
    execution_id: str,
    payload: dict[str, Any],
    response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
) -> dict[str, Any]:
    return mutation_response(response, service.resolve_claims(execution_id, payload, idempotency_key))


@router.post("/executions/{execution_id}/audit-draft", operation_id="auditGPTWorkflowDraft", dependencies=[Depends(authorize)])
def audit_draft(
    execution_id: str,
    payload: dict[str, Any],
    response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
) -> dict[str, Any]:
    return mutation_response(response, service.audit_draft(execution_id, payload, idempotency_key))


@router.get("/executions/{execution_id}", operation_id="getGPTWorkflowExecution", dependencies=[Depends(authorize)])
def get_execution(execution_id: str) -> dict[str, Any]:
    return service.get_execution(execution_id)


@router.get("/executions/{execution_id}/release", operation_id="getGPTWorkflowRelease", dependencies=[Depends(authorize)])
def get_release(execution_id: str) -> dict[str, Any]:
    return service.get_release(execution_id)


@router.post("/admin/cleanup", operation_id="cleanupGPTWorkflowStorage", dependencies=[Depends(authorize)])
def cleanup(
    payload: dict[str, Any],
    response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
) -> dict[str, Any]:
    return mutation_response(response, service.cleanup(payload, idempotency_key))


@router.get("/health", operation_id="getGPTWorkflowHealth")
def health() -> dict[str, Any]:
    return service.health()
