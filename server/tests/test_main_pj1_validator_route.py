from __future__ import annotations
import json,os,sys,tempfile,types,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; PROJECT=ROOT.parent; sys.path.insert(0,str(ROOT))
try:
 from fastapi import FastAPI
 from fastapi.testclient import TestClient
except ImportError: FastAPI=TestClient=None
@unittest.skipIf(TestClient is None,"fastapi ausente")
class RouteTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tmp=tempfile.TemporaryDirectory(); os.environ["PJ1_API_BEARER_TOKEN"]="deploy-test-token"; os.environ["PJ1_IDEMPOTENCY_DB"]=str(Path(cls.tmp.name)/"pj1.sqlite")
  fake=types.ModuleType("server.main_pj1"); fake.app=FastAPI()
  @fake.app.get("/legacy-probe")
  def legacy_probe(): return {"legacy":True}
  sys.modules["server.main_pj1"]=fake
  from server import main_pj1_validator
  cls.module=main_pj1_validator; cls.client=TestClient(main_pj1_validator.app); cls.fixture=PROJECT/"entregaveis/PJ1_VALIDATION_FIXTURES_V1/requests/PJ1-REG-CORPUS-006.request.json"
 @classmethod
 def tearDownClass(cls): cls.module.service.store.close(); cls.tmp.cleanup()
 def payload(self):
  p=json.loads(self.fixture.read_text(encoding="utf-8")); p["idempotency_key"]+=".deploy.route"; return p
 def test_preserves_imported_routes(self): self.assertEqual({"legacy":True},self.client.get("/legacy-probe").json())
 def test_requires_service_token(self): self.assertEqual(401,self.client.post("/v1/pj1/validate",json=self.payload()).status_code)
 def test_validates_and_replays(self):
  h={"Authorization":"Bearer deploy-test-token"}; a=self.client.post("/v1/pj1/validate",json=self.payload(),headers=h); b=self.client.post("/v1/pj1/validate",json=self.payload(),headers=h); self.assertEqual(200,a.status_code); self.assertEqual("true",b.headers["X-PJ1-Idempotent-Replay"])
