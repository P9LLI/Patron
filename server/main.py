from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import time
import uuid
from urllib.parse import quote_plus
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import stripe
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

APP_TITLE = "PATRON Secure Actions"
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "3600"))
RATE_LIMIT_MAX_CALLS = int(os.getenv("RATE_LIMIT_MAX_CALLS", "10"))
LOG_FULL_MESSAGE = os.getenv("LOG_FULL_MESSAGE", "false").lower() == "true"
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_API_VERSION = os.getenv("STRIPE_API_VERSION", "2026-02-25.clover")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://patron-api.onrender.com")
BILLING_MODE = os.getenv("BILLING_MODE", "registration_only")  # stripe | registration_only
REGISTRATION_BACKEND = os.getenv("REGISTRATION_BACKEND", "local")  # local | stripe
ALLOWED_SUBSCRIPTION_STATUSES = {
    status.strip().lower()
    for status in os.getenv("ALLOWED_SUBSCRIPTION_STATUSES", "active,trialing").split(",")
    if status.strip()
}

# ---------------------------------------------------------------------------
# SPLIT-KNOWLEDGE - METADE B (servidor)
# Os esquemas de roteamento e perfis de area vivem APENAS no servidor.
# O GPT recebe apenas um modo curto e opaco; sem parametros visiveis ou calibracao detalhada.
# ---------------------------------------------------------------------------

_MODE_BY_AREA: dict[str, str] = {
    "civil": "p1",
    "trabalhista": "p2",
    "tributario": "p3",
    "constitucional": "p4",
    "penal": "r1",
    "administrativo": "r2",
    "consumidor": "r3",
    "societario": "r4",
    "bancario_financeiro": "r5",
    "imobiliario_patrimonial": "r6",
    "sucessorio": "r7",
    "medico": "r8",
    "regulatorio": "r9",
    "penal_economico": "s1",
    "ambiental": "s2",
    "empresarial": "s3",
    "eleitoral": "s4",
}

_AREA_KEYWORDS: dict[str, list[str]] = {
    "trabalhista": ["trabalhista", "clt", "empregado", "empregador", "rescisao", "tst", "trt", "horas extras", "demissao", "fgts", "jornada"],
    "tributario": ["tributario", "tributo", "imposto", "icms", "iss", "irpj", "csll", "pis", "cofins", "receita federal", "fisco", "contribuicao"],
    "constitucional": ["constitucional", "stf", "adin", "adpf", "repercussao geral", "mandado de injuncao", "direito fundamental", "habeas corpus"],
    "penal": ["penal", "crime", "reu", "denuncia", "inquerito", "vara criminal", "absolvicao", "condenacao", "pena", "delito"],
    "administrativo": ["administrativo", "licitacao", "contrato administrativo", "concurso publico", "servidor publico", "ato administrativo", "improbidade"],
    "consumidor": ["consumidor", "cdc", "procon", "fornecedor", "vicio", "defeito", "recall", "dano moral consumidor"],
    "societario": ["societario", "sociedade", "socio", "quotas", "acoes", "dissolucao", "holding", "contrato social"],
    "bancario_financeiro": ["bancario", "banco", "financeiro", "credito", "juros", "financiamento", "emprestimo", "bacen"],
    "imobiliario_patrimonial": ["imobiliario", "imovel", "escritura", "matricula", "hipoteca", "alienacao fiduciaria", "condominio", "locacao"],
    "sucessorio": ["sucessorio", "heranca", "inventario", "testamento", "herdeiro", "espolio", "partilha", "legado"],
    "medico": ["medico", "hospital", "erro medico", "plano de saude", "cirurgia", "negligencia medica", "pericia medica"],
    "regulatorio": ["regulatorio", "agencia reguladora", "anatel", "anvisa", "aneel", "resolucao", "norma tecnica"],
    "penal_economico": ["penal economico", "lavagem", "corrupcao", "peculato", "organizacao criminosa", "cartel"],
    "ambiental": ["ambiental", "meio ambiente", "licenca ambiental", "ibama", "poluicao", "degradacao", "area de preservacao"],
    "empresarial": ["empresarial", "empresa", "falencia", "recuperacao judicial", "concordata", "direito comercial"],
    "eleitoral": ["eleitoral", "tse", "tre", "eleicao", "candidatura", "campanha", "inelegibilidade"],
}

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("DB_PATH", str(BASE_DIR / "server_data.db")))

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

