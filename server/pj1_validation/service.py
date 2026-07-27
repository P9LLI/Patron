from __future__ import annotations
import hashlib,json,sqlite3
from copy import deepcopy
from pathlib import Path
from threading import RLock
from jsonschema import Draft202012Validator,FormatChecker
from .core import validate_request
class RequestContractError(ValueError):
 def __init__(self,errors): super().__init__("request inv?lido"); self.errors=errors
class IdempotencyConflictError(ValueError):pass
class ResponseContractError(RuntimeError):pass
def errors(v,p): return [{"path":"/"+"/".join(map(str,e.absolute_path)),"message":e.message} for e in sorted(v.iter_errors(p),key=lambda x:list(x.absolute_path))]
def canonical(p): return json.dumps(p,ensure_ascii=False,sort_keys=True,separators=(",",":"))
class SQLiteIdempotencyStore:
 def __init__(self,path=":memory:"):
  self.path=str(path); self.lock=RLock(); self.db=sqlite3.connect(self.path,check_same_thread=False); self.db.execute("CREATE TABLE IF NOT EXISTS pj1_idempotency (key TEXT PRIMARY KEY, request_digest TEXT NOT NULL, response_json TEXT NOT NULL)"); self.db.commit()
 def get(self,key):
  with self.lock:
   row=self.db.execute("SELECT request_digest,response_json FROM pj1_idempotency WHERE key=?",(key,)).fetchone()
  return None if row is None else (row[0],json.loads(row[1]))
 def close(self):
  with self.lock: self.db.close()
 def put(self,key,digest,response):
  payload=canonical(response)
  with self.lock:
   try: self.db.execute("INSERT INTO pj1_idempotency VALUES (?,?,?)",(key,digest,payload)); self.db.commit()
   except sqlite3.IntegrityError: pass
class ValidationService:
 def __init__(self,contract_path=None,store=None):
  path=contract_path or Path(__file__).resolve().parent/"pj1_validation_contract_v1.schema.json"; self.v=Draft202012Validator(json.loads(path.read_text(encoding="utf-8")),format_checker=FormatChecker()); self.store=store or SQLiteIdempotencyStore(); self.lock=RLock()
 def validate(self,payload):
  bad=errors(self.v,payload)
  if bad: raise RequestContractError(bad)
  key=payload["idempotency_key"]; digest=hashlib.sha256(canonical(payload).encode()).hexdigest()
  with self.lock:
   saved=self.store.get(key)
   if saved:
    old,response=saved
    if old!=digest: raise IdempotencyConflictError("chave reutilizada com payload diferente")
    return deepcopy(response),True
   response=validate_request(payload); bad=errors(self.v,response)
   if bad: raise ResponseContractError(str(bad))
   self.store.put(key,digest,response); saved=self.store.get(key)
   if saved and saved[0]!=digest: raise IdempotencyConflictError("conflito concorrente de idempot?ncia")
   return response,False
