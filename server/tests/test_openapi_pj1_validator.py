import json,unittest
from pathlib import Path
P=Path(__file__).resolve().parents[1]/"openapi_pj1_validator.json"
class OpenAPITests(unittest.TestCase):
 @classmethod
 def setUpClass(c): c.s=json.loads(P.read_text(encoding="utf-8"))
 def resolve(self,ref):
  x=self.s
  for p in ref[2:].split("/"): x=x[p]
  return x
 def test_preserves_legacy_and_adds_validator(self): self.assertIn("/validateSubscription",self.s["paths"]); self.assertIn("/v14_2/pj1/research-plan",self.s["paths"]); self.assertIn("/v1/pj1/validate",self.s["paths"])
 def test_all_refs_resolve(self):
  def walk(x):
   if isinstance(x,dict):
    for k,v in x.items(): self.resolve(v) if k=="$ref" else walk(v)
   elif isinstance(x,list):
    for v in x: walk(v)
  walk(self.s)
 def test_validator_uses_service_bearer(self): self.assertEqual([{"serviceBearer":[]}],self.s["paths"]["/v1/pj1/validate"]["post"]["security"])
