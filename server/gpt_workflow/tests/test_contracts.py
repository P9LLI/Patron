from __future__ import annotations

import json
import unittest
from pathlib import Path

import yaml


class WorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1] / "contracts"
        cls.openapi = yaml.safe_load((cls.root / "openapi.yaml").read_text(encoding="utf-8"))
        cls.integration = yaml.safe_load(
            (cls.root / "integration-contract-v1.yaml").read_text(encoding="utf-8")
        )

    def test_required_handoff_files_are_parseable(self) -> None:
        json.loads((self.root / "backend-examples.json").read_text(encoding="utf-8"))
        json.loads((self.root / "version-matrix.json").read_text(encoding="utf-8"))
        for name in (
            "error-catalog.md",
            "test-environment.md",
            "storage-policy-report.md",
        ):
            self.assertTrue((self.root / name).read_text(encoding="utf-8").strip())

    def test_operation_ids_are_unique_and_complete(self) -> None:
        operations = [
            operation
            for path in self.openapi["paths"].values()
            for operation in path.values()
            if isinstance(operation, dict) and "operationId" in operation
        ]
        operation_ids = [operation["operationId"] for operation in operations]
        self.assertEqual(14, len(operation_ids))
        self.assertEqual(len(operation_ids), len(set(operation_ids)))
        self.assertEqual(
            set(operation_ids),
            {item["operationId"] for item in self.integration["operations"]},
        )

    def test_all_local_refs_resolve(self) -> None:
        unresolved: list[str] = []

        def walk(value: object) -> None:
            if isinstance(value, dict):
                ref = value.get("$ref")
                if isinstance(ref, str) and ref.startswith("#/"):
                    node: object = self.openapi
                    for token in ref[2:].split("/"):
                        if not isinstance(node, dict) or token not in node:
                            unresolved.append(ref)
                            break
                        node = node[token]
                for nested in value.values():
                    walk(nested)
            elif isinstance(value, list):
                for nested in value:
                    walk(nested)

        walk(self.openapi)
        self.assertEqual([], unresolved)

    def test_every_mutation_declares_idempotency_and_bearer(self) -> None:
        for path, path_item in self.openapi["paths"].items():
            for method, operation in path_item.items():
                if method == "post":
                    parameters = operation.get("parameters", [])
                    self.assertIn(
                        {"$ref": "#/components/parameters/IdempotencyKey"},
                        parameters,
                        path,
                    )
                if path != "/gpt-workflow/v1/health":
                    self.assertEqual([{"serviceBearer": []}], operation.get("security"), path)


if __name__ == "__main__":
    unittest.main()
