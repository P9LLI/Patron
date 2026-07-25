from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research_skill_runtime import run_research_skill


class ResearchSkillRuntimeTests(unittest.TestCase):
    def test_mapping_mode_requires_corpus_strategy_and_contrary_search(self) -> None:
        result = run_research_skill(
            {
                "query": "Quero saber a tendencia decisoria do relator em dano moral.",
                "work_type": "relatorio",
                "tribunals": ["TJSP"],
                "rapporteurs": ["Relator de Teste"],
                "period": "2019 a 2025",
                "legal_question": "Como o relator decide danos morais?",
                "requested_metrics": ["tendencia", "quantum"],
            }
        )
        research = result["research"]
        self.assertEqual(research["mode"], "mapping")
        self.assertEqual(research["saturation"]["strategy"], "corpus_formation")
        families = {item["family"] for item in research["query_plan"]}
        self.assertIn("contrary_results", families)
        self.assertIn("temporal", families)

    def test_application_mode_keeps_selective_strategy(self) -> None:
        result = run_research_skill(
            {
                "query": "Verificar a aplicacao de precedente a esta controversia contratual.",
                "work_type": "parecer",
                "tribunals": ["STJ"],
                "legal_question": "Qual regra juridica governa a controversia?",
                "thesis": "A parte busca aplicar a regra ao caso concreto.",
            }
        )
        research = result["research"]
        self.assertEqual(research["mode"], "application")
        self.assertEqual(research["saturation"]["strategy"], "selective_precedent_application")
        self.assertEqual(research["delivery_mode"], "writing")

    def test_statistics_use_independent_litigations_and_exclude_secondary_sources(self) -> None:
        cases = []
        for index, outcome in enumerate(["favorable", "favorable", "favorable", "favorable", "contrary"], start=1):
            cases.append(
                {
                    "document_id": f"doc-{index}",
                    "decision_id": f"decision-{index}",
                    "process_number": f"100000{index}-00.2024.8.26.0001",
                    "litigation_id": f"litigation-{index}",
                    "source_level": "official_full_text",
                    "source_url": f"https://www.tjsp.jus.br/acordao/{index}?utm_source=test",
                    "link_kind": "official_full_text",
                    "outcome": outcome,
                    "quantum_final": 10000 + index * 1000,
                    "cluster": "simple_case",
                    "material_facts": ["fato material"],
                    "holding": "resultado confirmado",
                    "ratio": "fundamento necessario",
                }
            )
        cases.append(
            {
                "document_id": "doc-duplicate",
                "decision_id": "decision-duplicate",
                "process_number": "1000001-00.2024.8.26.0001",
                "litigation_id": "litigation-1",
                "source_level": "official_metadata",
                "outcome": "favorable",
            }
        )
        cases.append(
            {
                "document_id": "secondary",
                "process_number": "1000099-00.2024.8.26.0001",
                "litigation_id": "secondary-litigation",
                "source_level": "secondary",
                "outcome": "favorable",
                "quantum_final": 9000,
            }
        )
        result = run_research_skill(
            {
                "query": "Mapear resultado e quantum de casos comparaveis.",
                "work_type": "relatorio",
                "tribunals": ["TJSP"],
                "period": "2024",
                "legal_question": "Qual e o resultado dos casos comparaveis?",
                "requested_metrics": ["tendencia", "quantum"],
                "known_cases": cases,
            }
        )
        statistics = result["research"]["statistics"]
        self.assertEqual(statistics["statistical_units"], 5)
        self.assertEqual(statistics["trend"]["denominator"], 5)
        self.assertEqual(statistics["trend"]["counts"]["favorable"], 4)
        self.assertTrue(statistics["trend"]["conclusion_allowed"])
        self.assertEqual(statistics["quantum_by_cluster"]["simple_case"]["median"], 13000.0)
        self.assertTrue(any(item["reason"].startswith("same_independent_litigation") for item in statistics["exclusions"]))
        self.assertIn("source_not_eligible_for_main_statistics", {item["reason"] for item in statistics["exclusions"]})

    def test_regression_fixture_treats_twelve_cases_as_seeds_not_target_corpus(self) -> None:
        fixture = json.loads((ROOT / "fixtures" / "antonio_rigolin_12_seed_regression.json").read_text())
        result = run_research_skill(fixture["request"])
        research = result["research"]
        self.assertEqual(research["mode"], "mapping")
        self.assertEqual(research["corpus"]["documents"], 12)
        self.assertEqual(research["statistics"]["statistical_units"], 0)
        seed_family = next(item for item in research["query_plan"] if item["family"] == "seed_expansion")
        self.assertEqual(seed_family["candidate_count"], 12)
        self.assertEqual(len(seed_family["queries"]), 12)
        self.assertEqual(research["statistics"]["trend"]["robustness"], "very_low")


if __name__ == "__main__":
    unittest.main()
