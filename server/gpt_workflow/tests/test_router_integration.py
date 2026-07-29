from __future__ import annotations

import importlib
import logging
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:
    FastAPI = TestClient = None


@unittest.skipIf(TestClient is None, "FastAPI test dependencies are unavailable")
class WorkflowRouterIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        root = Path(cls.temp.name)
        os.environ["GPT_WORKFLOW_DB"] = str(root / "workflow.db")
        os.environ["GPT_WORKFLOW_LOG"] = str(root / "workflow.log")
        os.environ["GPT_WORKFLOW_API_BEARER_TOKEN"] = "integration-token"

        previous = types.ModuleType("server.main_pj1_validator")
        previous.app = FastAPI()

        @previous.app.get("/legacy-probe")
        def legacy_probe() -> dict[str, bool]:
            return {"legacy": True}

        sys.modules["server.main_pj1_validator"] = previous
        for name in ("server.gpt_workflow.router", "server.main_gpt_workflow"):
            sys.modules.pop(name, None)
        cls.module = importlib.import_module("server.main_gpt_workflow")
        cls.client = TestClient(cls.module.app)

    @classmethod
    def tearDownClass(cls) -> None:
        logging.shutdown()
        cls.temp.cleanup()

    def test_preserves_imported_application_routes(self) -> None:
        self.assertEqual({"legacy": True}, self.client.get("/legacy-probe").json())

    def test_health_is_public_and_reports_storage(self) -> None:
        response = self.client.get("/gpt-workflow/v1/health")
        self.assertEqual(200, response.status_code)
        self.assertIn(response.json()["storage"]["status"], {"ok", "warning", "restricted", "critical"})

    def test_mutation_requires_bearer_and_idempotency(self) -> None:
        self.assertEqual(
            401,
            self.client.post(
                "/gpt-workflow/v1/executions",
                json={"input": {"question": "q"}},
                headers={"Idempotency-Key": "integration-unauthorized"},
            ).status_code,
        )
        response = self.client.post(
            "/gpt-workflow/v1/executions",
            json={"input": {"question": "q"}},
            headers={
                "Authorization": "Bearer integration-token",
                "Idempotency-Key": "integration-authorized",
            },
        )
        self.assertEqual(201, response.status_code)
        self.assertEqual("false", response.headers["X-GPT-Workflow-Idempotent-Replay"])
        replay = self.client.post(
            "/gpt-workflow/v1/executions",
            json={"input": {"question": "q"}},
            headers={
                "Authorization": "Bearer integration-token",
                "Idempotency-Key": "integration-authorized",
            },
        )
        self.assertEqual("true", replay.headers["X-GPT-Workflow-Idempotent-Replay"])
        self.assertEqual(response.json(), replay.json())
