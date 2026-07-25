"""Deterministic planning and audit helpers for legal-research workflows.

This module is intentionally domain-agnostic.  It does not retrieve cases,
invent citations, or make legal recommendations.  It normalizes a request,
plans a search, audits a supplied corpus, and exposes the conditions required
before a GPT may draw stronger conclusions.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from statistics import mean, median
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import re


__all__ = ["run_research_skill", "classify_research_mode", "normalize_process_number"]


_ALLOWED_REQUEST_KEYS = {
    "query",
    "work_type",
    "research_mode",
    "tribunals",
    "courts",
    "rapporteurs",
    "period",
    "facts",
    "legal_question",
    "thesis",
    "process_position",
    "output_format",
    "known_cases",
    "requested_metrics",
    "source_limits",
    "executed_families",
}
_WORK_TYPES = {"jurisprudencia", "peticao", "parecer", "relatorio", "memoriais", "minuta"}
_RESEARCH_MODES = {"application", "mapping", "audit", "hybrid"}
_SOURCE_LEVELS = {
    "official_full_text": "A",
    "official_metadata": "B",
    "official_derived": "C",
    "secondary": "D",
    "excluded": "E",
    "a": "A",
    "b": "B",
    "c": "C",
    "d": "D",
    "e": "E",
}
_SOURCE_RANK = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}
_OFFICIAL_LINK_KINDS = {
    "official_full_text",
    "official_case_page",
    "official_metadata",
}
_VALID_LINK_KINDS = _OFFICIAL_LINK_KINDS | {"secondary", "unavailable"}
_FAMILY_ORDER = [
    "institutional",
    "legal",
    "factual",
    "favorable_results",
    "contrary_results",
    "exceptions",
    "procedural_class",
    "temporal",
    "seed_expansion",
]


class _InputError(ValueError):
    pass


def run_research_skill(payload: dict[str, Any]) -> dict[str, Any]:
    """Build an auditable research plan without performing retrieval itself."""
    try:
        request = _normalize_request(payload)
        mode = classify_research_mode(request)
        gaps = _classify_gaps(request, mode)
        query_plan = _build_query_plan(request, mode)
        cases = [_normalize_case(item) for item in request["known_cases"]]
        corpus = _summarize_corpus(cases)
        statistics = _analyze_statistics(cases, request["requested_metrics"])
        gates = _evaluate_gates(request, mode, gaps, corpus, statistics)
        return {
            "status": "ok",
            "research": {
                "mode": mode,
                "delivery_mode": _delivery_mode(request["work_type"]),
                "normalized_query": _public_request_view(request),
                "gaps": gaps,
                "query_plan": query_plan,
                "saturation": _saturation_policy(mode),
                "corpus": corpus,
                "statistics": statistics,
                "confidence": _confidence(corpus, statistics, gates),
                "gates": gates,
                "output_template": _output_template(mode, request["work_type"]),
                "next_actions": _next_actions(gaps, gates),
            },
        }
    except _InputError as exc:
        return {"status": "needs_more_context", "code": str(exc)}
    except Exception:
        return {"status": "error", "code": "research_processing_unavailable"}


def classify_research_mode(request: dict[str, Any]) -> str:
    """Classify the research purpose before choosing collection strategy."""
    explicit = request.get("research_mode")
    if explicit in _RESEARCH_MODES:
        return explicit

    text = " ".join(
        part for part in [request["query"], request["legal_question"], request["thesis"], request["output_format"]] if part
    ).lower()
    mapping_signals = (
        "modo de julgar",
        "perfil decisorio",
        "perfil decisório",
        "tendencia",
        "tendência",
        "proporcao",
        "proporção",
        "mediana",
        "media",
        "média",
        "quantum",
        "estabilidade",
        "comportamento decisorio",
        "comportamento decisório",
        "relator",
        "orgao julgador",
        "órgão julgador",
    )
    audit_signals = ("auditar", "auditoria", "conferir lista", "validar lista", "recalcular")
    application_signals = ("aplicar precedente", "distinguishing", "distinguir", "tese aplicavel", "tese aplicável")
    writing = request["work_type"] in {"peticao", "parecer", "memoriais", "minuta"}
    mapping = bool(request["requested_metrics"]) or any(signal in text for signal in mapping_signals)
    audit = bool(request["known_cases"]) or any(signal in text for signal in audit_signals)
    application = any(signal in text for signal in application_signals) or request["work_type"] in {
        "peticao",
        "parecer",
        "memoriais",
        "minuta",
    }

    if (mapping and writing) or (mapping and application):
        return "hybrid"
    if audit and not mapping:
        return "audit"
    if mapping:
        return "mapping"
    if audit and application:
        return "hybrid"
    return "application"


def normalize_process_number(value: Any) -> str:
    """Keep a process identifier canonical without inventing a missing identifier."""
    digits = re.sub(r"\D", "", _text(value, 80))
    if len(digits) == 20:
        return f"{digits[:7]}-{digits[7:9]}.{digits[9:13]}.{digits[13]}.{digits[14:16]}.{digits[16:]}"
    return digits


def _normalize_request(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise _InputError("invalid_request_shape")
    extras = set(payload) - _ALLOWED_REQUEST_KEYS
    if extras:
        raise _InputError("unsupported_request_field")

    query = _text(payload.get("query"), 4000)
    legal_question = _text(payload.get("legal_question"), 2000)
    if len(query or legal_question) < 12:
        raise _InputError("missing_legal_question")

    work_type = _text(payload.get("work_type") or "jurisprudencia", 40).lower()
    if work_type not in _WORK_TYPES:
        raise _InputError("invalid_work_type")
    requested_metrics = _string_list(payload.get("requested_metrics"), 20, 80)
    known_cases = payload.get("known_cases") or []
    if not isinstance(known_cases, list):
        raise _InputError("invalid_known_cases")

    explicit_mode = _text(payload.get("research_mode"), 30).lower() or None
    if explicit_mode and explicit_mode not in _RESEARCH_MODES:
        raise _InputError("invalid_research_mode")

    return {
        "query": query,
        "work_type": work_type,
        "research_mode": explicit_mode,
        "tribunals": _string_list(payload.get("tribunals") or payload.get("courts"), 8, 80),
        "rapporteurs": _string_list(payload.get("rapporteurs"), 8, 120),
        "period": _text(payload.get("period"), 120),
        "facts": _text(payload.get("facts"), 4000),
        "legal_question": legal_question,
        "thesis": _text(payload.get("thesis"), 2000),
        "process_position": _text(payload.get("process_position"), 200),
        "output_format": _text(payload.get("output_format"), 400),
        "known_cases": known_cases[:250],
        "requested_metrics": requested_metrics,
        "source_limits": _text(payload.get("source_limits"), 500),
        "executed_families": set(_string_list(payload.get("executed_families"), 20, 40)),
    }


def _classify_gaps(request: dict[str, Any], mode: str) -> list[dict[str, str]]:
    gaps: list[dict[str, str]] = []
    if mode in {"mapping", "hybrid"} and not request["tribunals"]:
        gaps.append({"field": "tribunals", "severity": "blocking", "reason": "mapping_requires_delimited_universe"})
    individual_profile = any(word in request["query"].lower() for word in ("relator", "desembargador", "ministro", "juiz"))
    if mode in {"mapping", "hybrid"} and individual_profile and not request["rapporteurs"]:
        gaps.append({"field": "rapporteurs", "severity": "blocking", "reason": "individual_profile_requires_rapporteur"})
    for field, value in (("period", request["period"]), ("facts", request["facts"]), ("thesis", request["thesis"])):
        if not value:
            gaps.append({"field": field, "severity": "material", "reason": "improves_precision_without_blocking"})
    if not request["output_format"]:
        gaps.append({"field": "output_format", "severity": "accessory", "reason": "default_template_available"})
    return gaps


def _build_query_plan(request: dict[str, Any], mode: str) -> list[dict[str, Any]]:
    issue = request["legal_question"] or request["query"]
    context = request["facts"] or request["thesis"]
    tribunal = " OR ".join(request["tribunals"]) or "[tribunal a confirmar]"
    rapporteur = " OR ".join(request["rapporteurs"])
    period = request["period"] or "[periodo a definir]"
    plan: list[dict[str, Any]] = []

    def add(family: str, purpose: str, queries: list[str], required: bool = True, max_queries: int = 8) -> None:
        normalized_queries = _unique(queries)
        plan.append({
            "family": family,
            "purpose": purpose,
            "required": required,
            "candidate_count": len(normalized_queries),
            "queries": normalized_queries[:max_queries],
        })

    add("institutional", "delimit_issuer_and_decisional_universe", [
        " ".join(part for part in [tribunal, rapporteur, issue] if part),
        " ".join(part for part in [tribunal, issue] if part),
    ], required=mode in {"mapping", "hybrid"})
    add("legal", "locate_rule_and_authority", [
        " ".join(part for part in [tribunal, issue, request["thesis"]] if part),
        " ".join(part for part in [issue, "sumula tema repetitivo IRDR IAC"] if part),
    ])
    add("factual", "locate_materially_similar_cases", [
        " ".join(part for part in [tribunal, context, issue] if part),
    ], required=bool(context))
    add("favorable_results", "avoid_one_sided_recovery", [
        " ".join(part for part in [tribunal, issue, "procedencia provimento reconhecimento"] if part),
    ])
    add("contrary_results", "locate_counterarguments_and_limits", [
        " ".join(part for part in [tribunal, issue, "improcedencia afastamento desprovimento"] if part),
        " ".join(part for part in [tribunal, issue, "distinguishing excecao limitacao"] if part),
    ])
    add("exceptions", "test_exceptions_and_process_obstacles", [
        " ".join(part for part in [tribunal, issue, "prescricao ilegitimidade ausencia de prova"] if part),
    ])
    if request["process_position"]:
        add("procedural_class", "separate_procedural_posture", [
            " ".join(part for part in [tribunal, request["process_position"], issue] if part),
        ])
    add("temporal", "cover_declared_period", [
        " ".join(part for part in [tribunal, issue, period] if part),
    ], required=mode in {"mapping", "hybrid"})
    seed_numbers = [normalize_process_number(item.get("process_number")) for item in request["known_cases"] if isinstance(item, dict)]
    if seed_numbers:
        add("seed_expansion", "validate_seeds_and_expand_citations", seed_numbers, required=True, max_queries=50)
    return plan


def _saturation_policy(mode: str) -> dict[str, Any]:
    if mode in {"mapping", "hybrid"}:
        return {
            "strategy": "corpus_formation",
            "required_families": _FAMILY_ORDER,
            "stop_only_when": [
                "relevant_families_executed",
                "contrary_search_executed",
                "temporal_coverage_checked",
                "seed_expansion_checked",
                "two_consecutive_rounds_without_new_material_cases",
                "or_documented_technical_limit",
            ],
        }
    return {
        "strategy": "selective_precedent_application",
        "stop_only_when": ["rule_confirmed", "anchor_precedents_validated", "contrary_search_executed"],
    }


def _normalize_case(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _InputError("invalid_case_record")
    source_level = _SOURCE_LEVELS.get(_text(value.get("source_level"), 40).lower(), "D")
    process_number = normalize_process_number(value.get("process_number"))
    decision_id = _text(value.get("decision_id"), 160)
    document_id = _text(value.get("document_id"), 160)
    source_url, link_status, link_kind = _normalize_link(
        value.get("source_url"), value.get("link_kind"), source_level
    )
    litigation_id = _text(value.get("litigation_id"), 160) or process_number or decision_id or document_id
    decision_key = decision_id or "|".join(part for part in [process_number, _text(value.get("judgment_date"), 40), _text(value.get("decision_type"), 80)] if part)
    merits = value.get("merits") is not False
    include = value.get("include_in_statistics")
    if include is None:
        include = source_level in {"A", "B"} and merits
    quantum = _number(value.get("quantum_final"))
    return {
        "document_id": document_id,
        "decision_id": decision_id,
        "decision_key": decision_key or document_id or litigation_id,
        "process_number": process_number,
        "litigation_id": litigation_id,
        "source_level": source_level,
        "source_url": source_url,
        "link_kind": link_kind,
        "link_status": link_status,
        "tribunal": _text(value.get("tribunal"), 80),
        "court_panel": _text(value.get("court_panel"), 160),
        "rapporteur": _text(value.get("rapporteur"), 160),
        "judgment_date": _text(value.get("judgment_date"), 40),
        "publication_date": _text(value.get("publication_date"), 40),
        "decision_type": _text(value.get("decision_type"), 80),
        "material_topic": _text(value.get("material_topic"), 300),
        "material_facts": _string_list(value.get("material_facts"), 20, 300),
        "legal_question": _text(value.get("legal_question"), 600),
        "holding": _text(value.get("holding"), 1000),
        "ratio": _text(value.get("ratio"), 1200),
        "obiter": _text(value.get("obiter"), 800),
        "applied_rule": _text(value.get("applied_rule"), 500),
        "distinguishing": _text(value.get("distinguishing"), 800),
        "outcome": _text(value.get("outcome"), 80).lower() or "unknown",
        "quantum_origin": _number(value.get("quantum_origin")),
        "quantum_final": quantum,
        "cluster": _text(value.get("cluster"), 160) or "unclassified",
        "comparability": _text(value.get("comparability"), 40) or "unknown",
        "cumulative_harms": bool(value.get("cumulative_harms")),
        "merits": merits,
        "include_in_statistics": bool(include),
        "exclusion_reason": _text(value.get("exclusion_reason"), 300),
        "citation_relation": _text(value.get("citation_relation"), 80),
        "citation_source": _text(value.get("citation_source"), 160),
        "confirmed_fields": _string_list(value.get("confirmed_fields"), 40, 80),
        "unconfirmed_fields": _string_list(value.get("unconfirmed_fields"), 40, 80),
        "provenance": _text(value.get("provenance"), 800),
        "confidence": _text(value.get("confidence"), 40) or "unknown",
    }


def _normalize_link(value: Any, declared_kind: Any, source_level: str) -> tuple[str, str, str]:
    raw = _text(value, 1200)
    kind = _text(declared_kind, 60).lower()
    if kind not in _VALID_LINK_KINDS:
        kind = "official_full_text" if source_level == "A" else "official_metadata" if source_level == "B" else "official_derived" if source_level == "C" else "secondary" if raw else "unavailable"
    if not raw:
        return "", "unavailable", "unavailable"
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "", "invalid", kind
    clean_query = urlencode([(key, val) for key, val in parse_qsl(parsed.query, keep_blank_values=True) if not key.lower().startswith("utm_") and key.lower() not in {"gclid", "fbclid"}])
    clean = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, clean_query, ""))
    official_host = parsed.hostname and (parsed.hostname.endswith(".jus.br") or parsed.hostname.endswith(".gov.br"))
    if kind in _OFFICIAL_LINK_KINDS and not official_host:
        return clean, "official_destination_unverified", kind
    if kind == "official_full_text" and any(token in parsed.path.lower() for token in ("search", "busca", "consulta")):
        return clean, "official_search_page_not_full_text", "official_case_page"
    return clean, "validated" if official_host or kind == "secondary" else "unavailable", kind


def _summarize_corpus(cases: list[dict[str, Any]]) -> dict[str, Any]:
    decisions = {case["decision_key"] for case in cases if case["decision_key"]}
    processes = {case["process_number"] for case in cases if case["process_number"]}
    litigations = {case["litigation_id"] for case in cases if case["litigation_id"]}
    source_levels = Counter(case["source_level"] for case in cases)
    link_states = Counter(case["link_status"] for case in cases)
    relation_count = Counter("derived" if case["citation_relation"] else "direct" for case in cases)
    official_main = sum(case["source_level"] in {"A", "B"} for case in cases)
    return {
        "documents": len(cases),
        "decisions": len(decisions),
        "processes": len(processes),
        "independent_litigations": len(litigations),
        "duplicate_documents": max(0, len(cases) - len(decisions)),
        "source_levels": {level: source_levels.get(level, 0) for level in ("A", "B", "C", "D", "E")},
        "official_main_corpus_candidates": official_main,
        "citation_relations": dict(relation_count),
        "link_states": dict(link_states),
        "missing_original_source_count": sum(case["source_level"] == "C" for case in cases),
    }


def _analyze_statistics(cases: list[dict[str, Any]], requested_metrics: list[str]) -> dict[str, Any]:
    eligible, exclusions = _select_independent_statistical_units(cases)
    outcome_counts = Counter(case["outcome"] for case in eligible if case["outcome"] != "unknown")
    denominator = sum(outcome_counts.values())
    trend = {
        "denominator": denominator,
        "missing_outcomes": len(eligible) - denominator,
        "counts": dict(outcome_counts),
        "proportions": {outcome: _ratio(count, denominator) for outcome, count in outcome_counts.items()},
        "conclusion_allowed": denominator >= 5,
        "robustness": _robustness(denominator),
    }
    quantum_by_cluster: dict[str, list[float]] = defaultdict(list)
    for case in eligible:
        if case["quantum_final"] is not None:
            quantum_by_cluster[case["cluster"]].append(case["quantum_final"])
    quantum = {cluster: _describe_numbers(values) for cluster, values in quantum_by_cluster.items()}
    temporal = _temporal_coverage(eligible)
    return {
        "requested_metrics": requested_metrics,
        "statistical_units": len(eligible),
        "exclusions": exclusions,
        "trend": trend,
        "quantum_by_cluster": quantum,
        "temporal_coverage": temporal,
        "comparability_warning": any(case["cluster"] == "unclassified" or case["comparability"] in {"low", "unknown"} for case in eligible),
    }


def _select_independent_statistical_units(cases: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    exclusions: list[dict[str, str]] = []
    for case in cases:
        if not case["include_in_statistics"]:
            reason = case["exclusion_reason"] or _default_exclusion(case)
            exclusions.append({"decision": case["decision_key"], "reason": reason})
            continue
        if case["source_level"] not in {"A", "B"}:
            exclusions.append({"decision": case["decision_key"], "reason": "source_not_eligible_for_main_statistics"})
            continue
        if not case["merits"]:
            exclusions.append({"decision": case["decision_key"], "reason": "procedural_decision"})
            continue
        grouped[case["litigation_id"]].append(case)
    selected: list[dict[str, Any]] = []
    for litigation_id, group in grouped.items():
        group.sort(key=lambda case: (_SOURCE_RANK[case["source_level"]], not bool(case["ratio"]), not bool(case["holding"]), case["judgment_date"]))
        selected.append(group[0])
        for duplicate in group[1:]:
            exclusions.append({"decision": duplicate["decision_key"], "reason": f"same_independent_litigation:{litigation_id}"})
    return selected, exclusions


def _describe_numbers(values: list[float]) -> dict[str, Any]:
    ordered = sorted(values)
    frequencies = Counter(ordered)
    maximum_frequency = max(frequencies.values())
    modes = sorted(value for value, count in frequencies.items() if count == maximum_frequency and count > 1)
    return {
        "denominator": len(ordered),
        "mode": modes or None,
        "median": median(ordered),
        "range": {"min": ordered[0], "max": ordered[-1]},
        "interquartile_range": {"q1": _percentile(ordered, 0.25), "q3": _percentile(ordered, 0.75)},
        "mean_complementary": round(mean(ordered), 2),
        "robustness": _robustness(len(ordered)),
        "anchoring_allowed": len(ordered) >= 5,
    }


def _evaluate_gates(
    request: dict[str, Any], mode: str, gaps: list[dict[str, str]], corpus: dict[str, Any], statistics: dict[str, Any]
) -> list[dict[str, Any]]:
    blockers = [gap for gap in gaps if gap["severity"] == "blocking"]
    expected_families = set(_FAMILY_ORDER if mode in {"mapping", "hybrid"} else {"legal", "contrary_results"})
    executed = request["executed_families"]
    recall_status = "pending" if not executed else "pass" if expected_families <= executed else "warn"
    cases_present = corpus["documents"] > 0
    return [
        _gate("scope", "fail" if blockers else "pass", [gap["reason"] for gap in blockers] or ["universe_delimited"]),
        _gate("recall", recall_status, ["execute_query_families"] if not executed else sorted(expected_families - executed) or ["families_covered"]),
        _gate("authenticity", "pending" if not cases_present else "pass" if corpus["official_main_corpus_candidates"] == corpus["documents"] else "warn", ["validate_official_sources"]),
        _gate("independence", "pass" if corpus["duplicate_documents"] == 0 else "warn", ["deduplicate_documents_and_litigations"]),
        _gate("finding", "pending" if not cases_present else "warn", ["confirm_material_facts_holding_and_ratio"]),
        _gate("contrary", "pending" if not executed else "pass" if "contrary_results" in executed else "warn", ["run_contrary_search"]),
        _gate("quantitative", "pass" if not request["requested_metrics"] else "pass" if statistics["trend"]["conclusion_allowed"] else "warn", ["state_denominator_and_limit_inference"]),
        _gate("hyperlinks", "pending" if not cases_present else "pass" if corpus["link_states"].get("validated", 0) else "warn", ["validate_official_destination"]),
        _gate("recommendations", "pending", ["trace_recommendation_to_facts_ratio_and_risk"]),
        _gate("calibration", "pass" if statistics["trend"]["conclusion_allowed"] else "warn", ["avoid_generalization_beyond_audited_corpus"]),
    ]


def _confidence(corpus: dict[str, Any], statistics: dict[str, Any], gates: list[dict[str, Any]]) -> dict[str, str]:
    failures = sum(gate["status"] == "fail" for gate in gates)
    warnings = sum(gate["status"] == "warn" for gate in gates)
    def level(value: int) -> str:
        return "high" if value >= 3 else "moderate" if value == 2 else "low" if value == 1 else "very_low"
    return {
        "coverage": level(3 if statistics["trend"]["conclusion_allowed"] else 1 if corpus["documents"] else 0),
        "source_quality": level(3 if corpus["source_levels"].get("A", 0) else 2 if corpus["source_levels"].get("B", 0) else 0),
        "comparability": "low" if statistics["comparability_warning"] else "moderate",
        "quantitative_integrity": "moderate" if statistics["trend"]["conclusion_allowed"] else "very_low",
        "recommendation": "very_low" if failures else "low" if warnings else "moderate",
    }


def _output_template(mode: str, work_type: str) -> list[str]:
    if mode == "mapping":
        return ["scope", "method", "corpus", "validation", "trend", "clusters", "countercases", "quantum", "limits", "auditable_table"]
    if mode == "audit":
        return ["received_material", "case_status", "confirmed_data", "duplicates", "corrected_metrics", "retained_and_withdrawn_conclusions"]
    if mode == "hybrid":
        return ["audited_corpus", "applicable_anchors", "counterargument", "case_application", "operational_recommendation", "limits"]
    if work_type in {"peticao", "memoriais", "minuta"}:
        return ["legal_question", "rule", "anchor_precedents", "factual_fit", "counterargument", "requested_relief"]
    return ["legal_question", "answer", "rule", "anchor_precedents", "distinguishing", "operational_conclusion"]


def _public_request_view(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "work_type": request["work_type"],
        "tribunals": request["tribunals"],
        "rapporteurs": request["rapporteurs"],
        "period": request["period"] or "not_informed",
        "legal_question": request["legal_question"] or request["query"],
        "requested_metrics": request["requested_metrics"],
    }


def _next_actions(gaps: list[dict[str, str]], gates: list[dict[str, Any]]) -> list[str]:
    actions = [f"request:{gap['field']}" for gap in gaps if gap["severity"] == "blocking"]
    actions.extend(f"gate:{gate['name']}" for gate in gates if gate["status"] in {"fail", "warn", "pending"})
    return _unique(actions)


def _gate(name: str, status: str, reasons: list[str]) -> dict[str, Any]:
    return {"name": name, "status": status, "reasons": reasons}


def _delivery_mode(work_type: str) -> str:
    return "writing" if work_type in {"peticao", "parecer", "memoriais", "minuta", "relatorio"} else "research"


def _temporal_coverage(cases: list[dict[str, Any]]) -> dict[str, Any]:
    years = Counter()
    for case in cases:
        match = re.search(r"\b(19|20)\d{2}\b", case["judgment_date"] or case["publication_date"])
        if match:
            years[match.group(0)] += 1
    return {"years": dict(sorted(years.items())), "windows": len(years), "stability_assessable": len(years) >= 2 and sum(years.values()) >= 5}


def _default_exclusion(case: dict[str, Any]) -> str:
    if case["source_level"] in {"C", "D", "E"}:
        return "source_not_eligible_for_main_statistics"
    if not case["merits"]:
        return "procedural_decision"
    return "excluded_by_input"


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _robustness(n: int) -> str:
    if n < 5:
        return "very_low"
    if n < 10:
        return "low"
    if n < 25:
        return "moderate"
    return "higher_descriptive_robustness"


def _percentile(values: list[float], proportion: float) -> float:
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * proportion
    lower, upper = int(position), min(int(position) + 1, len(values) - 1)
    return round(values[lower] + (values[upper] - values[lower]) * (position - lower), 2)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _text(value: Any, limit: int) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()[:limit]


def _string_list(value: Any, max_items: int, item_limit: int) -> list[str]:
    if value is None:
        return []
    values = re.split(r"[,;|]", value) if isinstance(value, str) else value if isinstance(value, list) else []
    return _unique([_text(item, item_limit) for item in values if _text(item, item_limit)])[:max_items]


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
