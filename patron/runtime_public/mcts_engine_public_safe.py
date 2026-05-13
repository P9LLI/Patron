from __future__ import annotations

import re
from typing import Any

__all__ = ["run_public_safe"]

_ALLOWED_KEYS = {
    "query_text",
    "task_type",
    "tribunals",
    "period",
    "context",
    "output_format",
    "cfg",
    "sk",
}

_ALLOWED_TASK_TYPES = {"jurisprudencia", "peticao", "parecer", "relatorio"}
_ALLOWED_SK = {"A", "B", "C", "D"}
_MAX_FOCUS_POINTS = 6
_MAX_STRUCTURE_ITEMS = 8
_MAX_ITEM_LENGTH = 80


class _PublicSafeInputError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def run_public_safe(payload: dict) -> dict:
    """Return only sanitized, high-level guidance for the GPT final answer."""
    try:
        normalized = _normalize_payload(payload)
        validated = _validate_payload(normalized)
        return _build_safe_response(validated)
    except _PublicSafeInputError as exc:
        return {"status": "needs_more_facts", "code": exc.code}
    except Exception:
        return {"status": "error", "code": "processing_unavailable"}


def _normalize_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise _PublicSafeInputError("invalid_payload_shape")

    incoming_keys = set(payload.keys())
    extra_keys = incoming_keys - _ALLOWED_KEYS
    if extra_keys:
        raise _PublicSafeInputError("unsupported_payload_shape")

    normalized: dict[str, Any] = {}
    normalized["query_text"] = _clean_text(payload.get("query_text"))
    normalized["task_type"] = _clean_text(payload.get("task_type")).lower()
    normalized["period"] = _clean_text(payload.get("period")) or None
    normalized["context"] = _clean_text(payload.get("context")) or None
    normalized["output_format"] = _clean_text(payload.get("output_format")) or None
    normalized["cfg"] = _clean_text(payload.get("cfg"))
    normalized["sk"] = _clean_text(payload.get("sk")).upper()
    normalized["tribunals"] = _normalize_tribunals(payload.get("tribunals"))
    return normalized


def _validate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload["query_text"] or len(payload["query_text"]) < 12:
        raise _PublicSafeInputError("missing_essential_context")
    if payload["task_type"] not in _ALLOWED_TASK_TYPES:
        raise _PublicSafeInputError("invalid_task_type")
    if not payload["tribunals"]:
        raise _PublicSafeInputError("missing_target_tribunal")
    if not payload["cfg"] or len(payload["cfg"]) < 8:
        raise _PublicSafeInputError("invalid_operational_context")
    if payload["sk"] not in _ALLOWED_SK:
        raise _PublicSafeInputError("invalid_operational_context")
    return payload


def _build_safe_response(payload: dict[str, Any]) -> dict[str, Any]:
    full_text = " ".join(
        part for part in [payload["query_text"], payload.get("context"), payload.get("output_format")] if part
    ).lower()

    response_payload = {
        "focus_points": _limit_items(_derive_focus_points(payload["task_type"], full_text), _MAX_FOCUS_POINTS),
        "research_scope": {
            "tribunals": payload["tribunals"][:4],
            "period_hint": _normalize_period_hint(payload.get("period")),
            "prefer_official_sources": True,
            "prefer_recent_precedents": _prefer_recent_precedents(full_text, payload.get("period")),
        },
        "drafting_mode": _derive_drafting_mode(payload["task_type"], payload.get("output_format"), full_text),
        "risk_band": _derive_risk_band(full_text),
        "confidence_band": _derive_confidence_band(payload),
        "recommended_structure": _limit_items(_derive_structure(payload["task_type"]), _MAX_STRUCTURE_ITEMS),
        "needs_more_facts": _needs_more_facts(payload, full_text),
    }
    return {"status": "ok", "response_payload": response_payload}


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:2000]


