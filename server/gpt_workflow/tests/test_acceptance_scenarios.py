from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path

from server.gpt_workflow.config import WorkflowConfig
from server.gpt_workflow.service import WorkflowService


class ContextualAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        root = Path(self.temp.name)
        self.service = WorkflowService(
            WorkflowConfig(db_path=root / "workflow.db", log_path=root / "workflow.log")
        )
        self.counter = 0

    def tearDown(self) -> None:
        logging.shutdown()
        self.temp.cleanup()

    def key(self, name: str) -> str:
        self.counter += 1
        return f"acceptance-{name}-{self.counter}"

    def prepare_contextual_claim(self) -> tuple[str, str]:
        created, _, _ = self.service.create_execution(
            {"input": {"question": "contextual"}}, self.key("create")
        )
        execution_id = created["execution"]["execution_id"]
        self.service.submit_queries(
            execution_id,
            {"queries": [{"query_id": "Q1", "text": "fonte indireta"}]},
            self.key("query"),
        )
        self.service.submit_candidates(
            execution_id,
            {
                "candidates": [
                    {
                        "candidate_id": "CAND-CONTEXT",
                        "source_url": "https://example.invalid/context",
                        "process_number": "1000001-11.2024.8.26.0001",
                        "query_ids": ["Q1"],
                        "evidence_mode": "indirect",
                        "excerpts": {"identity": "Contexto qualificado."},
                    }
                ]
            },
            self.key("candidate"),
        )
        frozen, _, _ = self.service.freeze_repository(
            execution_id, {}, self.key("freeze")
        )
        receipt = frozen["repository_receipt"]
        batch = frozen["batches"][0]
        self.service.submit_selection(
            receipt["repository_id"],
            {
                "batch_id": batch["batch_id"],
                "repository_id": receipt["repository_id"],
                "repository_version": 1,
                "assessments": [
                    {
                        "candidate_id": "CAND-CONTEXT",
                        "identity_status": "confirmed",
                        "relator_status": "not_applicable",
                        "theme_class": "T3",
                        "preliminary_bucket": "contextual",
                        "requires_full_text_review": False,
                        "inclusion_rule_ids": ["I-CONTEXT"],
                        "exclusion_rule_ids": [],
                        "evidence_excerpt_ids": ["E-CONTEXT"],
                        "reason": "Fonte indireta utilizável apenas como contexto.",
                    }
                ],
            },
            self.key("selection"),
        )
        self.service.submit_verifications(
            execution_id,
            {
                "verifications": [
                    {
                        "candidate_id": "CAND-CONTEXT",
                        "verification_status": "verified",
                        "identity": {"status": "confirmed", "evidence": "Identidade confirmada."},
                        "relator": {"status": "not_applicable"},
                    }
                ]
            },
            self.key("verification"),
        )
        self.service.admit_sample(
            execution_id,
            {"candidates": [{"candidate_id": "CAND-CONTEXT", "bucket": "contextual"}]},
            self.key("sample"),
        )
        self.service.resolve_claims(
            execution_id,
            {
                "claims": [
                    {
                        "claim_id": "C-CONTEXT",
                        "status": "context_only",
                        "allowed_scope": "descrição contextual individual",
                        "evidence_ids": ["E-CONTEXT"],
                        "authorized_processes": ["1000001-11.2024.8.26.0001"],
                        "authorized_amounts": [],
                        "authorized_dates": [],
                        "authorized_summulas": [],
                        "forbidden_inferences": ["tendência", "frequência", "denominador"],
                    }
                ]
            },
            self.key("claims"),
        )
        return execution_id, receipt["repository_id"]

    def test_blocked_then_strict_contextual_release(self) -> None:
        execution_id, repository_id = self.prepare_contextual_claim()
        blocked, _, _ = self.service.audit_draft(
            execution_id,
            {
                "repository_id": repository_id,
                "repository_version": 1,
                "draft_text": (
                    "A tendência abrange 9999999-99.2024.8.26.0001, "
                    "R$ 1.000,00 e Súmula 385."
                ),
                "statements": [
                    {
                        "statement_id": "S1",
                        "text": (
                            "A tendência abrange 9999999-99.2024.8.26.0001, "
                            "R$ 1.000,00 e Súmula 385."
                        ),
                        "claim_id": "C-CONTEXT",
                        "evidence_ids": ["E-CONTEXT"],
                        "entities": {
                            "processes": [],
                            "amounts": [],
                            "dates": [],
                            "summulas": [],
                            "magistrates": [],
                            "chambers": [],
                        },
                    }
                ],
            },
            self.key("blocked"),
        )
        self.assertEqual(0, blocked["releases"]["answer_release"])

        released, _, _ = self.service.audit_draft(
            execution_id,
            {
                "repository_id": repository_id,
                "repository_version": 1,
                "draft_text": (
                    "Como contexto, o processo 1000001-11.2024.8.26.0001 "
                    "foi localizado em fonte indireta."
                ),
                "statements": [
                    {
                        "statement_id": "S2",
                        "text": (
                            "Como contexto, o processo 1000001-11.2024.8.26.0001 "
                            "foi localizado em fonte indireta."
                        ),
                        "claim_id": "C-CONTEXT",
                        "evidence_ids": ["E-CONTEXT"],
                        "entities": {
                            "processes": ["1000001-11.2024.8.26.0001"],
                            "amounts": [],
                            "dates": [],
                            "summulas": [],
                            "magistrates": [],
                            "chambers": [],
                        },
                    }
                ],
            },
            self.key("released"),
        )
        self.assertEqual(1, released["releases"]["answer_release"])


if __name__ == "__main__":
    unittest.main()
