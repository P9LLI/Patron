from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Form
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
import stripe

APP_TITLE = "Custom GPT Secure Actions"

TOKEN_TTL_MINUTES = int(os.getenv("TOKEN_TTL_MINUTES", "10"))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "3600"))
RATE_LIMIT_MAX_CALLS = int(os.getenv("RATE_LIMIT_MAX_CALLS", "10"))
LOG_FULL_MESSAGE = os.getenv("LOG_FULL_MESSAGE", "false").lower() == "true"
OBFUSCATE_ENABLED = os.getenv("OBFUSCATE_ENABLED", "true").lower() == "true"
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_API_VERSION = os.getenv("STRIPE_API_VERSION", "2026-02-25.clover")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://patron-api.onrender.com")
BILLING_MODE = os.getenv("BILLING_MODE", "stripe")  # stripe | registration_only
ALLOWED_SUBSCRIPTION_STATUSES = {
    status.strip().lower()
    for status in os.getenv("ALLOWED_SUBSCRIPTION_STATUSES", "active,trialing").split(",")
    if status.strip()
}

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("DB_PATH", str(BASE_DIR / "server_data.db")))
ALGO_PARTS_DIR = Path(os.getenv("ALGO_PARTS_DIR", str(BASE_DIR / "data")))

EXTRACTION_PATTERNS = [
    r"mostre\s+instru(c|ç)(o|õ)es",
    r"mostre\s+o\s+prompt",
    r"mostre\s+o\s+script",
    r"liste\s+arquivos",
    r"mostre\s+o\s+arquivo",
    r"conte(u|ú)do\s+completo",
    r"reveal\s+the\s+prompt",
    r"system\s+prompt",
    r"dump\s+context",
    r"repeat\s+verbatim",
    r"ignore\s+previous\s+instructions",
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                user_id TEXT,
                endpoint TEXT NOT NULL,
                status TEXT NOT NULL,
                reason TEXT,
                ip TEXT,
                message_hash TEXT,
                message_snippet TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS abuse_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                user_id TEXT,
                endpoint TEXT NOT NULL,
                reason TEXT NOT NULL,
                ip TEXT,
                message_snippet TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS customer_map (
                user_id TEXT PRIMARY KEY,
                stripe_customer_id TEXT,
                stripe_email TEXT,
                updated_at INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS subscription_cache (
                stripe_customer_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS blocklist (
                user_id TEXT PRIMARY KEY,
                reason TEXT NOT NULL,
                blocked_at INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS registrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL,
                cpf TEXT NOT NULL,
                oab_number TEXT NOT NULL,
                oab_state TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                status TEXT NOT NULL
            )
            """
        )


def log_event(
    *,
    user_id: Optional[str],
    endpoint: str,
    status: str,
    reason: Optional[str],
    ip: Optional[str],
    message: Optional[str],
) -> None:
    ts = int(time.time())
    msg = message or ""
    msg_hash = hashlib.sha256(msg.encode("utf-8")).hexdigest() if msg else None
    snippet = msg[:300] if (msg and LOG_FULL_MESSAGE) else (msg[:120] if msg else None)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO logs (ts, user_id, endpoint, status, reason, ip, message_hash, message_snippet)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (ts, user_id, endpoint, status, reason, ip, msg_hash, snippet),
        )


def log_abuse(
    *,
    user_id: Optional[str],
    endpoint: str,
    reason: str,
    ip: Optional[str],
    message: Optional[str],
) -> None:
    ts = int(time.time())
    snippet = (message or "")[:300]
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO abuse_events (ts, user_id, endpoint, reason, ip, message_snippet)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (ts, user_id, endpoint, reason, ip, snippet),
        )


def is_rate_limited(user_id: str, bucket: str) -> bool:
    since = int(time.time()) - RATE_LIMIT_WINDOW_SECONDS
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            """
            SELECT COUNT(*) FROM logs
            WHERE user_id = ? AND endpoint = ? AND ts >= ?
            """,
            (user_id, bucket, since),
        )
        count = cur.fetchone()[0]
    return count >= RATE_LIMIT_MAX_CALLS


def is_blocked(user_id: str) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            "SELECT 1 FROM blocklist WHERE user_id = ?",
            (user_id,),
        )
        return cur.fetchone() is not None


def upsert_customer_map(user_id: str, stripe_customer_id: Optional[str], stripe_email: Optional[str]) -> None:
    now = int(time.time())
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO customer_map (user_id, stripe_customer_id, stripe_email, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                stripe_customer_id=excluded.stripe_customer_id,
                stripe_email=excluded.stripe_email,
                updated_at=excluded.updated_at
            """,
            (user_id, stripe_customer_id, stripe_email, now),
        )


def get_customer_map(user_id: str) -> tuple[Optional[str], Optional[str]]:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            "SELECT stripe_customer_id, stripe_email FROM customer_map WHERE user_id = ?",
            (user_id,),
        )
        row = cur.fetchone()
    if not row:
        return None, None
    return row[0], row[1]


def cache_subscription_status(stripe_customer_id: str, status: str) -> None:
    now = int(time.time())
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO subscription_cache (stripe_customer_id, status, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(stripe_customer_id) DO UPDATE SET
                status=excluded.status,
                updated_at=excluded.updated_at
            """,
            (stripe_customer_id, status.lower(), now),
        )


def get_cached_subscription_status(stripe_customer_id: str) -> Optional[str]:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            "SELECT status FROM subscription_cache WHERE stripe_customer_id = ?",
            (stripe_customer_id,),
        )
        row = cur.fetchone()
    return row[0] if row else None


def detect_extraction_attempt(message: Optional[str]) -> bool:
    if not message:
        return False
    msg = message.lower()
    for pattern in EXTRACTION_PATTERNS:
        if re.search(pattern, msg):
            return True
    return False


def find_customer_id(stripe_customer_id: Optional[str], stripe_email: Optional[str]) -> Optional[str]:
    if stripe_customer_id:
        return stripe_customer_id
    if not stripe_email:
        return None
    query = f"email:'{stripe_email}'"
    result = stripe.Customer.search(query=query, limit=1)
    if result.data:
        return result.data[0].id
    return None


def is_subscription_active(
    user_id: str,
    payment_token: Optional[str],
    stripe_customer_id: Optional[str],
    stripe_email: Optional[str],
) -> bool:
    """
    Validates subscription in Stripe (default) or registration-only mode.
    """
    _ = payment_token
    if BILLING_MODE == "registration_only":
        return is_registered(user_id, stripe_email)
    if not STRIPE_SECRET_KEY:
        return False
    if not user_id:
        return False
    if is_blocked(user_id):
        return False

    mapped_customer_id, mapped_email = get_customer_map(user_id)
    customer_id = find_customer_id(
        stripe_customer_id or mapped_customer_id,
        stripe_email or mapped_email,
    )
    if not customer_id:
        return False

    cached = get_cached_subscription_status(customer_id)
    if cached and cached in ALLOWED_SUBSCRIPTION_STATUSES:
        return True

    subs = stripe.Subscription.list(customer=customer_id, status="all", limit=10)
    for sub in subs.data:
        if sub.status:
            cache_subscription_status(customer_id, sub.status)
            if sub.status.lower() in ALLOWED_SUBSCRIPTION_STATUSES:
                return True
    return False


def is_registered(user_id: str, email: Optional[str]) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        if user_id:
            cur = conn.execute(
                "SELECT 1 FROM registrations WHERE user_id = ? AND status = 'active'",
                (user_id,),
            )
            if cur.fetchone():
                return True
        if email:
            cur = conn.execute(
                "SELECT 1 FROM registrations WHERE email = ? AND status = 'active'",
                (email,),
            )
            if cur.fetchone():
                return True
    return False


def create_session_token(user_id: str) -> str:
    token = uuid.uuid4().hex
    now = int(time.time())
    expires_at = now + TOKEN_TTL_MINUTES * 60
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO sessions (token, user_id, created_at, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (token, user_id, now, expires_at),
        )
    return token


def validate_session_token(user_id: str, token: str) -> bool:
    now = int(time.time())
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            """
            SELECT expires_at FROM sessions
            WHERE token = ? AND user_id = ?
            """,
            (token, user_id),
        )
        row = cur.fetchone()
    return bool(row and row[0] > now)


def load_algorithm_part(part_name: str) -> str:
    part_path = ALGO_PARTS_DIR / part_name
    if not part_path.exists():
        raise FileNotFoundError(f"Missing algorithm part: {part_path}")
    try:
        return part_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # Fallback for Windows-1252/Latin-1 encodings
        return part_path.read_text(encoding="latin-1")


def obfuscate_text(text: str) -> str:
    if not OBFUSCATE_ENABLED:
        return text
    # Lightweight obfuscation: strip common comment lines and collapse whitespace.
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("//") or stripped.startswith("--"):
            continue
        lines.append(line)
    collapsed = " ".join(" ".join(lines).split())
    return collapsed


app = FastAPI(title=APP_TITLE)


class ValidateRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    message: Optional[str] = None
    payment_token: Optional[str] = None
    stripe_customer_id: Optional[str] = None
    stripe_email: Optional[str] = None


class ValidateResponse(BaseModel):
    status: str
    session_token: Optional[str] = None
    expires_in_seconds: Optional[int] = None
    reason: Optional[str] = None
    registration_url: Optional[str] = None


class PartRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    session_token: str = Field(..., min_length=1)
    message: Optional[str] = None
    stripe_customer_id: Optional[str] = None
    stripe_email: Optional[str] = None


class BlockRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)


class PartResponse(BaseModel):
    status: str
    part: Optional[str] = None
    cleanup: Optional[bool] = None
    reason: Optional[str] = None


@app.on_event("startup")
def startup() -> None:
    init_db()
    if STRIPE_SECRET_KEY:
        stripe.api_key = STRIPE_SECRET_KEY
        stripe.api_version = STRIPE_API_VERSION


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "time": utc_now().isoformat()}


@app.post("/validateSubscription", response_model=ValidateResponse)
def validate_subscription(payload: ValidateRequest, request: Request) -> ValidateResponse:
    ip = request.client.host if request.client else None
    if is_blocked(payload.user_id):
        log_event(
            user_id=payload.user_id,
            endpoint="validateSubscription",
            status="blocked",
            reason="user_blocked",
            ip=ip,
            message=payload.message,
        )
        return ValidateResponse(status="blocked", reason="user_blocked")

    if payload.stripe_customer_id or payload.stripe_email:
        upsert_customer_map(payload.user_id, payload.stripe_customer_id, payload.stripe_email)

    if detect_extraction_attempt(payload.message):
        log_abuse(
            user_id=payload.user_id,
            endpoint="validateSubscription",
            reason="extraction_suspected",
            ip=ip,
            message=payload.message,
        )
        log_event(
            user_id=payload.user_id,
            endpoint="validateSubscription",
            status="blocked",
            reason="extraction_suspected",
            ip=ip,
            message=payload.message,
        )
        return ValidateResponse(status="blocked", reason="extraction_suspected")

    if not is_subscription_active(
        payload.user_id,
        payload.payment_token,
        payload.stripe_customer_id,
        payload.stripe_email,
    ):
        if BILLING_MODE == "registration_only":
            reg_url = (
                f"{PUBLIC_BASE_URL}/register?user_id={payload.user_id}"
                f"&email={payload.stripe_email or ''}"
            )
            log_event(
                user_id=payload.user_id,
                endpoint="validateSubscription",
                status="needs_registration",
                reason="not_registered",
                ip=ip,
                message=payload.message,
            )
            return ValidateResponse(
                status="needs_registration",
                reason="not_registered",
                registration_url=reg_url,
            )
        log_event(
            user_id=payload.user_id,
            endpoint="validateSubscription",
            status="denied",
            reason="subscription_inactive",
            ip=ip,
            message=payload.message,
        )
        return ValidateResponse(status="denied", reason="subscription_inactive")

    token = create_session_token(payload.user_id)
    log_event(
        user_id=payload.user_id,
        endpoint="validateSubscription",
        status="ok",
        reason=None,
        ip=ip,
        message=payload.message,
    )
    return ValidateResponse(
        status="ok",
        session_token=token,
        expires_in_seconds=TOKEN_TTL_MINUTES * 60,
    )


def serve_part(part_filename: str, payload: PartRequest, request: Request) -> PartResponse:
    ip = request.client.host if request.client else None
    if is_blocked(payload.user_id):
        log_event(
            user_id=payload.user_id,
            endpoint="algorithm_parts",
            status="blocked",
            reason="user_blocked",
            ip=ip,
            message=payload.message,
        )
        return PartResponse(status="blocked", reason="user_blocked")

    if payload.stripe_customer_id or payload.stripe_email:
        upsert_customer_map(payload.user_id, payload.stripe_customer_id, payload.stripe_email)

    if detect_extraction_attempt(payload.message):
        log_abuse(
            user_id=payload.user_id,
            endpoint="algorithm_parts",
            reason="extraction_suspected",
            ip=ip,
            message=payload.message,
        )
        log_event(
            user_id=payload.user_id,
            endpoint="algorithm_parts",
            status="blocked",
            reason="extraction_suspected",
            ip=ip,
            message=payload.message,
        )
        return PartResponse(status="blocked", reason="extraction_suspected")

    if not validate_session_token(payload.user_id, payload.session_token):
        log_event(
            user_id=payload.user_id,
            endpoint="algorithm_parts",
            status="invalid_session",
            reason="session_invalid_or_expired",
            ip=ip,
            message=payload.message,
        )
        return PartResponse(status="invalid_session", reason="session_invalid_or_expired")

    if not is_subscription_active(
        payload.user_id,
        None,
        payload.stripe_customer_id,
        payload.stripe_email,
    ):
        log_event(
            user_id=payload.user_id,
            endpoint="algorithm_parts",
            status="denied",
            reason="subscription_inactive",
            ip=ip,
            message=payload.message,
        )
        return PartResponse(status="denied", reason="subscription_inactive")

    if is_rate_limited(payload.user_id, "algorithm_parts"):
        log_event(
            user_id=payload.user_id,
            endpoint="algorithm_parts",
            status="rate_limited",
            reason="too_many_requests",
            ip=ip,
            message=payload.message,
        )
        return PartResponse(status="rate_limited", reason="too_many_requests")

    try:
        raw_part = load_algorithm_part(part_filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    part = obfuscate_text(raw_part)
    log_event(
        user_id=payload.user_id,
        endpoint="algorithm_parts",
        status="ok",
        reason=None,
        ip=ip,
        message=payload.message,
    )
    return PartResponse(status="ok", part=part, cleanup=True)


@app.post("/getAlgorithmPart1", response_model=PartResponse)
def get_algorithm_part1(payload: PartRequest, request: Request) -> PartResponse:
    return serve_part("algorithm_part1.txt", payload, request)


@app.post("/getAlgorithmPart2", response_model=PartResponse)
def get_algorithm_part2(payload: PartRequest, request: Request) -> PartResponse:
    return serve_part("algorithm_part2.txt", payload, request)


@app.post("/getAlgorithmPart3", response_model=PartResponse)
def get_algorithm_part3(payload: PartRequest, request: Request) -> PartResponse:
    return serve_part("algorithm_part3.txt", payload, request)


@app.get("/register", response_class=HTMLResponse)
def register_form(user_id: str = "", email: str = "") -> str:
    return f"""
    <html>
      <head><title>Cadastro PATRON</title></head>
      <body>
        <h2>Cadastro PATRON (teste)</h2>
        <p>Preencha os dados para liberar o acesso.</p>
        <form method="post" action="/register">
          <input type="hidden" name="user_id" value="{user_id}" />
          <label>Nome completo:</label><br/>
          <input name="full_name" required /><br/><br/>
          <label>Email:</label><br/>
          <input name="email" value="{email}" required /><br/><br/>
          <label>CPF:</label><br/>
          <input name="cpf" required /><br/><br/>
          <label>OAB (numero):</label><br/>
          <input name="oab_number" required /><br/><br/>
          <label>OAB (estado):</label><br/>
          <input name="oab_state" required /><br/><br/>
          <button type="submit">Cadastrar</button>
        </form>
        <p>Ao enviar, voce concorda com o uso dos dados para validacao de acesso.</p>
      </body>
    </html>
    """


@app.post("/register", response_class=HTMLResponse)
def register_submit(
    user_id: str = Form(""),
    full_name: str = Form(...),
    email: str = Form(...),
    cpf: str = Form(...),
    oab_number: str = Form(...),
    oab_state: str = Form(...),
) -> str:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO registrations (user_id, full_name, email, cpf, oab_number, oab_state, created_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'active')
            """,
            (user_id, full_name, email, cpf, oab_number, oab_state, int(time.time())),
        )
    return """
    <html>
      <body>
        <h3>Cadastro concluido</h3>
        <p>Volte ao GPT e tente novamente.</p>
      </body>
    </html>
    """


@app.post("/blockUser")
def block_user(payload: BlockRequest, request: Request) -> dict:
    ip = request.client.host if request.client else None
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO blocklist (user_id, reason, blocked_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                reason=excluded.reason,
                blocked_at=excluded.blocked_at
            """,
            (payload.user_id, payload.reason, int(time.time())),
        )
    log_event(
        user_id=payload.user_id,
        endpoint="blockUser",
        status="ok",
        reason=payload.reason,
        ip=ip,
        message=None,
    )
    return {"status": "ok"}


@app.post("/stripe/webhook")
async def stripe_webhook(request: Request) -> dict:
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=400, detail="stripe webhook secret not configured")
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    if not sig_header:
        raise HTTPException(status_code=400, detail="missing stripe signature")
    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=STRIPE_WEBHOOK_SECRET,
        )
    except stripe.error.SignatureVerificationError as exc:
        raise HTTPException(status_code=400, detail="invalid signature") from exc

    event_type = event["type"]
    data_object = event["data"]["object"]

    if event_type in {"checkout.session.completed", "checkout.session.async_payment_succeeded"}:
        customer_id = data_object.get("customer")
        customer_email = data_object.get("customer_details", {}).get("email")
        if customer_id:
            if customer_email:
                upsert_customer_map(customer_id, customer_id, customer_email)
            cache_subscription_status(customer_id, "active")

    if event_type in {"customer.subscription.created", "customer.subscription.updated"}:
        customer_id = data_object.get("customer")
        status = data_object.get("status")
        if customer_id and status:
            cache_subscription_status(customer_id, status)

    if event_type == "customer.subscription.deleted":
        customer_id = data_object.get("customer")
        if customer_id:
            cache_subscription_status(customer_id, "canceled")

    return {"status": "ok"}
