from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from patron.runtime_public.patron_runtime import run as run_v14_2
from server.patron_pj1_adapter import run_integrated


def _baseline_payload(*, task: str = "jurisprudencia") -> dict:
    return {
        "q": "Responsabilidade civil por inscricao indevida em cadastro restritivo",
        "tt": task,
        "tr": ["TJSP"],
        "pd": "2023 a 2026",
        "cx": "Consumidor aponta negativacao sem relacao contratual valida.",
        "of": "relatorio objetivo",
        "m": "p1",
    }


class PatronPj1AdapterTests(unittest.TestCase):
    def test_v142_output_is_preserved_byte_for_byte_as_a_value(self) -> None:
        legacy_input = _baseline_payload()
        legacy_output = run_v14_2(legacy_input)

        integrated = run_integrated({"v142": legacy_input})

        self.assertEqual(integrated["ok"], 1)
        self.assertEqual(integrated["v142"], legacy_output)
        self.assertTrue(integrated["pj1"]["active"])

    def test_pj1_uses_separate_schema_without_polluting_legacy_payload(self) -> None:
        legacy_input = _baseline_payload()
        pj1_input = {
            "research_mode": "mapping",
            "legal_question": "Qual a orientacao recente do TJSP sobre dano moral in re ipsa?",
            "requested_metrics": ["trend", "quantum"],
            "rapporteurs": ["Relator de teste"],
            "known_cases": [],
        }

        integrated = run_integrated({"v142": legacy_input, "pj1": pj1_input})

        self.assertEqual(integrated["v142"], run_v14_2(legacy_input))
        self.assertTrue(integrated["pj1"]["active"])
        self.assertEqual(integrated["pj1"]["mode"], "mapping")
        self.assertIn("query_plan", integrated["pj1"])
        self.assertIn("gates", integrated["pj1"])

    def test_non_research_task_does_not_activate_pj1_without_signal(self) -> None:
        legacy_input = _baseline_payload(task="peticao")
        legacy_input["q"] = "Elaborar peticao inicial com os fatos e pedidos fornecidos"
        legacy_input["cx"] = "Contrato de prestacao de servicos e inadimplemento documental."

        integrated = run_integrated({"v142": legacy_input})

        self.assertEqual(integrated["v142"], run_v14_2(legacy_input))
        self.assertFalse(integrated["pj1"]["active"])
        self.assertEqual(integrated["pj1"]["reason"], "not_a_research_request")

    def test_baseline_rejection_blocks_pj1(self) -> None:
        invalid_legacy_input = _baseline_payload()
        invalid_legacy_input["unexpected"] = "must not reach PJ1"

        integrated = run_integrated({"v142": invalid_legacy_input, "pj1": {"research_mode": "audit"}})

        self.assertEqual(integrated["ok"], 0)
        self.assertEqual(integrated["v142"], {"ok": 0})
        self.assertFalse(integrated["pj1"]["active"])
        self.assertEqual(integrated["pj1"]["reason"], "baseline_rejected")


if __name__ == "__main__":
    unittest.main()