app = FastAPI(title=APP_TITLE)


class ValidateRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    message: Optional[str] = None
    stripe_customer_id: Optional[str] = None
    stripe_email: Optional[str] = None
    oab_number: Optional[str] = None
    oab_state: Optional[str] = None


class ValidateResponse(BaseModel):
    status: str
    reason: Optional[str] = None
    registration_url: Optional[str] = None
    mode: Optional[str] = None


class RuntimeModeRequest(BaseModel):
    """Non-identifying input used only to select the opaque public-runtime mode."""

    model_config = ConfigDict(extra="forbid")

    topic: str = Field(..., min_length=12, max_length=1000)
    task_type: Optional[str] = Field(default=None, max_length=64)
    tribunals: list[str] = Field(default_factory=list, max_length=5)


class RuntimeModeResponse(BaseModel):
    status: str
    mode: Optional[str] = None
    reason: Optional[str] = None


class BlockRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
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


def log_event(*, user_id: Optional[str], endpoint: str, status: str, reason: Optional[str], ip: Optional[str], message: Optional[str]) -> None:
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


def log_abuse(*, user_id: Optional[str], endpoint: str, reason: str, ip: Optional[str], message: Optional[str]) -> None:
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
        cur = conn.execute("SELECT 1 FROM blocklist WHERE user_id = ?", (user_id,))
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