def _normalize_tribunals(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        candidates = re.split(r"[,;/|]", value)
    elif isinstance(value, list):
        candidates = [str(item) for item in value]
    else:
        raise _PublicSafeInputError("invalid_target_tribunal")

    normalized: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        tribunal = re.sub(r"\s+", " ", item).strip().upper()
        tribunal = tribunal[:24]
        if tribunal and tribunal not in seen:
            normalized.append(tribunal)
            seen.add(tribunal)
    return normalized[:6]


def _normalize_period_hint(period: str | None) -> str:
    if not period:
        return "recorte_nao_informado"
    lowered = period.lower()
    if "ano" in lowered or "anos" in lowered:
        return lowered.replace(" ", "_")[:40]
    if any(token in lowered for token in ["mes", "meses", "semana", "semanas"]):
        return lowered.replace(" ", "_")[:40]
    return "recorte_informado"


def _prefer_recent_precedents(full_text: str, period: str | None) -> bool:
    if period and any(token in period.lower() for token in ["ano", "anos", "mes", "meses", "recente"]):
        return True
    return any(token in full_text for token in ["recente", "recentes", "atual", "ultimos", "últimos"])


def _derive_focus_points(task_type: str, full_text: str) -> list[str]:
    focus: list[str] = []

    task_defaults = {
        "jurisprudencia": ["precedentes relevantes", "fonte oficial", "recorte de entendimento"],
        "peticao": ["tese central", "fundamento juridico", "precedentes de apoio"],
        "parecer": ["enquadramento juridico", "risco processual", "alternativas argumentativas"],
        "relatorio": ["panorama de precedentes", "pontos controvertidos", "fontes oficiais"],
    }
    focus.extend(task_defaults.get(task_type, []))

    keyword_map = [
        (["habeas corpus", "hc"], "cabimento do habeas corpus"),
        (["liminar", "tutela", "urgencia", "urgência"], "requisitos de urgencia"),
        (["desapropriacao", "desapropriação"], "precedentes sobre desapropriacao"),
        (["prescricao", "prescrição"], "marco prescricional"),
        (["juros compensatorios", "juros compensatórios"], "juros compensatorios"),
        (["dano moral"], "fundamentacao sobre dano moral"),
        (["responsabilidade civil"], "responsabilidade civil"),
        (["prova"], "limites probatorios"),
        (["nulidade"], "nulidades e seus requisitos"),
        (["inadimplemento"], "consequencias do inadimplemento"),
        (["recurso"], "adequacao recursal"),
    ]
    for terms, label in keyword_map:
        if any(term in full_text for term in terms):
            focus.append(label)

    if any(term in full_text for term in ["stf", "stj", "tst", "trf", "tj"]):
        focus.append("jurisprudencia dos tribunais indicados")

    return _unique_preserve_order(focus)


def _derive_drafting_mode(task_type: str, output_format: str | None, full_text: str) -> str:
    combined = " ".join(part for part in [task_type, output_format or "", full_text] if part)
    if any(term in combined for term in ["quadro", "tabela", "topicos", "tópicos", "objetivo", "resumo"]):
        return "objetivo"
    if any(term in combined for term in ["estrateg", "estratég", "combater", "reforcar", "reforçar"]):
        return "estrategico"
    if any(term in combined for term in ["completo", "detalhado", "analitico", "analítico", "parecer"]):
        return "analitico"
    if task_type == "peticao":
        return "estrategico"
    if task_type == "parecer":
        return "analitico"
    return "objetivo"


def _derive_risk_band(full_text: str) -> str:
    high_terms = ["prisao", "prisão", "liminar", "urgencia", "urgência", "bloqueio", "suspensao", "suspensão"]
    medium_terms = ["nulidade", "prescricao", "prescrição", "competencia", "competência", "prova"]
    if any(term in full_text for term in high_terms):
        return "alto"
    if any(term in full_text for term in medium_terms):
        return "medio"
    return "baixo"


def _derive_confidence_band(payload: dict[str, Any]) -> str:
    score = 0
    if len(payload["query_text"]) >= 60:
        score += 1
    if payload.get("context"):
        score += 1
    if payload.get("period"):
        score += 1
    if payload.get("output_format"):
        score += 1
    if len(payload.get("tribunals", [])) >= 1:
        score += 1

    if score >= 5:
        return "alta"
    if score >= 3:
        return "media"
    return "baixa"


def _derive_structure(task_type: str) -> list[str]:
    structures = {
        "jurisprudencia": [
            "contexto resumido",
            "tese principal",
            "precedentes selecionados",
            "sintese do entendimento",
            "fontes oficiais",
        ],
        "peticao": [
            "resumo dos fatos",
            "tese central",
            "fundamentos juridicos",
            "precedentes de apoio",
            "pedido ou encaminhamento",
        ],
        "parecer": [
            "questao apresentada",
            "enquadramento juridico",
            "analise de risco",
            "entendimento predominante",
            "conclusao objetiva",
        ],
        "relatorio": [
            "escopo da pesquisa",
            "panorama de precedentes",
            "pontos de convergencia",
            "pontos de divergencia",
            "conclusoes praticas",
        ],
    }
    return structures.get(task_type, ["analise objetiva", "fontes oficiais", "conclusao"])


def _needs_more_facts(payload: dict[str, Any], full_text: str) -> bool:
    short_query = len(payload["query_text"]) < 45
    lacks_context = not payload.get("context")
    lacks_period = not payload.get("period")
    generic_terms = ["ajuda", "analise", "análise", "consulta", "pesquisa"]
    too_generic = sum(term in full_text for term in generic_terms) >= 2 and len(full_text) < 90
    return bool(short_query and (lacks_context or lacks_period or too_generic))


def _limit_items(items: list[str], limit: int) -> list[str]:
    clipped: list[str] = []
    for item in items:
        text = _clean_text(item)
        if text:
            clipped.append(text[:_MAX_ITEM_LENGTH])
    return clipped[:limit]


def _unique_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
