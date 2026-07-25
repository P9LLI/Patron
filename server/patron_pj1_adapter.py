"""Compatibility adapter between the PATRON v14.2 runtime and PJ1.

The v14.2 runtime remains the first and authoritative routing step.  PJ1 is
activated only for legal-research work and receives a separately normalized
payload, so its richer schema never reaches the strict v14.2 ``run`` contract.
"""

from __future__ import annotations

import re
from typing import Any

from patron.runtime_public.patron_runtime import run as run_v14_2
from server.pesquisa_jurisprudencial_auditavel.research_skill_runtime import (
    run_research_skill,
)

__all__ = ["run_integrated"]

_OUTER_KEYS = {"v142", "pj1"}
_RESEARCH_SIGNALS = (
    "precedente",
    "jurisprud",
    "acordao",
    "acórdão",
    "sumula",
    "súmula",
    "tema repetitivo",
    "repercussao geral",
    "repercussão geral",
    "relator",
    "orgao julgador",
    "órgão julgador",
    "tendencia",
    "tendência",
    "quantum",
    "distinguishing",
    "auditoria",
)
_PJ1_SIGNALS = {"research_mode", "known_cases", "requested_metrics", "rapporteurs", "executed_families"}


def run_integrated(payload: dict[str, Any]) -> dict[str, Any]:
    """Run v14.2 first and, when appropriate, attach a PJ1 research plan.

    The returned ``v142`` object is the unmodified output of
    :func:`patron.runtime_public.patron_runtime.run`. This makes legacy-output
    regression checks exact and confines PJ1 to its own result namespace.
    """

    if not isinstance(payload, dict) or set(payload) - _OUTER_KEYS:
        return _invalid("invalid_envelope")

    baseline_payload = payload.get("v142")
    if not isinstance(baseline_payload, dict):
        return _invalid("invalid_v142_payload")

    pj1_payload = payload.get("pj1") or {}
    if not isinstance(pj1_payload, dict):
        return _invalid("invalid_pj1_payload")

    baseline = run_v14_2(baseline_payload)
    response: dict[str, Any] = {"ok": baseline.get("ok", 0), "v142": baseline}

    if baseline.get("ok") != 1:
        needs_facts = bool((baseline.get("rp") or {}).get("nf"))
        response["pj1"] = {
            "active": False,
            "reason": "baseline_needs_facts" if needs_facts else "baseline_rejected",
        }
        return response

    if not _should_activate(baseline_payload, pj1_payload):
        response["pj1"] = {"active": False, "reason": "not_a_research_request"}
        return response

    research_payload = _build_research_payload(baseline_payload, pj1_payload)
    research_result = run_research_skill(research_payload)
    if research_result.get("status") != "ok" or not isinstance(research_result.get("research"), dict):
        response["pj1"] = {"active": False, "reason": "research_payload_rejected"}
        return response

    response["pj1"] = {"active": True, **_public_research_view(research_result["research"])}
    return response


def _invalid(reason: str) -> dict[str, Any]:
    return {
        "ok": 0,
        "v142": {"ok": 0},
        "pj1": {"active": False, "reason": reason},
    }


def _should_activate(v142: dict[str, Any], pj1: dict[str, Any]) -> bool:
    if str(v142.get("tt", "")).strip().lower() == "jurisprudencia":
        return True
    if any(key in pj1 for key in _PJ1_SIGNALS):
        return True
    searchable = " ".join(
        str(value) for value in (v142.get("q"), v142.get("cx"), v142.get("of")) if value
    ).lower()
    normalized = f" {re.sub(r'[^\\wÀ-ÿ]+', ' ', searchable)} "
    return "jurisprud" in normalized or any(f" {signal} " in normalized for signal in _RESEARCH_SIGNALS)


def _build_research_payload(v142: dict[str, Any], pj1: dict[str, Any]) -> dict[str, Any]:
    """Map only whitelisted values into the PJ1 contract."""

    return {
        "query": _text_or(pj1.get("query"), v142.get("q")),
        "work_type": _text_or(pj1.get("work_type"), v142.get("tt")),
        "research_mode": pj1.get("research_mode"),
        "tribunals": pj1.get("tribunals") or pj1.get("courts") or v142.get("tr"),
        "rapporteurs": pj1.get("rapporteurs"),
        "period": _text_or(pj1.get("period"), v142.get("pd")),
        "facts": _text_or(pj1.get("facts"), v142.get("cx")),
        "legal_question": _text_or(pj1.get("legal_question"), v142.get("q")),
        "thesis": pj1.get("thesis"),
        "process_position": pj1.get("process_position"),
        "output_format": _text_or(pj1.get("output_format"), v142.get("of")),
        "known_cases": pj1.get("known_cases") or [],
        "requested_metrics": pj1.get("requested_metrics") or [],
        "source_limits": pj1.get("source_limits"),
        "executed_families": pj1.get("executed_families") or [],
    }


def _text_or(preferred: Any, fallback: Any) -> Any:
    return preferred if preferred not in (None, "") else fallback


def _public_research_view(research: dict[str, Any]) -> dict[str, Any]:
    """Expose only the operational plan, corpus controls, and conclusion gates."""

    keys = (
        "mode",
        "delivery_mode",
        "gaps",
        "query_plan",
        "saturation",
        "corpus",
        "statistics",
        "confidence",
        "gates",
        "output_template",
        "next_actions",
    )
    return {key: research.get(key) for key in keys if key in research}
