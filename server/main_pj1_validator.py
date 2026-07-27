"""PATRON v14.2 + PJ1 research plan + deterministic validation route."""
from __future__ import annotations
import hmac
import os
from pathlib import Path
from typing import Any
from fastapi import Depends, HTTPException, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from server.main_pj1 import app
from server.pj1_validation.service import (
    IdempotencyConflictError,
    RequestContractError,
    ResponseContractError,
    SQLiteIdempotencyStore,
    ValidationService,
)

BASE_DIR = Path(__file__).resolve().parent
SERVICE_TOKEN = os.getenv("PJ1_API_BEARER_TOKEN", "")
IDEMPOTENCY_DB = Path(os.getenv("PJ1_IDEMPOTENCY_DB", os.getenv("DB_PATH", str(BASE_DIR / "server_data.db"))))
service = ValidationService(
    contract_path=BASE_DIR / "pj1_validation" / "pj1_validation_contract_v1.schema.json",
    store=SQLiteIdempotencyStore(IDEMPOTENCY_DB),
)
bearer = HTTPBearer(auto_error=False)

def authorize_service(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> None:
    if not SERVICE_TOKEN:
        raise HTTPException(status_code=503, detail={"code": "service_token_not_configured"})
    if credentials is None or credentials.scheme.lower() != "bearer" or not hmac.compare_digest(credentials.credentials, SERVICE_TOKEN):
        raise HTTPException(status_code=401, detail={"code": "invalid_service_token"}, headers={"WWW-Authenticate": "Bearer"})

@app.post("/v1/pj1/validate", operation_id="validatePJ1Response")
def validate_pj1_response(payload: dict[str, Any], response: Response, _: None = Depends(authorize_service)) -> dict[str, Any]:
    try:
        result, replayed = service.validate(payload)
    except RequestContractError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_validation_request", "errors": exc.errors}) from exc
    except IdempotencyConflictError as exc:
        raise HTTPException(status_code=409, detail={"code": "idempotency_conflict", "message": str(exc)}) from exc
    except ResponseContractError as exc:
        raise HTTPException(status_code=500, detail={"code": "invalid_validation_response"}) from exc
    response.headers["X-PJ1-Idempotent-Replay"] = "true" if replayed else "false"
    return result
