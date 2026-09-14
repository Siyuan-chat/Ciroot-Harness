"""Offline, resumable D19-P1 investigation orchestration."""
from __future__ import annotations

import hashlib, json, sqlite3, time, uuid
from pathlib import Path
from jsonschema import Draft202012Validator
from langgraph.graph import StateGraph, START, END
from .errors import HarnessError, NotFoundError, ValidationError
from .investigation_sources import SourceError, SyntheticTransport, baseline_snapshot, normalize, policy_allows

ROLES = ("planning", "paper_search", "patent_search", "evidence_analysis", "business_judgment", "synthesis", "writing", "verification")

class InvestigationError(HarnessError):
    def __init__(self, code="RH_INVESTIGATION", message="investigation failed"):
        self.code, self.message = code, message
    def to_dict(self): return {"code": self.code, "message": self.message}

def schema(key, item=None):
    p = {key: item or {"type": "object"}}
    return {"$schema":"https://json-schema.org/draft/2020-12/schema", "type":"object", "required":[key], "additionalProperties":False, "properties":p}

candidate = {"type":"object","required":["document_id","relevance","reason"],"additionalProperties":False,"properties":{"document_id":{"type":"string","minLength":1},"relevance":{"enum":["relevant","irrelevant","uncertain"]},"reason":{"type":"string","minLength":1}}}
finding = {"type":"object","required":["finding","evidence_ids"],"additionalProperties":False,"properties":{"finding":{"type":"string","minLength":1},"evidence_ids":{"type":"array","minItems":1,"items":{"type":"string"}}}}
TASK_SCHEMAS = {
 "planning": schema("search_plan", {"type":"object","required":["queries"],"additionalProperties":False,"properties":{"queries":{"type":"array","minItems":1,"items":{"type":"object","required":["source","query"],"additionalProperties":False,"properties":{"source":{"enum":["synthetic-paper","synthetic-patent"]},"query":{"type":"string","minLength":1}}}}}}),
 "paper_search": schema("candidates", {"type":"array","items":candidate}), "patent_search": schema("candidates", {"type":"array","items":candidate}),
 "evidence_analysis": schema("findings", {"type":"array","minItems":1,"items":finding}),
 "business_judgment": schema("judgments", {"type":"array","items":{"type":"object","required":["document_id","relevance","human_review_required","reason"],"additionalProperties":False,"properties":{"document_id":{"type":"string"},"relevance":{"enum":["relevant","irrelevant","uncertain"]},"human_review_required":{"type":"boolean"},"reason":{"type":"string","minLength":1}}}}),
 "synthesis": schema("claims", {"type":"array","minItems":1,"items":{"type":"object","required":["claim","finding_refs"],"additionalProperties":False,"properties":{"claim":{"type":"string","minLength":1},"finding_refs":{"type":"array","minItems":1,"items":{"type":"integer","minimum":0}}}}}),
 "writing": schema("sections", {"type":"array","minItems":1,"items":{"type":"object","required":["title","text","claim_refs"],"additionalProperties":False,"properties":{"title":{"type":"string","minLength":1},"text":{"type":"string","minLength":1},"claim_refs":{"type":"array","items":{"type":"integer","minimum":0}}}}}),
 "verification": schema("verification", {"type":"object","required":["status","conclusion","supported_claim_refs"],"additionalProperties":False,"properties":{"status":{"enum":["supported","partial","insufficient","contradicted"]},"conclusion":{"type":"string","minLength":1},"supported_claim_refs":{"type":"array","items":{"type":"integer","minimum":0}}}}),
}
# D19 C2 extensions remain optional for C1 compatibility, but are required
# before a frozen reader-facing ReportData object can be produced.
TASK_SCHEMAS["evidence_analysis"]["properties"]["findings"]["items"]["properties"].update({"finding_id":{"type":"string"},"value":{"type":["string","number","null"]},"unit":{"type":["string","null"]},"conditions":{"type":["string","null"]}})
TASK_SCHEMAS["synthesis"]["properties"]["claims"]["items"]["properties"].update({"claim_id":{"type":"string"},"evidence_refs":{"type":"array","items":{"type":"string"}},"quote":{"type":"string"},"document_id":{"type":"string"},"version_id":{"type":"string"}})
TASK_SCHEMAS["writing"]["properties"]["sections"]["items"]["properties"].update({"deliverable_type":{"enum":["technical_report","literature_review","patent_monitor_digest"]},"language":{"type":"string"},"section_id":{"type":"string"},"body":{"type":"string"},"claim_ids":{"type":"array","items":{"type":"string"}}})
TASK_SCHEMAS["planning"]["properties"]["search_plan"]["properties"]["queries"]["items"]["properties"].update({"query_id":{"type":"string"},"parent_query_id":{"type":["string","null"]},"input_refs":{"type":"array","items":{"type":"string"}}})

