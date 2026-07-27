from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from typing import Any, Iterable


IMPLEMENTATION_VERSION = "PJ1_CORE_0.1.0"
GENERALIZATION_CLASSES = {
    "bounded_recurrence",
    "profile_behavior",
    "metric",
    "temporal_trend",
    "quantum",
    "prediction",
}
MONETARY_FIELDS = {"quantum_origin", "quantum_final"}
RULE_BY_LEVEL = {
    "A": "PJ1-AB-001",
    "B": "PJ1-AB-001",
    "C": "PJ1-C-003",
    "D": "PJ1-D-004",
    "E": "PJ1-E-005",
}
GATE_RULES = {
    "scope": "PJ1-GEN-011",
    "recovery": "PJ1-CORP-008",
    "identity": "PJ1-ID-002",
    "authenticity": "PJ1-AB-001",
    "provenance": "PJ1-C-003",
    "finding": "PJ1-FIELD-006",
    "independence": "PJ1-IND-009",
    "countersearch": "PJ1-GEN-011",
    "comparability": "PJ1-COHORT-010",
    "quantitative": "PJ1-QUANT-017",
    "temporal": "PJ1-TREND-015",
    "saturation": "PJ1-MAP-014",
    "hyperlinks": "PJ1-AUDIT-021",
    "recommendation": "PJ1-REC-018",
    "calibration": "PJ1-PRES-022",
}