def normalize_oab_number(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    return digits or None


def normalize_oab_state(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    letters = re.sub(r"[^A-Za-z]", "", value).upper()
    return letters[:2] if letters else None


def _detect_area(message: Optional[str]) -> str:
    if not message:
        return "civil"
    msg = message.lower()
    for area, keywords in _AREA_KEYWORDS.items():
        if any(keyword in msg for keyword in keywords):
            return area
    return "civil"


def _build_mode(message: Optional[str]) -> str:
    area = _detect_area(message)
    return _MODE_BY_AREA.get(area, "p1")



def _anonymous_rate_key(request: Request) -> str:
    """Create a non-reversible rate-limit key without retaining the client IP."""
    ip = request.client.host if request.client else "unknown"
    return "anonymous:" + hashlib.sha256(ip.encode("utf-8")).hexdigest()


def _runtime_mode_text(payload: RuntimeModeRequest) -> str:
    """Use only the legal routing fields permitted by the public Action contract."""
    return " ".join([payload.task_type or "", *payload.tribunals, payload.topic]).strip()[:1200]


def find_customer_id(stripe_customer_id: Optional[str], stripe_email: Optional[str]) -> Optional[str]:
    if stripe_customer_id:
        return stripe_customer_id
    if not stripe_email:
        return None
    result = stripe.Customer.search(query=f"email:'{stripe_email}'", limit=1)
    if result.data:
        return result.data[0].id
    return None


def is_registered(user_id: str, email: Optional[str], oab_number: Optional[str], oab_state: Optional[str]) -> bool:
    normalized_oab = normalize_oab_number(oab_number)
    normalized_state = normalize_oab_state(oab_state)
    if not normalized_oab or not normalized_state:
        return False

    if REGISTRATION_BACKEND == "stripe" and STRIPE_SECRET_KEY and email:
        try:
            result = stripe.Customer.search(query=f"email:'{email}'", limit=5)
            if not result.data:
                return False
            for customer in result.data:
                metadata = customer.metadata or {}
                customer_oab = normalize_oab_number(metadata.get("oab_number"))
                customer_state = normalize_oab_state(metadata.get("oab_state"))
                if customer_oab == normalized_oab and customer_state == normalized_state:
                    return True
            return False
        except Exception:
            return False

    with sqlite3.connect(DB_PATH) as conn:
        if user_id:
            cur = conn.execute(
                "SELECT oab_number, oab_state FROM registrations WHERE user_id = ? AND status = 'active'",
                (user_id,),
            )
            row = cur.fetchone()
            if row and normalize_oab_number(row[0]) == normalized_oab and normalize_oab_state(row[1]) == normalized_state:
                return True
        if email:
            cur = conn.execute(
                "SELECT oab_number, oab_state FROM registrations WHERE email = ? AND status = 'active'",
                (email,),
            )
            row = cur.fetchone()
            if row and normalize_oab_number(row[0]) == normalized_oab and normalize_oab_state(row[1]) == normalized_state:
                return True
    return False


def is_subscription_active(user_id: str, stripe_customer_id: Optional[str], stripe_email: Optional[str], oab_number: Optional[str], oab_state: Optional[str]) -> bool:
    if BILLING_MODE == "registration_only":
        return is_registered(user_id, stripe_email, oab_number, oab_state)

    if not STRIPE_SECRET_KEY or not user_id:
        return False
    if is_blocked(user_id):
        return False

    mapped_customer_id, mapped_email = get_customer_map(user_id)
    customer_id = find_customer_id(stripe_customer_id or mapped_customer_id, stripe_email or mapped_email)
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


@app.on_event("startup")
def startup() -> None:
    init_db()
    if STRIPE_SECRET_KEY:
        stripe.api_key = STRIPE_SECRET_KEY
        stripe.api_version = STRIPE_API_VERSION


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "time": utc_now().isoformat()}

@app.post("/runtime-mode", response_model=RuntimeModeResponse)
def get_runtime_mode(payload: RuntimeModeRequest, request: Request) -> RuntimeModeResponse:
    """Return an opaque Split-Knowledge mode without registration or personal data."""
    rate_key = _anonymous_rate_key(request)
    routing_text = _runtime_mode_text(payload)

    if is_rate_limited(rate_key, "runtimeMode"):
        log_event(user_id=rate_key, endpoint="runtimeMode", status="blocked", reason="rate_limited", ip=None, message=None)
        return RuntimeModeResponse(status="blocked", reason="rate_limited")

    if detect_extraction_attempt(routing_text):
        log_abuse(user_id=rate_key, endpoint="runtimeMode", reason="extraction_suspected", ip=None, message=None)
        log_event(user_id=rate_key, endpoint="runtimeMode", status="blocked", reason="extraction_suspected", ip=None, message=None)
        return RuntimeModeResponse(status="blocked", reason="extraction_suspected")

    mode = _build_mode(routing_text)
    log_event(user_id=rate_key, endpoint="runtimeMode", status="ok", reason=None, ip=None, message=None)
    return RuntimeModeResponse(status="ok", mode=mode)



@app.post("/validateSubscription", response_model=ValidateResponse)
def validate_subscription(payload: ValidateRequest, request: Request) -> ValidateResponse:
    ip = request.client.host if request.client else None
    normalized_state = normalize_oab_state(payload.oab_state)

    if is_blocked(payload.user_id):
        log_event(user_id=payload.user_id, endpoint="validateSubscription", status="blocked", reason="user_blocked", ip=ip, message=payload.message)
        return ValidateResponse(status="blocked", reason="user_blocked")

    if is_rate_limited(payload.user_id, "validateSubscription"):
        log_event(user_id=payload.user_id, endpoint="validateSubscription", status="blocked", reason="rate_limited", ip=ip, message=payload.message)
        return ValidateResponse(status="blocked", reason="rate_limited")

    if payload.stripe_customer_id or payload.stripe_email:
        upsert_customer_map(payload.user_id, payload.stripe_customer_id, payload.stripe_email)

    if detect_extraction_attempt(payload.message):
        log_abuse(user_id=payload.user_id, endpoint="validateSubscription", reason="extraction_suspected", ip=ip, message=payload.message)
        log_event(user_id=payload.user_id, endpoint="validateSubscription", status="blocked", reason="extraction_suspected", ip=ip, message=payload.message)
        return ValidateResponse(status="blocked", reason="extraction_suspected")

    if not is_subscription_active(payload.user_id, payload.stripe_customer_id, payload.stripe_email, payload.oab_number, normalized_state):
        if BILLING_MODE == "registration_only":
            reg_url = f"{PUBLIC_BASE_URL}/register?user_id={quote_plus(payload.user_id)}&email={quote_plus(payload.stripe_email or payload.user_id or '')}"
            log_event(user_id=payload.user_id, endpoint="validateSubscription", status="needs_registration", reason="not_registered", ip=ip, message=payload.message)
            return ValidateResponse(status="needs_registration", reason="not_registered", registration_url=reg_url)
        log_event(user_id=payload.user_id, endpoint="validateSubscription", status="denied", reason="subscription_inactive", ip=ip, message=payload.message)
        return ValidateResponse(status="denied", reason="subscription_inactive")

    mode = _build_mode(payload.message)
    log_event(user_id=payload.user_id, endpoint="validateSubscription", status="ok", reason=None, ip=ip, message=payload.message)
    return ValidateResponse(status="ok", mode=mode)


@app.get("/register", response_class=HTMLResponse)
def register_form(user_id: str = "", email: str = "") -> str:
    return f"""
    <html>
      <head><title>Cadastro PATRON</title></head>
      <body>
        <h2>Cadastro PATRON</h2>
        <p><strong>Cadastro simplificado:</strong> informe apenas e-mail, numero da OAB e estado da OAB.</p>
        <p><strong>Depois do cadastro:</strong> o acesso no GPT usa apenas <strong>e-mail + OAB/estado</strong>.</p>
        <form method="post" action="/register">
          <input type="hidden" name="user_id" value="{user_id}" />
          <label>Email:</label><br/>
          <input name="email" value="{email}" required /><br/><br/>
          <label>OAB (numero):</label><br/>
          <input name="oab_number" required /><br/><br/>
          <label>OAB (estado):</label><br/>
          <input name="oab_state" maxlength="2" required /><br/><br/>
          <button type="submit">Cadastrar</button>
        </form>
        <p>Ao enviar, voce concorda com o uso dos dados para validacao de acesso.</p>
      </body>
    </html>
    """


@app.post("/register", response_class=HTMLResponse)
def register_submit(
    user_id: str = Form(""),
    email: str = Form(...),
    oab_number: str = Form(...),
    oab_state: str = Form(...),
) -> str:
    normalized_number = normalize_oab_number(oab_number)
    normalized_state = normalize_oab_state(oab_state)
    if not normalized_number or not normalized_state:
        return """
        <html>
          <body>
            <h3>Cadastro incompleto</h3>
            <p>Informe e-mail, numero da OAB e estado da OAB.</p>
          </body>
        </html>
        """

    if REGISTRATION_BACKEND == "stripe":
        if not STRIPE_SECRET_KEY:
            return """
            <html>
              <body>
                <h3>Cadastro indisponivel</h3>
                <p>O Stripe nao esta configurado. Contate o suporte.</p>
              </body>
            </html>
            """
        try:
            existing = stripe.Customer.search(query=f"email:'{email}'", limit=1)
            metadata = {"oab_number": normalized_number, "oab_state": normalized_state}
            if user_id:
                metadata["user_id"] = user_id

            if existing.data:
                customer = existing.data[0]
                merged_metadata = dict(customer.metadata or {})
                merged_metadata.update(metadata)
                customer = stripe.Customer.modify(customer.id, metadata=merged_metadata)
            else:
                customer = stripe.Customer.create(email=email, metadata=metadata)

            upsert_customer_map(user_id or email, customer.id, email)
            return """
            <html>
              <body>
                <h3>Cadastro concluido</h3>
                <p>Seu acesso foi registrado. Volte ao GPT e tente novamente.</p>
              </body>
            </html>
            """
        except Exception as exc:
            error_id = uuid.uuid4().hex[:12]
            print(f"[register][stripe_error] id={error_id} error={exc!r}")
            return f"""
            <html>
              <body>
                <h3>Erro ao cadastrar</h3>
                <p>Tivemos um problema ao registrar seu e-mail. Tente novamente.</p>
                <p>Se persistir, informe este codigo ao suporte: <strong>{error_id}</strong></p>
              </body>
            </html>
            """

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO registrations (user_id, full_name, email, cpf, oab_number, oab_state, created_at, status)
            VALUES (?, '', ?, '', ?, ?, ?, 'active')
            """,
            (user_id, email, normalized_number, normalized_state, int(time.time())),
        )
    return """
    <html>
      <body>
        <h3>Cadastro concluido</h3>
        <p>Seu acesso foi registrado. Volte ao GPT e tente novamente.</p>
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
    log_event(user_id=payload.user_id, endpoint="blockUser", status="ok", reason=payload.reason, ip=ip, message=None)
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
        event = stripe.Webhook.construct_event(payload=payload, sig_header=sig_header, secret=STRIPE_WEBHOOK_SECRET)
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