class InvestigationService:
    def __init__(self, workspace):
        self.root=Path(workspace); self.root.mkdir(parents=True, exist_ok=True)
        self.db=sqlite3.connect(self.root/"investigation.sqlite"); self.db.row_factory=sqlite3.Row
        self.db.executescript("""CREATE TABLE IF NOT EXISTS investigations(id TEXT PRIMARY KEY,spec TEXT NOT NULL,runtime TEXT NOT NULL,scenario TEXT NOT NULL,status TEXT NOT NULL,stage TEXT NOT NULL,budget TEXT NOT NULL,created REAL NOT NULL,updated REAL NOT NULL,result TEXT,trace TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS model_tasks(id TEXT PRIMARY KEY,run_id TEXT NOT NULL,task_version INTEGER NOT NULL,role TEXT NOT NULL,task_type TEXT NOT NULL,payload TEXT NOT NULL,output_schema TEXT NOT NULL,status TEXT NOT NULL,result TEXT,result_hash TEXT,created REAL NOT NULL, UNIQUE(run_id,role,task_type,task_version));""")
        self.db.execute("CREATE TABLE IF NOT EXISTS source_attempts(run_id TEXT,query_id TEXT,cursor TEXT,attempt INTEGER,status TEXT,result TEXT,PRIMARY KEY(run_id,query_id,cursor,attempt))")
        self.db.commit(); self.graph=self._graph()
    def close(self): self.db.close()
    def __enter__(self): return self
    def __exit__(self,*_): self.close()
    def doctor(self): return {"ok":True,"mode":"offline","network":"disabled","data_mode":"synthetic","missing":[],"capabilities":{"langgraph":True,"model_api":False,"sources":"synthetic_only"}}
    def validate_plan(self, plan):
        if not isinstance(plan,dict) or not isinstance(plan.get("research_question"),str) or not plan["research_question"].strip(): raise ValidationError()
        if plan.get("status") not in (None,"ready"): raise InvestigationError("RH_PLAN_STATUS","plan must be ready")
        return {"valid":True,"mode":"offline","sources":plan.get("sources",[]),"budget":plan.get("budget",{})}
    def create_investigation(self,spec,runtime,scenario=None):
        self.validate_plan(spec)
        if spec.get("status")!="ready" or runtime.get("mode")!="host" or runtime.get("data_mode")!="synthetic": raise InvestigationError("RH_PRECONDITION","ready synthetic host inputs are required")
        scenario=scenario or {}
        if not isinstance(scenario,dict) or not isinstance(scenario.get("sources",[]),list): raise InvestigationError("RH_SCENARIO","scenario.sources must be a list")
        scenario=dict(scenario); scenario["baseline_snapshot"]=baseline_snapshot(scenario.get("references",[]),runtime)
        run="inv-"+uuid.uuid4().hex[:12]; now=time.time(); budget=dict(runtime.get("budget",{})); budget.setdefault("max_tasks",8); budget.setdefault("max_source_calls",32); budget["reserved_tasks"]=0; budget["reserved_source_calls"]=0
        self.db.execute("INSERT INTO investigations VALUES (?,?,?,?,?,?,?,?,?,?,?)",(run,json.dumps(spec),json.dumps(runtime),json.dumps(scenario),"running","planning",json.dumps(budget),now,now,None,"[]")); self.db.commit()
        self._task(run,"planning","plan",{"spec":spec,"scenario_refs":["scenario:sources"],"baseline_evidence":scenario["baseline_snapshot"]}); self._set(run,status="waiting_model",stage="planning")
        return {"run_id":run,"stage":"planning","status":"waiting_model"}
    def get_pending_tasks(self,run_id):
        self._run(run_id); rows=self.db.execute("SELECT * FROM model_tasks WHERE run_id=? AND status='pending' ORDER BY created,id",(run_id,))
        return [{"task_id":r["id"],"task_version":r["task_version"],"role":r["role"],"task_type":r["task_type"],"input_refs":json.loads(r["payload"]).get("input_refs",[]),"payload":json.loads(r["payload"]),"output_schema":json.loads(r["output_schema"]),"allowed_operations":["submit_structured_result"]} for r in rows]
    def submit_model_result(self,run_id,task_id,result,task_version):
        row=self.db.execute("SELECT * FROM model_tasks WHERE id=? AND run_id=?",(task_id,run_id)).fetchone()
        if not row: raise NotFoundError()
        if row["task_version"]!=task_version: raise InvestigationError("RH_TASK_VERSION","task version is stale")
        raw=json.dumps(result,ensure_ascii=False,sort_keys=True,separators=(",",":")); digest=hashlib.sha256(raw.encode()).hexdigest()
        if row["status"]=="completed":
            if row["result_hash"]==digest:return {"status":"reused","task_id":task_id}
            raise InvestigationError("RH_TASK_CONFLICT","different task result was submitted")
        errors=list(Draft202012Validator(json.loads(row["output_schema"])).iter_errors(result))
        if errors: raise InvestigationError("RH_MODEL_RESULT_INVALID","model result failed schema validation")
        self._refs(row,result); self.db.execute("UPDATE model_tasks SET status='completed',result=?,result_hash=? WHERE id=?",(raw,digest,task_id)); self.db.commit()
        return {"status":"accepted","task_id":task_id}
    def advance_investigation(self,run_id):
        self._run(run_id)
        try: self.graph.invoke({"run_id":run_id})
        except InvestigationError as error:
            if error.code != "RH_MODEL_BUDGET": raise
            extracted=self._done(run_id,"evidence_analysis","extract")
            evidence_row=self.db.execute("SELECT payload FROM model_tasks WHERE run_id=? AND role='evidence_analysis' AND task_type='extract'",(run_id,)).fetchone()
            result={"run_id":run_id,"synthetic":True,"outcome":"partial","conclusion":"Model task budget exhausted before the next stage.","verification":None,"findings":extracted[0]["findings"] if extracted else [],"evidence":json.loads(evidence_row["payload"])["evidence"] if evidence_row else [],"artifacts":[],"issues":[{"code":"RH_MODEL_BUDGET","status":"open"}]}
            self.db.execute("UPDATE investigations SET status='partial',stage='budget_exhausted',result=?,updated=? WHERE id=?",(json.dumps(result),time.time(),run_id)); self.db.commit()
        s=self.status(run_id)
        if s["status"] in ("completed","partial"): return {"run_id":run_id,"outcome":s["status"],"stage":"completed"}
        return {"run_id":run_id,"outcome":"waiting","waiting_reason":"model_task","stage":s["stage"]}
    def resume_investigation(self,run_id): return self.advance_investigation(run_id)
    def status(self,run_id=None):
        if run_id is None:return {"runs":[self.status(r["id"]) for r in self.db.execute("SELECT id FROM investigations ORDER BY created DESC")]}
        r=self._run(run_id); return {"run_id":run_id,"status":r["status"],"stage":r["stage"],"waiting_reason":"model_task" if r["status"]=="waiting_model" else None,"budget":json.loads(r["budget"]),"stage_trace":json.loads(r["trace"]),"outcome":r["status"] if r["status"] in ("completed","partial") else "waiting"}
    def get_result(self,run_id):
        r=self._run(run_id)
        if not r["result"]: raise InvestigationError("RH_RESULT_PENDING","investigation has not reached verification")
        return json.loads(r["result"])
    def get_artifacts(self,run_id): return self.get_result(run_id).get("artifacts",[])
    def build_report_data(self,run_id):
        run=self._run(run_id); result=self.get_result(run_id); rjson=json.loads(run["spec"])
        claims=self._done(run_id,"synthesis","synthesize")[0]["claims"]; sections=self._done(run_id,"writing","write")[0]["sections"]
        for claim in claims:
            if not {"claim_id","evidence_refs","quote","document_id","version_id"} <= claim.keys(): raise InvestigationError("RH_REPORT_DATA","claim lacks required evidence binding")
            self._check_claim(claim,result["evidence"])
        if not all({"deliverable_type","language","section_id","title","body","claim_ids"} <= x.keys() for x in sections): raise InvestigationError("RH_REPORT_DATA","writing result lacks report section fields")
        return {"synthetic":True,"report_version":"run-"+run_id,"research_question":rjson["research_question"],"report_targets":rjson.get("report_targets",["technical_report","literature_review"]),"findings":[dict(x, evidence_refs=x["evidence_ids"]) for x in result["findings"]],"evidence":result["evidence"],"claims":[dict(x,verification="verified") for x in claims],"sections":sections,"bibliography":[],"coverage":{"outcome":result["outcome"]},"issues":result.get("issues",[])}
    def export_report(self,run_id,languages=None):
        from .investigation_reporting import export_reports
        data=self.build_report_data(run_id); exported=export_reports(self.root,run_id,data,languages)
        row=self._run(run_id); result=json.loads(row["result"]); result["artifacts"]=exported["artifacts"]
        self.db.execute("UPDATE investigations SET result=?,updated=? WHERE id=?",(json.dumps(result),time.time(),run_id));self.db.commit();return exported

    def _graph(self):
        g=StateGraph(dict)
        for name,fn in (("planning_gate",self._plan),("source_task",self._source),("acquire_normalize",self._acquire),("analysis_task",self._analysis),("verification_gate",self._verify)): g.add_node(name,fn)
        g.add_edge(START,"planning_gate")
        g.add_conditional_edges("planning_gate",self._route,{"source_task":"source_task","end":END}); g.add_conditional_edges("source_task",self._route,{"acquire_normalize":"acquire_normalize","end":END}); g.add_conditional_edges("acquire_normalize",self._route,{"analysis_task":"analysis_task","end":END}); g.add_conditional_edges("analysis_task",self._route,{"verification_gate":"verification_gate","end":END}); g.add_edge("verification_gate",END)
        return g.compile()
    def _route(self,s): return s["next"]
    def _plan(self,s):
        r=self._run(s["run_id"])
        if r["stage"]!="planning":return {"run_id":s["run_id"],"next":"source_task"}
        if self._pending(s["run_id"]):return {"run_id":s["run_id"],"next":"end"}
        plan=self._done(s["run_id"],"planning","plan")[0]["search_plan"]; q=plan["queries"]
        sources=[(item,"paper_search" if item["source"]=="synthetic-paper" else "patent_search") for item in q]
        self._reserve_available(s["run_id"],len(sources))
        runtime=json.loads(r["runtime"])
        for item,role in sources:
            source=item["source"]; query_id=item.get("query_id") or "q-"+hashlib.sha256((source+item["query"]+str(item.get("parent_query_id",""))).encode()).hexdigest()[:12]
            candidates=self._search_pages(s["run_id"],source,query_id,runtime,r)
            visible=[{"document_id":x["document_id"],"title":x.get("title","")} for x in candidates if policy_allows(x,runtime)]
            self._task(s["run_id"],role,"screen",{"input_refs":["task:planning",*item.get("input_refs",[])],"query":item["query"],"query_id":query_id,"parent_query_id":item.get("parent_query_id"),"candidates":visible})
        self._set(s["run_id"],stage="source",status="waiting_model"); self._trace(s["run_id"],"planning_gate","planned"); return {"run_id":s["run_id"],"next":"end"}
    def _source(self,s):
        r=self._run(s["run_id"])
        if r["stage"]=="planning" or self._pending(s["run_id"]): return {"run_id":s["run_id"],"next":"end"}
        if r["stage"]!="source":return {"run_id":s["run_id"],"next":"acquire_normalize"}
        self._set(s["run_id"],stage="acquire_normalize",status="running"); self._trace(s["run_id"],"source_task","screened"); return {"run_id":s["run_id"],"next":"acquire_normalize"}
    def _acquire(self,s):
        r=self._run(s["run_id"])
        if r["stage"]!="acquire_normalize":return {"run_id":s["run_id"],"next":"analysis_task"}
        selected={x["document_id"] for task in self._done(s["run_id"],None,"screen") for x in task["candidates"] if x["relevance"]!="irrelevant"}; evidence=[]
        runtime=json.loads(r["runtime"])
        for doc in self._sources(r):
            if doc.get("document_id") not in selected: continue
            if not policy_allows(doc,runtime):
                self._trace(s["run_id"],"acquire_normalize","blocked",{"waiting_reason":{"code":"RH_POLICY_BLOCKED","scope":"model_payload","detail":"restricted"}}); continue
            try: evidence.extend(normalize(doc))
            except SourceError as error: self._trace(s["run_id"],"acquire_normalize","source_failure",{"code":error.code})
        self._reserve_available(s["run_id"],2)
        self._task(s["run_id"],"evidence_analysis","extract",{"input_refs":["stage:acquire_normalize"],"evidence":evidence}); self._task(s["run_id"],"business_judgment","judge",{"input_refs":["stage:acquire_normalize"],"documents":[{"document_id":e["document_id"],"evidence_id":e["evidence_id"]} for e in evidence]})
        self._set(s["run_id"],stage="analysis",status="waiting_model");self._trace(s["run_id"],"acquire_normalize","normalized",{"evidence_count":len(evidence)});return {"run_id":s["run_id"],"next":"end"}
    def _analysis(self,s):
        r=self._run(s["run_id"])
        if r["stage"]=="acquire_normalize" or self._pending(s["run_id"]):return {"run_id":s["run_id"],"next":"end"}
        if r["stage"]!="analysis":return {"run_id":s["run_id"],"next":"verification_gate"}
        findings=self._done(s["run_id"],"evidence_analysis","extract")[0]["findings"]; self._task(s["run_id"],"synthesis","synthesize",{"input_refs":["task:evidence_analysis"],"findings":findings});self._set(s["run_id"],stage="verification",status="waiting_model");self._trace(s["run_id"],"analysis_task","analyzed",{"finding_count":len(findings)});return {"run_id":s["run_id"],"next":"end"}
    def _verify(self,s):
        r=self._run(s["run_id"])
        if r["stage"]!="verification" or self._pending(s["run_id"]):return {"run_id":s["run_id"],"next":"end"}
        if not self._done(s["run_id"],"writing","write"):
            self._task(s["run_id"],"writing","write",{"input_refs":["task:synthesis"],"claims":self._done(s["run_id"],"synthesis","synthesize")[0]["claims"]});return {"run_id":s["run_id"],"next":"end"}
        if not self._done(s["run_id"],"verification","verify"):
            self._task(s["run_id"],"verification","verify",{"input_refs":["task:writing"],"sections":self._done(s["run_id"],"writing","write")[0]["sections"]});return {"run_id":s["run_id"],"next":"end"}
        v=self._done(s["run_id"],"verification","verify")[0]["verification"]; outcome="completed" if v["status"]=="supported" else "partial"; evidence=json.loads(self.db.execute("SELECT payload FROM model_tasks WHERE run_id=? AND role='evidence_analysis' AND task_type='extract'",(s["run_id"],)).fetchone()["payload"])["evidence"]; result={"run_id":s["run_id"],"synthetic":True,"outcome":outcome,"conclusion":v["conclusion"],"verification":v,"findings":self._done(s["run_id"],"evidence_analysis","extract")[0]["findings"],"evidence":evidence,"artifacts":[]}
        self.db.execute("UPDATE investigations SET stage='completed',status=?,result=?,updated=? WHERE id=?",(outcome,json.dumps(result),time.time(),s["run_id"]));self.db.commit();self._trace(s["run_id"],"verification_gate",v["status"]);return {"run_id":s["run_id"],"next":"end"}

    def _task(self,run,role,typ,payload):
        b=json.loads(self._run(run)["budget"])
        if b["reserved_tasks"]>=b["max_tasks"]:raise InvestigationError("RH_MODEL_BUDGET","model task budget exhausted")
        p={"input_refs":payload.get("input_refs",[]),"allowed_operations":["submit_structured_result"],**payload}; self.db.execute("INSERT INTO model_tasks VALUES (?,?,?,?,?,?,?,?,?,?,?)",("task-"+uuid.uuid4().hex[:12],run,1,role,typ,json.dumps(p),json.dumps(TASK_SCHEMAS[role]),"pending",None,None,time.time()));b["reserved_tasks"]+=1;self.db.execute("UPDATE investigations SET budget=?,updated=? WHERE id=?",(json.dumps(b),time.time(),run));self.db.commit()
    def _reserve_available(self,run,count):
        b=json.loads(self._run(run)["budget"])
        if b["reserved_tasks"]+count>b["max_tasks"]:raise InvestigationError("RH_MODEL_BUDGET","model task budget exhausted")
    def _refs(self,row,result):
        p=json.loads(row["payload"]); role=row["role"]
        if role in ("paper_search","patent_search"):
            if not {x["document_id"] for x in result["candidates"]}<={x["document_id"] for x in p["candidates"]}:raise InvestigationError("RH_RESULT_REFERENCE","candidate is not in source task")
        elif role=="evidence_analysis":
            if not all(set(x["evidence_ids"])<={e["evidence_id"] for e in p["evidence"]} for x in result["findings"]):raise InvestigationError("RH_RESULT_REFERENCE","finding cites unknown evidence")
        elif role=="business_judgment":
            if not {x["document_id"] for x in result["judgments"]}<={x["document_id"] for x in p["documents"]}:raise InvestigationError("RH_RESULT_REFERENCE","judgment cites unknown document")
        elif role=="synthesis":
            findings=self._done(row["run_id"],"evidence_analysis","extract")[0]["findings"]
            if any(any(i>=len(findings) for i in x["finding_refs"]) for x in result["claims"]):raise InvestigationError("RH_RESULT_REFERENCE","claim references unknown finding")
        elif role=="verification":
            claims=self._done(row["run_id"],"synthesis","synthesize")[0]["claims"]
            if any(i>=len(claims) for i in result["verification"]["supported_claim_refs"]):raise InvestigationError("RH_RESULT_REFERENCE","verification references unknown claim")
    def _check_claim(self,claim,evidence):
        lookup={x["evidence_id"]:x for x in evidence}
        for ref in claim["evidence_refs"]:
            item=lookup.get(ref)
            if not item or claim["document_id"]!=item["document_id"] or claim["version_id"]!=item["version_id"] or not item.get("locator") or claim["quote"] not in item["text"]:raise InvestigationError("RH_RESULT_REFERENCE","claim quotation does not bind to normalized evidence")
    def _done(self,run,role,typ):
        sql="SELECT result FROM model_tasks WHERE run_id=? AND task_type=? AND status='completed'";args=[run,typ]
        if role:sql+=" AND role=?";args.append(role)
        return [json.loads(x["result"]) for x in self.db.execute(sql,args)]
    def _pending(self,run):return self.db.execute("SELECT 1 FROM model_tasks WHERE run_id=? AND status='pending'",(run,)).fetchone() is not None
    def _run(self,run):
        x=self.db.execute("SELECT * FROM investigations WHERE id=?",(run,)).fetchone()
        if not x:raise NotFoundError()
        return x
    def _sources(self,run):return json.loads(run["scenario"]).get("sources",[])
    def _search_pages(self,run_id,source,query_id,runtime,run):
        transport=SyntheticTransport(json.loads(run["scenario"]).get("transport_pages",[])); cursor=None; found=[]
        while True:
            done=self.db.execute("SELECT result FROM source_attempts WHERE run_id=? AND query_id=? AND cursor IS ? AND status='success' ORDER BY attempt DESC LIMIT 1",(run_id,query_id,cursor)).fetchone()
            if done: page=json.loads(done["result"])
            else:
                budget=json.loads(self._run(run_id)["budget"])
                if budget["reserved_source_calls"]>=budget["max_source_calls"]: raise InvestigationError("RH_SOURCE_BUDGET","source call budget exhausted")
                attempt=self.db.execute("SELECT COUNT(*) FROM source_attempts WHERE run_id=? AND query_id=? AND cursor IS ?",(run_id,query_id,cursor)).fetchone()[0]+1
                budget["reserved_source_calls"]+=1;self.db.execute("UPDATE investigations SET budget=? WHERE id=?",(json.dumps(budget),run_id));self.db.commit()
                try: page=transport.search(source,query_id,cursor)
                except SourceError as error:
                    self.db.execute("INSERT INTO source_attempts VALUES (?,?,?,?,?,?)",(run_id,query_id,cursor,attempt,error.code,"{}"));self.db.commit()
                    if error.code in {"RH_SOURCE_RATE_LIMIT","RH_SOURCE_TIMEOUT","RH_SOURCE_SERVER_ERROR"} and attempt<3: continue
                    self._trace(run_id,"source_task","source_partial",{"query_id":query_id,"code":error.code}); return found
                self.db.execute("INSERT INTO source_attempts VALUES (?,?,?,?,?,?)",(run_id,query_id,cursor,attempt,"success",json.dumps(page)));self.db.commit()
            found.extend(page["candidates"]); cursor=page["next_cursor"]
            if cursor is None:return found
    def _set(self,run,**kw):
        kw["updated"]=time.time();self.db.execute("UPDATE investigations SET "+",".join(f"{k}=?" for k in kw)+" WHERE id=?",(*kw.values(),run));self.db.commit()
    def _trace(self,run,node,event,extra=None):
        r=self._run(run);x=json.loads(r["trace"]);x.append({"node":node,"event":event,**(extra or {})});self.db.execute("UPDATE investigations SET trace=?,updated=? WHERE id=?",(json.dumps(x),time.time(),run));self.db.commit()
