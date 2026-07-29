from __future__ import annotations

import logging
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from server.gpt_workflow.config import WorkflowConfig
from server.gpt_workflow.errors import WorkflowError
from server.gpt_workflow.service import WorkflowService


class WorkflowServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        root = Path(self.temp.name)
        self.config = WorkflowConfig(
            db_path=root / "workflow.db",
            log_path=root / "workflow.log",
            bearer_token="test-token",
            batch_size=5,
            candidates_max_count=20,
            repository_versions_max=2,
        )
        self.service = WorkflowService(self.config)
        self.sequence = 0

    def tearDown(self) -> None:
        logging.shutdown()
        self.temp.cleanup()

    def key(self, label: str) -> str:
        self.sequence += 1
        return f"test-{label}-{self.sequence:04d}"

    def create(self) -> str:
        body, status, replay = self.service.create_execution(
            {"input": {"question": "Responsabilidade civil"}}, self.key("create")
        )
        self.assertEqual(201, status)
        self.assertFalse(replay)
        return body["execution"]["execution_id"]

    def discover(self, execution_id: str) -> None:
        self.service.submit_queries(
            execution_id,
            {"queries": [{"query_id": "Q1", "text": "indenização TJSP"}, {"query_id": "Q2", "text": "dano moral TJSP"}]},
            self.key("queries"),
        )

    @staticmethod
    def candidate(candidate_id: str = "CAND-0001", process: str = "1000001-11.2024.8.26.0001") -> dict:
        return {
            "candidate_id": candidate_id,
            "source_url": f"https://esaj.tjsp.jus.br/{candidate_id}",
            "final_url": f"https://esaj.tjsp.jus.br/{candidate_id}",
            "tribunal": "TJSP",
            "document_type": "acordao",
            "process_number": process,
            "container_process": process,
            "target_process": process,
            "container_relator": "Fulano de Tal",
            "target_relator": "Fulano de Tal",
            "chamber": "1ª Câmara",
            "judgment_date": "2024-01-10",
            "official_source": True,
            "access_status": "accessible",
            "evidence_mode": "direct",
            "query_ids": ["Q1"],
            "excerpts": {"identity": "Trecho oficial", "holding": "Recurso desprovido."},
            "pages": {"identity": 1, "holding": 6},
            "full_text_reference": "DOC-1",
        }

    def build_frozen(self, count: int = 1) -> tuple[str, dict]:
        execution_id = self.create()
        self.discover(execution_id)
        candidates = [
            self.candidate(
                f"CAND-{index:04d}",
                f"{1000000 + index:07d}-11.2024.8.26.0001",
            )
            for index in range(1, count + 1)
        ]
        self.service.submit_candidates(
            execution_id, {"candidates": candidates}, self.key("candidates")
        )
        frozen, _, _ = self.service.freeze_repository(
            execution_id, {}, self.key("freeze")
        )
        return execution_id, frozen

    def complete_selection(self, frozen: dict) -> None:
        receipt = frozen["repository_receipt"]
        for batch in frozen["batches"]:
            self.service.submit_selection(
                receipt["repository_id"],
                {
                    "batch_id": batch["batch_id"],
                    "repository_id": receipt["repository_id"],
                    "repository_version": receipt["repository_version"],
                    "assessments": [
                        {
                            "candidate_id": candidate_id,
                            "identity_status": "confirmed",
                            "relator_status": "confirmed",
                            "theme_class": "T1",
                            "preliminary_bucket": "main_candidate",
                            "requires_full_text_review": True,
                            "inclusion_rule_ids": ["I-01"],
                            "exclusion_rule_ids": [],
                            "evidence_excerpt_ids": [f"EX-{candidate_id}"],
                            "reason": "Identidade e tema confirmados.",
                        }
                        for candidate_id in batch["candidate_ids"]
                    ],
                },
                self.key("selection"),
            )

    def complete_to_claims(self) -> tuple[str, dict]:
        execution_id, frozen = self.build_frozen()
        self.complete_selection(frozen)
        candidate_id = frozen["batches"][0]["candidate_ids"][0]
        self.service.submit_verifications(
            execution_id,
            {
                "verifications": [
                    {
                        "candidate_id": candidate_id,
                        "verification_status": "verified",
                        "identity": {"status": "confirmed", "evidence": "Identidade oficial."},
                        "relator": {"status": "confirmed", "name": "Fulano de Tal", "evidence": "Cabeçalho."},
                        "theme": {"class": "T1", "central_issue": "Dano moral", "evidence": "Ementa."},
                        "holding": {"text": "Recurso desprovido.", "page": 6},
                        "quantum": {"value": None, "currency": "BRL", "page": None},
                    }
                ]
            },
            self.key("verify"),
        )
        self.service.admit_sample(
            execution_id,
            {"candidates": [{"candidate_id": candidate_id, "bucket": "main"}]},
            self.key("sample"),
        )
        self.service.resolve_claims(
            execution_id,
            {
                "claims": [
                    {
                        "claim_id": "C1",
                        "status": "supported",
                        "allowed_scope": "descriptive holding",
                        "evidence_ids": ["EX-1"],
                        "authorized_processes": ["1000001-11.2024.8.26.0001"],
                        "authorized_amounts": [],
                        "authorized_dates": [],
                        "authorized_summulas": [],
                        "forbidden_inferences": ["trend", "frequency"],
                    }
                ]
            },
            self.key("claims"),
        )
        return execution_id, frozen

    def test_candidate_deduplication_and_query_linking(self) -> None:
        execution_id = self.create()
        self.discover(execution_id)
        first = self.candidate()
        second = dict(first)
        second["candidate_id"] = "CAND-DUP"
        second["query_ids"] = ["Q2"]
        response, _, _ = self.service.submit_candidates(
            execution_id, {"candidates": [first, second]}, self.key("candidate")
        )
        self.assertEqual(1, response["inserted"])
        self.assertEqual(1, response["deduplicated"])
        with self.service.storage.session() as conn:
            self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM gptwf_candidates").fetchone()[0])
            self.assertEqual(2, conn.execute("SELECT COUNT(*) FROM gptwf_candidate_queries").fetchone()[0])

    def test_selection_before_freeze_is_rejected(self) -> None:
        execution_id = self.create()
        self.discover(execution_id)
        response, _, _ = self.service.submit_candidates(
            execution_id, {"candidates": [self.candidate()]}, self.key("candidate")
        )
        repository = response["repository"]
        with self.assertRaises(WorkflowError) as raised:
            self.service.submit_selection(
                repository["repository_id"],
                {
                    "batch_id": "BATCH-X",
                    "repository_id": repository["repository_id"],
                    "repository_version": 1,
                    "assessments": [],
                },
                self.key("selection"),
            )
        self.assertIn(raised.exception.code, {"BATCH_REPOSITORY_MISMATCH", "REPOSITORY_NOT_FROZEN"})

    def test_new_candidate_after_freeze_creates_new_version(self) -> None:
        execution_id, frozen = self.build_frozen()
        response, _, _ = self.service.submit_candidates(
            execution_id,
            {"candidates": [self.candidate("CAND-0002", "1000002-11.2024.8.26.0001")]},
            self.key("revision"),
        )
        self.assertEqual(2, response["repository"]["repository_version"])
        self.assertEqual(2, response["repository"]["candidate_count"])
        with self.service.storage.session() as conn:
            self.assertEqual(
                "frozen",
                conn.execute(
                    "SELECT status FROM gptwf_repositories WHERE repository_id=? AND version=1",
                    (frozen["repository_receipt"]["repository_id"],),
                ).fetchone()[0],
            )

    def test_batch_from_other_repository_is_rejected(self) -> None:
        _, frozen_one = self.build_frozen()
        _, frozen_two = self.build_frozen()
        batch = frozen_one["batches"][0]
        receipt = frozen_two["repository_receipt"]
        with self.assertRaises(WorkflowError) as raised:
            self.service.submit_selection(
                receipt["repository_id"],
                {
                    "batch_id": batch["batch_id"],
                    "repository_id": receipt["repository_id"],
                    "repository_version": receipt["repository_version"],
                    "assessments": [],
                },
                self.key("wrong-repo"),
            )
        self.assertEqual("BATCH_REPOSITORY_MISMATCH", raised.exception.code)

    def test_incomplete_selection_is_rejected(self) -> None:
        _, frozen = self.build_frozen(2)
        batch = frozen["batches"][0]
        receipt = frozen["repository_receipt"]
        with self.assertRaises(WorkflowError) as raised:
            self.service.submit_selection(
                receipt["repository_id"],
                {
                    "batch_id": batch["batch_id"],
                    "repository_id": receipt["repository_id"],
                    "repository_version": 1,
                    "assessments": [],
                },
                self.key("incomplete"),
            )
        self.assertEqual("SELECTION_INCOMPLETE", raised.exception.code)

    def test_main_requires_verified_candidate_and_confirmed_relator(self) -> None:
        execution_id, frozen = self.build_frozen()
        self.complete_selection(frozen)
        candidate_id = frozen["batches"][0]["candidate_ids"][0]
        self.service.submit_verifications(
            execution_id,
            {
                "verifications": [
                    {
                        "candidate_id": candidate_id,
                        "verification_status": "verified",
                        "relator": {"status": "unconfirmed"},
                    }
                ]
            },
            self.key("verify"),
        )
        with self.assertRaises(WorkflowError) as raised:
            self.service.admit_sample(
                execution_id,
                {"candidates": [{"candidate_id": candidate_id, "bucket": "main"}]},
                self.key("sample"),
            )
        self.assertEqual("MAIN_RELATOR_NOT_CONFIRMED", raised.exception.code)

    def test_audit_blocks_unauthorized_entities_and_trend(self) -> None:
        execution_id, frozen = self.complete_to_claims()
        receipt = frozen["repository_receipt"]
        result, _, _ = self.service.audit_draft(
            execution_id,
            {
                "repository_id": receipt["repository_id"],
                "repository_version": 1,
                "draft_text": "A tendência inclui o processo 9999999-99.2024.8.26.0001 e R$ 9.000,00, conforme Súmula 385.",
                "statements": [
                    {
                        "statement_id": "S1",
                        "text": "A tendência inclui o processo 9999999-99.2024.8.26.0001 e R$ 9.000,00, conforme Súmula 385.",
                        "claim_id": "C1",
                        "evidence_ids": ["EX-1"],
                        "entities": {"processes": [], "amounts": [], "dates": [], "summulas": [], "magistrates": [], "chambers": []},
                    }
                ],
            },
            self.key("audit"),
        )
        self.assertEqual("blocked", result["status"])
        codes = {item["code"] for item in result["violations"]}
        self.assertTrue({"UNAUTHORIZED_PROCESS", "UNAUTHORIZED_AMOUNT", "UNAUTHORIZED_SUMULA", "UNAUTHORIZED_TREND"}.issubset(codes))
        self.assertEqual(0, result["releases"]["answer_release"])

    def test_valid_draft_is_released_and_immutable(self) -> None:
        execution_id, frozen = self.complete_to_claims()
        receipt = frozen["repository_receipt"]
        payload = {
            "repository_id": receipt["repository_id"],
            "repository_version": 1,
            "draft_text": "No processo 1000001-11.2024.8.26.0001, o recurso foi desprovido.",
            "statements": [
                {
                    "statement_id": "S1",
                    "text": "No processo 1000001-11.2024.8.26.0001, o recurso foi desprovido.",
                    "claim_id": "C1",
                    "evidence_ids": ["EX-1"],
                    "entities": {"processes": ["1000001-11.2024.8.26.0001"], "amounts": [], "dates": [], "summulas": [], "magistrates": [], "chambers": []},
                }
            ],
        }
        result, _, _ = self.service.audit_draft(execution_id, payload, self.key("audit"))
        self.assertEqual("released", result["status"])
        self.assertEqual(1, self.service.get_release(execution_id)["releases"]["answer_release"])
        with self.assertRaises(WorkflowError) as raised:
            changed = dict(payload)
            changed["draft_text"] = payload["draft_text"] + " Texto alterado."
            self.service.audit_draft(execution_id, changed, self.key("changed"))
        self.assertEqual("DRAFT_CHANGED_AFTER_RELEASE", raised.exception.code)

    def test_idempotency_conflict_and_recovery_after_restart(self) -> None:
        key = self.key("idempotent")
        first, _, replay = self.service.create_execution({"input": {"a": 1}}, key)
        second, _, replay_second = self.service.create_execution({"input": {"a": 1}}, key)
        self.assertEqual(first, second)
        self.assertFalse(replay)
        self.assertTrue(replay_second)
        with self.assertRaises(WorkflowError) as raised:
            self.service.create_execution({"input": {"a": 2}}, key)
        self.assertEqual("IDEMPOTENCY_CONFLICT", raised.exception.code)
        restarted = WorkflowService(self.config)
        self.assertEqual("CREATED", restarted.get_execution(first["execution"]["execution_id"])["state"])

    def test_limits_warning_restriction_and_read_during_restriction(self) -> None:
        execution_id = self.create()
        warning_service = WorkflowService(replace(self.config, simulated_disk_percent=72))
        self.assertEqual("warning", warning_service.health()["storage"]["status"])
        restricted = WorkflowService(replace(self.config, simulated_disk_percent=87))
        self.assertEqual("restricted", restricted.health()["storage"]["status"])
        self.assertEqual(execution_id, restricted.get_execution(execution_id)["execution_id"])
        with self.assertRaises(WorkflowError) as raised:
            restricted.create_execution({"input": {"x": 1}}, self.key("restricted"))
        self.assertEqual("DISK_HARD_LIMIT_REACHED", raised.exception.code)

    def test_payload_and_candidate_count_limits(self) -> None:
        small = WorkflowService(
            replace(self.config, request_max_bytes=80, candidates_max_count=1)
        )
        with self.assertRaises(WorkflowError) as raised:
            small.create_execution({"input": {"text": "x" * 200}}, self.key("large"))
        self.assertEqual("PAYLOAD_TOO_LARGE", raised.exception.code)
        execution_id = self.create()
        self.discover(execution_id)
        one = WorkflowService(replace(self.config, candidates_max_count=1))
        with self.assertRaises(WorkflowError) as count_error:
            one.submit_candidates(
                execution_id,
                {"candidates": [self.candidate(), self.candidate("CAND-2", "1000002-11.2024.8.26.0001")]},
                self.key("count"),
            )
        self.assertEqual("EXECUTION_STORAGE_LIMIT", count_error.exception.code)

    def test_cleanup_preserves_receipts_and_is_namespace_limited(self) -> None:
        execution_id, frozen = self.complete_to_claims()
        receipt_hash = self.service.get_execution(execution_id)["workflow_receipt"]["receipt_hash"]
        with self.service.storage.transaction() as conn:
            conn.execute("CREATE TABLE unrelated_data(value TEXT)")
            conn.execute("INSERT INTO unrelated_data VALUES ('preserve')")
            conn.execute(
                "UPDATE gptwf_executions SET retention_state='EXPIRED',state='ANSWER_RELEASED' WHERE execution_id=?",
                (execution_id,),
            )
        result, _, _ = self.service.cleanup({}, self.key("cleanup"))
        self.assertIn(execution_id, result["cleaned_execution_ids"])
        recovered = self.service.get_execution(execution_id)
        self.assertEqual(receipt_hash, recovered["workflow_receipt"]["receipt_hash"])
        self.assertEqual("AUDIT_MINIMUM", recovered["retention_state"])
        with self.service.storage.session() as conn:
            self.assertEqual("preserve", conn.execute("SELECT value FROM unrelated_data").fetchone()[0])
            self.assertGreater(conn.execute("SELECT COUNT(*) FROM gptwf_receipts WHERE execution_id=?", (execution_id,)).fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