def canonical_digest(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalize_identifier(value: str | None) -> str | None:
    if value is None:
        return None
    return re.sub(r"\s+", "", value).upper()


def observed_fields(document: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for fragment in document.get("fragments", []):
        result.update(fragment.get("claimed_fields", []))
    return result


def derive_access(document: dict[str, Any]) -> str:
    retrieval = document["retrieval"]
    observed = retrieval.get("observed_access", "unknown")
    status = retrieval.get("http_status")
    if (
        observed == "opened"
        and isinstance(status, int)
        and 200 <= status < 300
        and retrieval.get("content_hash")
    ):
        return "verified"
    return {
        "not_found": "not_found",
        "restricted": "restricted",
        "generic_page": "generic_page",
        "wrong_artifact": "wrong_artifact",
        "unavailable": "unavailable",
    }.get(observed, "unknown")


def derive_document_decision(document: dict[str, Any]) -> dict[str, Any]:
    target = normalize_identifier(document["target_identifier"])
    primary = normalize_identifier(document.get("observed_primary_process_number"))
    cited = sorted(
        {
            normalized
            for value in document.get("observed_cited_process_numbers", [])
            if (normalized := normalize_identifier(value))
        }
    )
    access = derive_access(document)
    kind = document["observed_kind"]
    fields = observed_fields(document)

    if access == "verified" and primary == target and kind == "full_text":
        level, identity = "A", "match"
    elif access == "verified" and primary == target and kind in {"case_page", "metadata"}:
        level, identity = "B", "match"
    elif (
        access == "verified"
        and kind == "official_reproduction"
        and primary is not None
        and primary != target
        and target in cited
    ):
        level, identity = "C", "derived_reference"
    elif kind == "secondary":
        level, identity = "D", "unknown"
    else:
        level = "E"
        if primary is not None and primary != target:
            identity = "mismatch"
        else:
            identity = "unknown"

    if level in {"A", "B"}:
        eligible = fields
    elif level == "C":
        eligible = fields - MONETARY_FIELDS
    else:
        eligible = set()
    ineligible = fields - eligible
    reasons = [f"Classificação determinística em nível {level}."]
    if identity != "match":
        reasons.append(f"Identidade documental: {identity}.")
    if access != "verified":
        reasons.append(f"Acesso documental: {access}.")
    decision: dict[str, Any] = {
        "document_id": document["document_id"],
        "source_level": level,
        "access_status": access,
        "identity_status": identity,
        "target_identifier": document["target_identifier"],
        "eligible_fields": sorted(eligible),
        "ineligible_fields": sorted(ineligible),
        "rule_ids": [RULE_BY_LEVEL[level]],
        "reasons": reasons,
    }
    if primary:
        decision["normalized_primary_process_number"] = primary
    if cited:
        decision["normalized_cited_process_numbers"] = cited
    return decision


def derive_claim_decision(
    claim: dict[str, Any],
    document_decision: dict[str, Any],
    document: dict[str, Any],
) -> dict[str, Any]:
    level = document_decision["source_level"]
    field = claim["field"]
    excerpt = claim.get("evidence_excerpt", "")
    located = bool(claim.get("source_locator") and excerpt)
    rule_ids = [RULE_BY_LEVEL[level]]
    decision: dict[str, Any] = {
        "claim_id": claim["claim_id"],
        "field": field,
        "source_document_id": claim["source_document_id"],
        "source_level": level,
        "claim_status": "unknown",
        "output_disposition": "SUPPRESS",
        "eligible_for_supporting_cohort": False,
        "rule_ids": rule_ids,
        "reasons": [],
    }
    if (
        document["retrieval"]["origin"] == "user_supplied"
        and field in {"facts", "quantum_origin", "other"}
        and claim.get("explicitly_asserted") is True
    ):
        decision.update(
            {
                "claim_status": "confirmed",
                "output_disposition": "ALLOW_USER_FACT",
                "eligible_for_supporting_cohort": False,
                "confirmed_value": claim["value"],
                "reasons": [
                    "Fato do pr?prio caso fornecido pelo usu?rio; n?o integra corpus jurisprudencial."
                ],
            }
        )
    elif (
        level in {"A", "B"}
        and document_decision["access_status"] == "verified"
        and document_decision["identity_status"] == "match"
        and located
        and claim.get("explicitly_asserted") is True
    ):
        decision.update(
            {
                "claim_status": "confirmed",
                "output_disposition": "ALLOW_AB",
                "eligible_for_supporting_cohort": True,
                "confirmed_value": claim["value"],
                "reasons": ["Campo expresso e localizado em fonte A/B elegível."],
            }
        )
    elif (
        level == "C"
        and document_decision["identity_status"] == "derived_reference"
        and field not in MONETARY_FIELDS
        and located
    ):
        decision.update(
            {
                "claim_status": "partial",
                "output_disposition": "ALLOW_C_LITERAL",
                "approved_literal_excerpt": excerpt,
                "reasons": [
                    "Permitida somente a reprodução literal derivada, não monetária e atribuída."
                ],
            }
        )
    elif level == "D":
        decision.update(
            {
                "output_disposition": "CANDIDATE_ONLY",
                "reasons": ["Fonte D serve apenas à descoberta do candidato."],
            }
        )
    elif level == "E":
        decision.update(
            {
                "output_disposition": "PENDING_ONLY",
                "reasons": ["Fonte E não autoriza conteúdo jurídico atribuído ao caso."],
            }
        )
    else:
        decision["rule_ids"] = sorted(set(rule_ids + ["PJ1-FIELD-006"]))
        decision["reasons"] = ["Claim não confirmado para o campo submetido."]
    return decision


def derive_candidate_decisions(
    request: dict[str, Any],
    document_decisions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    decisions_by_id = {item["document_id"]: item for item in document_decisions}
    exclusions = defaultdict(list)
    for item in request["exclusions"]:
        exclusions[(item["subject_type"], item["subject_id"])].append(item)

    result = []
    for candidate in request["candidates"]:
        target = normalize_identifier(candidate["target_identifier"])
        validated = any(
            decisions_by_id[document_id]["source_level"] in {"A", "B"}
            and decisions_by_id[document_id]["identity_status"] == "match"
            and normalize_identifier(decisions_by_id[document_id]["target_identifier"])
            == target
            for document_id in candidate["discovered_by_document_ids"]
            if document_id in decisions_by_id
        )
        candidate_exclusions = exclusions[("candidate", candidate["candidate_id"])]
        neutral_resolution = next(
            (
                item
                for item in candidate_exclusions
                if item["reason_code"] in {"outside_scope", "duplicate_supported"}
                and item.get("candidate_resolved_asserted") is True
                and item.get("resolution_evidence_document_ids")
            ),
            None,
        )
        resolved = validated or neutral_resolution is not None
        material = candidate["materiality_asserted"] in {"material", "unknown"}
        material_pending = material and not resolved
        if validated:
            resolution_code = "validated_by_eligible_source"
        elif neutral_resolution and neutral_resolution["reason_code"] == "outside_scope":
            resolution_code = "outside_scope_neutral"
        elif neutral_resolution:
            resolution_code = "duplicate_supported"
        else:
            resolution_code = "unresolved"
        result.append(
            {
                "candidate_id": candidate["candidate_id"],
                "material_pending": material_pending,
                "candidate_resolved": resolved,
                "resolution_code": resolution_code,
                "rule_ids": ["PJ1-CORP-008"],
                "reasons": [
                    "Candidato resolvido por evidência elegível."
                    if resolved
                    else "Candidato ainda não resolvido por fonte A/B ou exclusão neutra comprovada."
                ],
            }
        )
    return result


def query_gate(request: dict[str, Any]) -> tuple[str, str, int]:
    report = request.get("search_report")
    if not report:
        return "pending", "fail", 0
    contrary = any(
        query["direction"] == "contrary" for query in report.get("queries", [])
    )
    counter = "pass" if contrary else "fail"
    coverage = report.get("coverage_asserted", "unknown")
    if coverage not in {"pass", "limited", "fail"}:
        coverage = "fail"
    return counter, coverage, int(report.get("saturation_rounds_asserted", 0))


def case_to_litigation(request: dict[str, Any]) -> dict[str, str]:
    mapping = {}
    for group in request["proposed_litigation_groups"]:
        for case_id in group["case_ids"]:
            mapping.setdefault(case_id, group["litigation_id"])
    return mapping


def comparable_cases(request: dict[str, Any]) -> set[str]:
    result = set()
    for cluster in request["proposed_clusters"]:
        if cluster["comparability_asserted"] == "high":
            result.update(cluster["case_ids"])
    return result


def exclusion_integrity(request: dict[str, Any]) -> str:
    discovered_by: dict[str, set[str]] = defaultdict(set)
    for candidate in request["candidates"]:
        for document_id in candidate["discovered_by_document_ids"]:
            discovered_by[document_id].add(candidate["candidate_id"])
    for exclusion in request["exclusions"]:
        if exclusion["subject_type"] != "document":
            continue
        if discovered_by.get(exclusion["subject_id"]) and not exclusion.get(
            "candidate_resolved_asserted", False
        ):
            return "fail"
    return "pass"


def make_preflight(
    request: dict[str, Any],
    proposition: dict[str, Any],
    claim_by_id: dict[str, dict[str, Any]],
    claim_submission_by_id: dict[str, dict[str, Any]],
    material_pending_count: int,
) -> dict[str, Any]:
    support_ids = proposition.get("supporting_claim_ids", [])
    selected = [
        claim_by_id[claim_id] for claim_id in support_ids if claim_id in claim_by_id
    ]
    submitted = [
        claim_submission_by_id[claim_id]
        for claim_id in support_ids
        if claim_id in claim_submission_by_id
    ]
    field = proposition["field"]
    selected_for_field = [item for item in selected if item["field"] == field]
    submitted_for_field = [item for item in submitted if item["field"] == field]
    case_litigation = case_to_litigation(request)
    eligible_cases = {
        claim_submission_by_id[item["claim_id"]].get("case_id")
        for item in selected_for_field
        if item["eligible_for_supporting_cohort"]
    }
    eligible_cases.discard(None)
    eligible_litigations = {
        case_litigation.get(case_id)
        for case_id in eligible_cases
        if case_litigation.get(case_id)
    }
    all_submitted_cases = {
        item.get("case_id") for item in submitted_for_field if item.get("case_id")
    }
    all_submitted_litigations = {
        case_litigation.get(case_id)
        for case_id in all_submitted_cases
        if case_litigation.get(case_id)
    }
    supporting_count = len(all_submitted_litigations)
    eligible_count = len(eligible_litigations)
    confirmed_count = len(
        {
            case_litigation.get(
                claim_submission_by_id[item["claim_id"]].get("case_id")
            )
            for item in selected_for_field
            if item["claim_status"] == "confirmed"
            and case_litigation.get(
                claim_submission_by_id[item["claim_id"]].get("case_id")
            )
        }
    )
    independent_count = eligible_count
    counter, coverage, rounds = query_gate(request)
    exclusion = exclusion_integrity(request)
    comparable = comparable_cases(request)
    comparability = (
        "pass"
        if all_submitted_cases and all_submitted_cases <= comparable
        else "fail"
    )
    blocking: list[str] = []
    if supporting_count < 5:
        blocking.append("n_below_5")
    if eligible_count != supporting_count:
        blocking.append("ineligible_source_or_identity")
    if confirmed_count != supporting_count:
        blocking.append("unconfirmed_claim")
    if independent_count != supporting_count:
        blocking.append("non_independent_litigation")
    if material_pending_count:
        blocking.append("material_pending")
    if counter != "pass":
        blocking.append("countersearch_not_pass")
    if exclusion != "pass":
        blocking.append("exclusion_integrity_not_pass")
    if comparability != "pass":
        blocking.append("comparability_not_pass")
    if coverage not in {"pass", "limited"}:
        blocking.append("coverage_not_sufficient")
    if proposition["semantic_class"] == "temporal_trend":
        blocking.append("insufficient_temporal_windows")
    status = "fail" if blocking else "pass"
    if status == "fail":
        ceiling = "case_description"
    elif (
        request["research_mode_asserted"] in {"mapping", "hybrid"}
        and coverage == "pass"
        and rounds >= 2
    ):
        ceiling = "descriptive_mapping"
    elif request["research_mode_asserted"] in {"mapping", "hybrid"}:
        ceiling = "qualitative_signal"
    else:
        ceiling = "case_description"
    return {
        "preflight_id": f"PREFLIGHT-{proposition['proposition_id']}",
        "target_proposition_id": proposition["proposition_id"],
        "field": field,
        "semantic_class": proposition["semantic_class"],
        "supporting_cohort_count": supporting_count,
        "eligible_ab_match_verified": eligible_count,
        "confirmed_claim_count": confirmed_count,
        "independent_litigation_count": independent_count,
        "material_pending_count": material_pending_count,
        "countersearch_status": counter,
        "coverage_status": coverage,
        "exclusion_integrity": exclusion,
        "comparability_status": comparability,
        "status": status,
        "empirical_ceiling": ceiling,
        "blocking_reasons": sorted(set(blocking)),
    }


def recommendation_allowed(
    request: dict[str, Any],
    proposition: dict[str, Any],
    claim_by_id: dict[str, dict[str, Any]],
) -> bool:
    selected = [
        claim_by_id[claim_id]
        for claim_id in proposition.get("supporting_claim_ids", [])
        if claim_id in claim_by_id
        and claim_by_id[claim_id]["eligible_for_supporting_cohort"]
    ]
    fields = {item["field"] for item in selected}
    counter, _, _ = query_gate(request)
    return (
        "facts" in fields
        and "official_rule" in fields
        and bool(fields & {"holding", "ratio"})
        and bool(fields & {"distinguishing", "outcome"})
        and counter == "pass"
    )


def subset_surfaces(request: dict[str, Any]) -> list[str]:
    surfaces = {item["surface"] for item in request["propositions"]}
    if "draft_response" in request:
        surfaces.update(
            fragment["surface"] for fragment in request["draft_response"]["fragments"]
        )
    return sorted(surfaces or {"body"})


def draft_proposition_ids(request: dict[str, Any]) -> set[str]:
    return {
        proposition_id
        for fragment in request.get("draft_response", {}).get("fragments", [])
        for proposition_id in fragment.get("proposition_ids", [])
    }


def validate_request(request: dict[str, Any]) -> dict[str, Any]:
    document_decisions = [
        derive_document_decision(document) for document in request["documents"]
    ]
    document_by_id = {item["document_id"]: item for item in document_decisions}
    document_submission_by_id = {
        item["document_id"]: item for item in request["documents"]
    }
    claim_decisions = [
        derive_claim_decision(
            claim,
            document_by_id[claim["source_document_id"]],
            document_submission_by_id[claim["source_document_id"]],
        )
        for claim in request["claims"]
    ]
    claim_by_id = {item["claim_id"]: item for item in claim_decisions}
    claim_submission_by_id = {item["claim_id"]: item for item in request["claims"]}
    candidate_decisions = derive_candidate_decisions(request, document_decisions)
    material_pending_count = sum(
        item["material_pending"] for item in candidate_decisions
    )

    preflights = []
    preflight_by_proposition: dict[str, dict[str, Any]] = {}
    for proposition in request["propositions"]:
        if proposition["semantic_class"] in GENERALIZATION_CLASSES:
            preflight = make_preflight(
                request,
                proposition,
                claim_by_id,
                claim_submission_by_id,
                material_pending_count,
            )
            preflights.append(preflight)
            preflight_by_proposition[proposition["proposition_id"]] = preflight

    recommendation_results = {
        proposition["proposition_id"]: recommendation_allowed(
            request, proposition, claim_by_id
        )
        for proposition in request["propositions"]
        if proposition["semantic_class"] == "conditional_legal_application"
    }
    recommendation_gate = (
        "allowed"
        if recommendation_results and all(recommendation_results.values())
        else "blocked"
    )

    proposition_decisions = []
    for proposition in request["propositions"]:
        support = [
            claim_by_id[claim_id]
            for claim_id in proposition.get("supporting_claim_ids", [])
            if claim_id in claim_by_id
        ]
        semantic_class = proposition["semantic_class"]
        rule_ids: list[str]
        disposition = "SUPPRESS"
        reasons = []
        if semantic_class == "documentary_next_step":
            disposition = "PENDING_ONLY"
            rule_ids = ["PJ1-PRES-022"]
            reasons.append("Provid?ncia documental ou recusa segura preservada.")
        elif semantic_class in GENERALIZATION_CLASSES:
            preflight = preflight_by_proposition[proposition["proposition_id"]]
            if preflight["status"] == "pass":
                disposition = "ALLOW_AB"
                reasons.append("Preflight por conclusão e campo aprovado.")
            else:
                reasons.append(
                    "Preflight reprovado: "
                    + ", ".join(preflight["blocking_reasons"])
                    + "."
                )
            if semantic_class == "temporal_trend":
                rule_ids = ["PJ1-TREND-015"]
            elif semantic_class == "quantum":
                rule_ids = ["PJ1-QUANT-017"]
            else:
                rule_ids = ["PJ1-GEN-011"]
        elif semantic_class == "conditional_legal_application":
            rule_ids = ["PJ1-REC-018"]
            if recommendation_results.get(proposition["proposition_id"]):
                disposition = "ALLOW_AB"
                reasons.append("Gate cumulativo de recomendação aprovado.")
            else:
                reasons.append("Gate cumulativo de recomendação não comprovado.")
        elif support and all(
            item["output_disposition"] == "ALLOW_USER_FACT" for item in support
        ):
            disposition = "ALLOW_USER_FACT"
            rule_ids = ["PJ1-PRES-022"]
            reasons.append("Fato fornecido pelo usu?rio preservado fora do corpus jurisprudencial.")
        elif support and all(
            item["output_disposition"] == "ALLOW_AB" for item in support
        ):
            disposition = "ALLOW_AB"
            rule_ids = ["PJ1-AB-001"]
            reasons.append("Todos os claims de suporte são A/B elegíveis.")
        elif (
            semantic_class == "individual_case_description"
            and support
            and all(
                item["output_disposition"] == "ALLOW_C_LITERAL" for item in support
            )
        ):
            disposition = "ALLOW_C_LITERAL"
            rule_ids = ["PJ1-C-003"]
            reasons.append("Descrição limitada ao trecho C literal permitido.")
        else:
            rule_ids = ["PJ1-FIELD-006"]
            reasons.append("Suporte insuficiente para a proposição.")

        decision: dict[str, Any] = {
            "proposition_id": proposition["proposition_id"],
            "field": proposition["field"],
            "output_disposition": disposition,
            "rule_ids": rule_ids,
            "violation_ids": [],
            "reasons": reasons,
        }
        if disposition != "SUPPRESS":
            decision["approved_text"] = proposition["text"]
        proposition_decisions.append(decision)

    draft_ids = draft_proposition_ids(request)
    decision_by_prop = {
        item["proposition_id"]: item for item in proposition_decisions
    }
    leaked = {
        proposition_id
        for proposition_id in draft_ids
        if decision_by_prop.get(proposition_id, {}).get("output_disposition")
        == "SUPPRESS"
    }
    proposition_by_id = {
        item["proposition_id"]: item for item in request["propositions"]
    }
    violations = []
    for index, proposition_id in enumerate(sorted(leaked), 1):
        proposition = proposition_by_id[proposition_id]
        if proposition["field"] in MONETARY_FIELDS:
            rule_id, severity, code = (
                "PJ1-QUANT-016",
                "P2",
                "forbidden_quantum_in_draft",
            )
        else:
            rule_id, severity, code = (
                "PJ1-LANG-020",
                "P3",
                "conclusion_above_ceiling",
            )
        violation_id = f"VIO-{index:03d}-{proposition_id}"
        violations.append(
            {
                "violation_id": violation_id,
                "severity": severity,
                "rule_id": rule_id,
                "code": code,
                "message": "Proposição suprimida permanece na resposta renderizada.",
                "affected_ids": [proposition_id],
                "remediation": "Remover integralmente a proposição e reexecutar a auditoria terminal.",
            }
        )
        decision_by_prop[proposition_id]["violation_ids"].append(violation_id)

    pending_items = [
        {
            "pending_id": f"PENDING-{item['candidate_id']}",
            "kind": "candidate",
            "subject_id": item["candidate_id"],
            "reason": "Candidato material permanece sem resolução documental.",
            "required_action": "Obter fonte A/B do próprio alvo ou exclusão neutra comprovada.",
        }
        for item in candidate_decisions
        if item["material_pending"]
    ]

    metric_decisions = []
    cluster_default = (
        request["proposed_clusters"][0]["cluster_id"]
        if request["proposed_clusters"]
        else "CLUSTER-UNRESOLVED"
    )
    for preflight in preflights:
        metric = {
            "metric_id": f"METRIC-{preflight['target_proposition_id']}",
            "field": preflight["field"],
            "status": "allowed" if preflight["status"] == "pass" else "blocked",
            "cluster_id": cluster_default,
            "independent_litigation_count": preflight[
                "independent_litigation_count"
            ],
            "missing_count": max(
                0,
                preflight["supporting_cohort_count"]
                - preflight["confirmed_claim_count"],
            ),
            "preflight_id": preflight["preflight_id"],
        }
        if preflight["status"] == "pass":
            metric["denominator"] = preflight["supporting_cohort_count"]
        else:
            metric["blocking_reasons"] = preflight["blocking_reasons"]
        metric_decisions.append(metric)

    collective_leaks = sum(
        proposition_by_id[item]["semantic_class"] in GENERALIZATION_CLASSES
        for item in leaked
    )
    recommendation_leaks = sum(
        proposition_by_id[item]["semantic_class"]
        == "conditional_legal_application"
        for item in leaked
    )
    quantum_leaks = sum(
        proposition_by_id[item]["field"] in MONETARY_FIELDS for item in leaked
    )
    terminal_status = "fail" if leaked else "pass"
    terminal_audit = {
        "status": terminal_status,
        "checked_surfaces": subset_surfaces(request),
        "residual_forbidden_values": quantum_leaks,
        "collective_predicates_above_ceiling": collective_leaks,
        "contaminated_recommendation_clauses": recommendation_leaks,
        "false_suppressions": 0,
        "findings": (
            ["Nenhuma proposição suprimida permaneceu no texto renderizado."]
            if not leaked
            else [
                f"{len(leaked)} proposição(ões) suprimida(s) permaneceu(ram) no draft."
            ]
        ),
    }

    ceilings = [item["empirical_ceiling"] for item in preflights]
    if "descriptive_mapping" in ceilings:
        empirical_ceiling = "descriptive_mapping"
    elif "qualitative_signal" in ceilings:
        empirical_ceiling = "qualitative_signal"
    elif request["documents"]:
        empirical_ceiling = "case_description"
    else:
        empirical_ceiling = "none"

    suppressed = [
        item["proposition_id"]
        for item in proposition_decisions
        if item["output_disposition"] == "SUPPRESS"
    ]
    allowed = [
        item["proposition_id"]
        for item in proposition_decisions
        if item["output_disposition"] != "SUPPRESS"
    ]
    limited_disposition = any(
        item["output_disposition"]
        in {"ALLOW_C_LITERAL", "CANDIDATE_ONLY", "PENDING_ONLY"}
        for item in proposition_decisions
    )
    if terminal_status == "fail":
        status = "BLOCKED"
    elif suppressed or pending_items or limited_disposition:
        status = "APPROVED_WITH_LIMITS"
    else:
        status = "APPROVED"

    if status in {"APPROVED", "APPROVED_WITH_LIMITS"}:
        approved_text = request.get("draft_response", {}).get("rendered_text", "")
        if not approved_text:
            approved_text = "Validação estrutural concluída; consulte as decisões por proposição."
        release = {
            "status": "released",
            "must_not_rewrite": True,
            "approved_text": approved_text,
        }
    else:
        release = {
            "status": "withheld",
            "must_not_rewrite": True,
            "safe_fallback_text": (
                "A conclusão submetida excede o suporte documental validado. "
                "Use somente as descrições individuais liberadas e cumpra as pendências."
            ),
        }

    counter, coverage, rounds = query_gate(request)
    recommendation_status = (
        "pass" if recommendation_gate == "allowed" else "fail"
    )
    gate_statuses = {
        "scope": "pass",
        "recovery": "fail" if material_pending_count else "pass",
        "identity": (
            "pass"
            if all(
                item["identity_status"] in {"match", "derived_reference"}
                for item in document_decisions
            )
            else "fail"
        ),
        "authenticity": (
            "pass"
            if any(item["source_level"] in {"A", "B"} for item in document_decisions)
            else "fail"
        ),
        "provenance": (
            "pass"
            if all(item["source_level"] != "E" for item in document_decisions)
            else "fail"
        ),
        "finding": (
            "pass"
            if all(item["claim_status"] != "conflicting" for item in claim_decisions)
            else "fail"
        ),
        "independence": (
            "pass" if request["proposed_litigation_groups"] else "pending"
        ),
        "countersearch": counter,
        "comparability": (
            "pass" if comparable_cases(request) else "pending"
        ),
        "quantitative": (
            "pass"
            if any(
                item["semantic_class"] in GENERALIZATION_CLASSES
                and item["status"] == "pass"
                for item in preflights
            )
            else "fail"
        ),
        "temporal": (
            "fail"
            if any(
                item["semantic_class"] == "temporal_trend" for item in preflights
            )
            else "pending"
        ),
        "saturation": "pass" if rounds >= 2 else "pending",
        "hyperlinks": (
            "pass"
            if all(item.get("canonical_url") for item in request["documents"])
            else "fail"
        ),
        "recommendation": recommendation_status,
        "calibration": terminal_status,
    }
    gate_results = [
        {
            "gate_id": gate_id,
            "status": gate_status,
            "rule_ids": [GATE_RULES[gate_id]],
            "reasons": [f"Resultado determinístico do gate {gate_id}: {gate_status}."],
        }
        for gate_id, gate_status in gate_statuses.items()
    ]

    core_response: dict[str, Any] = {
        "schema_kind": "validation_response",
        "schema_version": "1.0.0",
        "validation_id": f"VAL-{request['request_id']}",
        "request_id": request["request_id"],
        "idempotency_key": request["idempotency_key"],
        "ruleset_version": "PJ1_V2_3",
        "status": status,
        "research_mode": request["research_mode_asserted"],
        "empirical_ceiling": empirical_ceiling,
        "recommendation_gate": recommendation_gate,
        "document_decisions": document_decisions,
        "claim_decisions": claim_decisions,
        "candidate_decisions": candidate_decisions,
        "gate_results": gate_results,
        "preflights": preflights,
        "proposition_decisions": proposition_decisions,
        "violations": violations,
        "pending_items": pending_items,
        "metric_decisions": metric_decisions,
        "allowed_content": allowed,
        "suppressed_content": suppressed,
        "terminal_audit": terminal_audit,
        "release": release,
    }
    request_digest = canonical_digest(request)
    decision_digest = canonical_digest(core_response)
    audit_seed = {
        "request_digest": request_digest,
        "decision_digest": decision_digest,
        "implementation_version": IMPLEMENTATION_VERSION,
    }
    core_response["audit"] = {
        "computed_at": request["submitted_at"],
        "engine_mode": "deterministic",
        "implementation_version": IMPLEMENTATION_VERSION,
        "request_digest": request_digest,
        "decision_digest": decision_digest,
        "audit_digest": canonical_digest(audit_seed),
    }
    return core_response
