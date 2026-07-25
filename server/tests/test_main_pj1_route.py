from __future__ import annotations

import importlib
import sys
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _install_server_dependency_stubs() -> None:
    """Allow route-contract testing without installing deployment packages."""

    fastapi = types.ModuleType("fastapi")

    class FastAPI:
        def __init__(self, *args, **kwargs):
            pass

        def get(self, *args, **kwargs):
            return lambda function: function

        def post(self, *args, **kwargs):
            return lambda function: function

        def on_event(self, *args, **kwargs):
            return lambda function: function

    class HTTPException(Exception):
        pass

    class Request:
        pass

    def Form(value=None, *args, **kwargs):
        return value

    fastapi.FastAPI = FastAPI
    fastapi.Form = Form
    fastapi.HTTPException = HTTPException
    fastapi.Request = Request
    sys.modules["fastapi"] = fastapi

    responses = types.ModuleType("fastapi.responses")
    responses.HTMLResponse = str
    sys.modules["fastapi.responses"] = responses

    stripe = types.ModuleType("stripe")
    stripe.Customer = types.SimpleNamespace(search=lambda **kwargs: types.SimpleNamespace(data=[]))
    stripe.Subscription = types.SimpleNamespace(list=lambda **kwargs: types.SimpleNamespace(data=[]))
    stripe.Webhook = types.SimpleNamespace(construct_event=lambda **kwargs: {})
    stripe.error = types.SimpleNamespace(SignatureVerificationError=ValueError)
    sys.modules["stripe"] = stripe


class MainV142Pj1RouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _install_server_dependency_stubs()
        sys.modules.pop("server.main", None)
        sys.modules.pop("server.main_pj1", None)
        cls.module = importlib.import_module("server.main_pj1")

    def test_route_derives_mode_server_side_before_adapter(self) -> None:
        captured: dict = {}
        self.module.is_blocked = lambda user_id: False
        self.module.is_rate_limited = lambda user_id, bucket: False
        self.module.is_subscription_active = lambda *args: True
        self.module.log_event = lambda **kwargs: None
        self.module.log_abuse = lambda **kwargs: None
        self.module.detect_extraction_attempt = lambda message: False
        self.module._build_mode = lambda message: "p2"

        def fake_adapter(payload: dict) -> dict:
            captured.update(payload)
            return {"ok": 1, "v142": {"ok": 1}, "pj1": {"active": True}}

        self.module.run_integrated = fake_adapter
        payload = self.module.ResearchPlanRequest(
            user_id="advogado@example.com",
            oab_number="12345",
            oab_state="SP",
            v142={
                "q": "Pesquisar precedentes sobre responsabilidade civil",
                "tt": "jurisprudencia",
                "tr": ["TJSP"],
                "pd": "2024",
                "cx": "Fatos materiais suficientes.",
                "of": "relatorio",
                "m": "s4",
            },
            pj1={"research_mode": "application"},
        )
        request = types.SimpleNamespace(client=types.SimpleNamespace(host="127.0.0.1"))

        response = self.module.build_auditable_research_plan(payload, request)

        self.assertEqual(response["status"], "ok")
        self.assertEqual(response["mode"], "p2")
        self.assertEqual(captured["v142"]["m"], "p2")
        self.assertEqual(captured["pj1"], {"research_mode": "application"})


if __name__ == "__main__":
    unittest.main()
