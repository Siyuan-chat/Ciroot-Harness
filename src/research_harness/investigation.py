"""Offline, resumable D19-P1 investigation service."""
from __future__ import annotations
import hashlib, json, sqlite3, time, uuid
from pathlib import Path
from typing import Any
from .errors import HarnessError, ValidationError, NotFoundError, UnsupportedError
from langgraph.graph import StateGraph, START, END
from jsonschema import validate

ROLES=("planning","paper_search","patent_search","evidence_analysis","business_judgment","synthesis","writing","verification")

class InvestigationError(HarnessError):
    code="RH_INVESTIGATION"
    def __init__(self, code="RH_INVESTIGATION", message="investigation failed"): self.code=code; self.message=message
    def to_dict(self): return {"code":self.code,"message":self.message}

class InvestigationService:
    def __init__(self, workspace):
        self.root=Path(workspace); self.root.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.root/"investigation.sqlite"); self.db.row_factory=sqlite3.Row
        self.db.executescript("""CREATE TABLE IF NOT EXISTS investigations(id TEXT PRIMARY KEY,spec TEXT,runtime TEXT,status TEXT,stage TEXT,budget TEXT,created REAL,updated REAL,result TEXT);
CREATE TABLE IF NOT EXISTS model_tasks(id TEXT PRIMARY KEY,run_id TEXT,task_version INTEGER,role TEXT,task_type TEXT,payload TEXT,output_schema TEXT,status TEXT,result TEXT,UNIQUE(run_id,role,task_version));""")
        self.db.commit()
    def close(self): self.db.close()
    def __enter__(self): return self
    def __exit__(self,*_): self.close()
    def doctor(self): return {"ok":True,"mode":"offline","network":"disabled","data_mode":"synthetic","missing":[],"capabilities":{"langgraph":True,"model_api":False,"sources":"synthetic_only"}}
    def validate_plan(self, plan):
        if not isinstance(plan,dict) or not plan.get("research_question"): raise ValidationError()
        return {"valid":True,"mode":"offline","sources":plan.get("sources",[]),"budget":plan.get("budget",{})}
    def create_investigation(self,spec,runtime,scenario=None):
        if spec.get("status")!="ready" or runtime.get("mode")!="host" or runtime.get("data_mode")!="synthetic": raise InvestigationError("RH_PRECONDITION","ready synthetic host inputs are required")
        run="inv-"+uuid.uuid4().hex[:12]; now=time.time(); budget=runtime.get("budget",{})
        self.db.execute("INSERT INTO investigations VALUES (?,?,?,?,?,?,?,?,?)",(run,json.dumps(spec),json.dumps(runtime),"running","planning",json.dumps(budget),now,now,None)); self.db.commit()
        self._task(run,"planning","plan",{"spec":spec,"scenario":scenario or {}},{"type":"object","required":["summary"],"properties":{"summary":{"type":"string","minLength":1}}}); return {"run_id":run,"stage":"planning","status":"waiting_model"}
    def _task(self,run,role,kind,payload,schema):
        payload={"input_refs":payload.get("input_refs",[]),"allowed_operations":["submit_structured_result"],**payload}
        self.db.execute("INSERT INTO model_tasks VALUES (?,?,?,?,?,?,?,?,?)",("task-"+uuid.uuid4().hex[:12],run,1,role,kind,json.dumps(payload),json.dumps(schema),"pending",None));self.db.commit()
    def get_pending_tasks(self,run_id):
        return [{"task_id":r["id"],"task_version":r["task_version"],"role":r["role"],"task_type":r["task_type"],"input_refs":json.loads(r["payload"]).get("input_refs",[]),"payload":json.loads(r["payload"]),"output_schema":json.loads(r["output_schema"]),"allowed_operations":json.loads(r["payload"]).get("allowed_operations",[])} for r in self.db.execute("SELECT id,task_version,role,task_type,payload,output_schema FROM model_tasks WHERE run_id=? AND status='pending'",(run_id,))]
    def submit_model_result(self,run_id,task_id,result,task_version):
        row=self.db.execute("SELECT * FROM model_tasks WHERE id=? AND run_id=?",(task_id,run_id)).fetchone()
        if not row: raise NotFoundError()
        if row["task_version"]!=task_version: raise InvestigationError("RH_TASK_VERSION","task version is stale")
        value=json.dumps(result,sort_keys=True)
        if row["status"]=="completed":
            if row["result"]==value:return {"status":"reused","task_id":task_id}
            raise InvestigationError("RH_TASK_CONFLICT","different task result was submitted")
        schema=json.loads(row["output_schema"])
        try: validate(result,schema)
        except Exception as exc: raise ValidationError() from exc
        self.db.execute("UPDATE model_tasks SET status='completed',result=? WHERE id=?",(value,task_id));self.db.commit();return {"status":"accepted","task_id":task_id}
    def advance_investigation(self,run_id):
        row=self.db.execute("SELECT * FROM investigations WHERE id=?",(run_id,)).fetchone()
        if not row: raise NotFoundError()
        def planning_gate(state):
            if self.get_pending_tasks(run_id): return "waiting"
            done=self.db.execute("SELECT COUNT(*) FROM model_tasks WHERE run_id=?",(run_id,)).fetchone()[0]
            if done>=len(ROLES): return "complete"
            prior=[r[0] for r in self.db.execute("SELECT id FROM model_tasks WHERE run_id=? AND status='completed' ORDER BY rowid",(run_id,))]
            role=ROLES[done]; self._task(run_id,role,role,{"input_refs":prior,"consumed_results":[json.loads(x[0]) for x in self.db.execute("SELECT result FROM model_tasks WHERE run_id=? AND status='completed'",(run_id,))]},{"type":"object","required":["summary"],"properties":{"summary":{"type":"string","minLength":1}}}); self.db.execute("UPDATE investigations SET stage=?,status='waiting_model',updated=? WHERE id=?",(role,time.time(),run_id));self.db.commit();return "waiting"
        g=StateGraph(dict);g.add_node("planning_gate",lambda s:{"next":planning_gate(s)});g.add_node("source_task",lambda s:s);g.add_node("acquire_normalize",lambda s:s);g.add_node("analysis_task",lambda s:s);g.add_node("verification_gate",lambda s:s);g.add_edge(START,"planning_gate");g.add_conditional_edges("planning_gate",lambda s:s["next"],{"waiting":END,"complete":END});out=g.compile().invoke({})
        if out["next"]=="complete": self.db.execute("UPDATE investigations SET status='completed',stage='completed',updated=? WHERE id=?",(time.time(),run_id));self.db.commit();return {"run_id":run_id,"outcome":"completed","stage":"completed"}
        now=self.status(run_id);return {"run_id":run_id,"outcome":"waiting","waiting_reason":"model_task","stage":now["stage"]}
    def resume_investigation(self,run_id): return self.advance_investigation(run_id)
    def status(self,run_id=None):
        if run_id:
            r=self.db.execute("SELECT * FROM investigations WHERE id=?",(run_id,)).fetchone()
            if not r: raise NotFoundError()
            return {"run_id":r["id"],"status":r["status"],"stage":r["stage"],"budget":json.loads(r["budget"])}
        return {"runs":[self.status(r["id"]) for r in self.db.execute("SELECT id FROM investigations ORDER BY created DESC")]}
