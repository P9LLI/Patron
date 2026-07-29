from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path

from server.gpt_workflow.config import WorkflowConfig
from server.gpt_workflow.service import WorkflowService


class BatchMaterializationTests(unittest.TestCase):
    def test_batch_reconstructs_candidate_from_document_and_link(self) -> None:
        temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        try:
            root = Path(temp.name)
            service = WorkflowService(
                WorkflowConfig(db_path=root / "workflow.db", log_path=root / "workflow.log")
            )
            created, _, _ = service.create_execution(
                {"input": {"question": "q"}}, "batch-create"
            )
            execution_id = created["execution"]["execution_id"]
            service.submit_queries(
                execution_id,
                {"queries": [{"query_id": "Q1", "text": "q"}]},
                "batch-query",
            )
            service.submit_candidates(
                execution_id,
                {
                    "candidates": [
                        {
                            "candidate_id": "CAND-1",
                            "source_url": "https://example.invalid/case",
                            "tribunal": "TJSP",
                            "process_number": "1000001-11.2024.8.26.0001",
                            "query_ids": ["Q1"],
                            "excerpts": {"holding": "Trecho."},
                        }
                    ]
                },
                "batch-candidate",
            )
            frozen, _, _ = service.freeze_repository(
                execution_id, {}, "batch-freeze"
            )
            receipt = frozen["repository_receipt"]
            batch = service.get_batch(
                receipt["repository_id"], frozen["batches"][0]["batch_id"]
            )
            self.assertEqual("CAND-1", batch["candidates"][0]["candidate_id"])
            self.assertEqual("TJSP", batch["candidates"][0]["tribunal"])
            self.assertEqual(["Q1"], batch["candidates"][0]["query_ids"])
            with service.storage.session() as conn:
                document = conn.execute(
                    "SELECT normalized_json FROM gptwf_documents"
                ).fetchone()[0]
                self.assertNotIn("candidate_id", document)
                self.assertNotIn("query_ids", document)
        finally:
            logging.shutdown()
            temp.cleanup()


if __name__ == "__main__":
    unittest.main()
