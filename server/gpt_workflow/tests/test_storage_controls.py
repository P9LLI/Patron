from __future__ import annotations

import logging
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from server.gpt_workflow.config import WorkflowConfig
from server.gpt_workflow.errors import WorkflowError
from server.gpt_workflow.service import WorkflowService


class StorageControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        root = Path(self.temp.name)
        self.config = WorkflowConfig(
            db_path=root / "workflow.db",
            log_path=root / "workflow.log",
            log_max_bytes=300,
            log_backup_count=2,
            repository_versions_max=2,
        )
        self.service = WorkflowService(self.config)

    def tearDown(self) -> None:
        logging.shutdown()
        self.temp.cleanup()

    def test_rotating_logger_bounds_file_count(self) -> None:
        for index in range(100):
            self.service.storage.logger.info(
                "event=rotation_probe execution_id=exec-test index=%s", index
            )
        files = list(self.config.log_path.parent.glob("workflow.log*"))
        self.assertGreaterEqual(len(files), 2)
        self.assertLessEqual(len(files), self.config.log_backup_count + 1)
        self.assertLessEqual(self.config.log_path.stat().st_size, self.config.log_max_bytes)

    def test_interrupted_transaction_rolls_back_cleanly(self) -> None:
        created, _, _ = self.service.create_execution(
            {"input": {"question": "q"}}, "interruption-create"
        )
        execution_id = created["execution"]["execution_id"]
        with self.assertRaises(RuntimeError):
            with self.service.storage.transaction() as conn:
                conn.execute(
                    "UPDATE gptwf_executions SET state='ANSWER_RELEASED' WHERE execution_id=?",
                    (execution_id,),
                )
                raise RuntimeError("simulated interruption")
        self.assertEqual("CREATED", self.service.get_execution(execution_id)["state"])
        with self.service.storage.session() as conn:
            self.assertEqual("ok", conn.execute("PRAGMA integrity_check").fetchone()[0])

    def test_warning_runs_namespace_only_safe_cleanup(self) -> None:
        warning = WorkflowService(replace(self.config, simulated_disk_percent=72))
        with warning.storage.transaction() as conn:
            conn.execute("CREATE TABLE unrelated_cleanup_probe(value TEXT)")
            conn.execute("INSERT INTO unrelated_cleanup_probe VALUES ('preserve')")
            conn.execute(
                """
                INSERT INTO gptwf_idempotency
                VALUES ('expired','probe','hash',200,'{}','2020-01-01T00:00:00+00:00','2020-01-02T00:00:00+00:00')
                """
            )
        warning.storage.guard_growth("probe")
        with warning.storage.session() as conn:
            self.assertEqual(
                0,
                conn.execute(
                    "SELECT COUNT(*) FROM gptwf_idempotency WHERE idempotency_key='expired'"
                ).fetchone()[0],
            )
            self.assertEqual(
                "preserve",
                conn.execute("SELECT value FROM unrelated_cleanup_probe").fetchone()[0],
            )

    def test_repository_version_limit_is_enforced(self) -> None:
        body, _, _ = self.service.create_execution(
            {"input": {"question": "q"}}, "version-create"
        )
        execution_id = body["execution"]["execution_id"]
        self.service.submit_queries(
            execution_id,
            {"queries": [{"query_id": "Q1", "text": "query"}]},
            "version-query",
        )

        def candidate(number: int) -> dict:
            return {
                "candidate_id": f"CAND-{number}",
                "source_url": f"https://example.invalid/{number}",
                "process_number": f"{1000000 + number:07d}-11.2024.8.26.0001",
                "query_ids": ["Q1"],
                "excerpts": {"identity": "evidence"},
            }

        self.service.submit_candidates(
            execution_id, {"candidates": [candidate(1)]}, "version-candidate-1"
        )
        self.service.freeze_repository(execution_id, {}, "version-freeze-1")
        self.service.submit_candidates(
            execution_id, {"candidates": [candidate(2)]}, "version-candidate-2"
        )
        self.service.freeze_repository(execution_id, {}, "version-freeze-2")
        with self.assertRaises(WorkflowError) as raised:
            self.service.submit_candidates(
                execution_id, {"candidates": [candidate(3)]}, "version-candidate-3"
            )
        self.assertEqual("REPOSITORY_VERSION_LIMIT", raised.exception.code)


if __name__ == "__main__":
    unittest.main()
