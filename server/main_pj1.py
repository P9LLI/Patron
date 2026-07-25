"""PJ1 extension server for PATRON v14.2.

Run this module instead of ``server.main`` to add the protected PJ1 route.
The production module is imported unchanged, so every legacy endpoint and its
behavior remain available on the same FastAPI application.
"""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import quote_plus

from fastapi import Request
from pydantic import BaseModel, Field

from server.main import (
    BILLING_MODE,
    PUBLIC_BASE_URL,
    _build_mode,
    app,
    detect_extraction_attempt,
    is_blocked,
    is_rate_limited,
    is_subscription_active,
    log_abuse,
    log_event,
    normalize_oab_state,
    upsert_customer_map,
)
from server.patron_pj1_adapter import run_integrated


class ResearchPlanRequest(BaseModel):
    """Authenticated request for a PJ1 plan or corpus audit."""

    user_id: str = Field(..., min_length=1, max_length=256)
    message: Optional[str] = Field(default=None, max_length=4000)
    stripe_customer_id: Optional[str] = Field(default=None, max_length=256)
    stripe_email: Optional[str] = Field(default=None, max_length=320)
    oab_number: Optional[str] = Field(default=None, max_length=64)
    oab_state: Optional[str] = Field(default=None, max_length=8)
    v142: dict[str, Any]
    pj1: dict[str, Any] = Field(default_factory=dict)


def _request_text(payload: ResearchPlanRequest) -> str:
    """Build a bounded message for access classification and abuse checks."""

    values = [payload.message or ""]
    for source, key in (
        (payload.v142, "q"),
        (payload.v142, "cx"),
        (payload.v142, "of"),
        (payload.pj1, "query"),
        (payload.pj1, "legal_question"),
        (payload.pj1, "facts"),
    ):
        value = source.get(key)
        if value:
            values.append(str(value))
    return " ".join(values)[:4000]


def _authorize_research(payload: ResearchPlanRequest, request: Request, message: str) -> dict[str, Any] | None:
    """Apply the v14.2 security and subscription gates on every PJ1 call."""

    ip = request.client.host if request.client else None
    normalized_state = normalize_oab_state(payload.oab_state)

    if is_blocked(payload.user_id):
        log_event(user_id=payload.user_id, endpoint="pj1ResearchPlan", status="blocked", reason="user_blocked", ip=ip, message=message)
        return {"status": "blocked", "reason": "user_blocked"}

    if is_rate_limited(payload.user_id, "pj1ResearchPlan"):
        log_event(user_id=payload.user_id, endpoint="pj1ResearchPlan", status="blocked", reason="rate_limited", ip=ip, message=message)
        return {"status": "blocked", "reason": "rate_limited"}

    if payload.stripe_customer_id or payload.stripe_email:
        upsert_customer_map(payload.user_id, payload.stripe_customer_id, payload.stripe_email)

    if detect_extraction_attempt(message):
        log_abuse(user_id=payload.user_id, endpoint="pj1ResearchPlan", reason="extraction_suspected", ip=ip, message=message)
        log_event(user_id=payload.user_id, endpoint="pj1ResearchPlan", status="blocked", reason="extraction_suspected", ip=ip, message=message)
        return {"status": "blocked", "reason": "extraction_suspected"}

    if not is_subscription_active(
        payload.user_id,
        payload.stripe_customer_id,
        payload.stripe_email,
        payload.oab_number,
        normalized_state,
    ):
        if BILLING_MODE == "registration_only":
            registration_url = (
                f"{PUBLIC_BASE_URL}/register?user_id={quote_plus(payload.user_id)}"
                f"&email={quote_plus(payload.stripe_email or payload.user_id)}"
            )
            log_event(user_id=payload.user_id, endpoint="pj1ResearchPlan", status="needs_registration", reason="not_registered", ip=ip, message=message)
            return {"status": "needs_registration", "reason": "not_registered", "registration_url": registration_url}
        log_event(user_id=payload.user_id, endpoint="pj1ResearchPlan", status="denied", reason="subscription_inactive", ip=ip, message=message)
        return {"status": "denied", "reason": "subscription_inactive"}

    return None


@app.post("/v14_2/pj1/research-plan")
def build_auditable_research_plan(payload: ResearchPlanRequest, request: Request) -> dict[str, Any]:
    """Return a v14.2-compatible routing result plus PJ1 research controls."""

    message = _request_text(payload)
    access_failure = _authorize_research(payload, request, message)
    if access_failure:
        return access_failure

    # The route derives the opaque mode server-side. It never trusts a mode
    # supplied by the GPT, while the direct legacy runtime contract remains intact.
    v142_payload = dict(payload.v142)
    mode = _build_mode(message)
    v142_payload["m"] = mode
    result = run_integrated({"v142": v142_payload, "pj1": payload.pj1})

    ip = request.client.host if request.client else None
    if result.get("ok") != 1:
        needs_facts = bool(((result.get("v142") or {}).get("rp") or {}).get("nf"))
        status = "needs_facts" if needs_facts else "invalid_request"
        log_event(user_id=payload.user_id, endpoint="pj1ResearchPlan", status=status, reason=None, ip=ip, message=message)
        return {"status": status, "mode": mode}

    log_event(user_id=payload.user_id, endpoint="pj1ResearchPlan", status="ok", reason=None, ip=ip, message=message)
    return {"status": "ok", "mode": mode, "runtime": result}
