"""Offline, resumable D19-P1 investigation orchestration."""
from __future__ import annotations

import hashlib, json, sqlite3, time, uuid
from pathlib import Path
from jsonschema import Draft202012Validator
from langgraph.graph import StateGraph, START, END
from .errors import HarnessError, NotFoundError, ValidationError
from .investigation_sources import SourceError, SyntheticTransport, baseline_snapshot, normalize, policy_allows, canonical_identity
from .investigation_contracts import get_task_schema, validate_spec, validate_runtime
from .investigation_monitoring import MonitorStore
from .investigation_review import ReviewStore
from filelock import FileLock, Timeout

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
        self._lock=FileLock(str(self.root/".investigation.write.lock"))
        self._acquire_lock()
        self.db=sqlite3.connect(self.root/"investigation.sqlite"); self.db.row_factory=sqlite3.Row
        self.db.executescript("""CREATE TABLE IF NOT EXISTS investigations(id TEXT PRIMARY KEY,spec TEXT NOT NULL,runtime TEXT NOT NULL,scenario TEXT NOT NULL,status TEXT NOT NULL,stage TEXT NOT NULL,budget TEXT NOT NULL,created REAL NOT NULL,updated REAL NOT NULL,result TEXT,trace TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS model_tasks(id TEXT PRIMARY KEY,run_id TEXT NOT NULL,task_version INTEGER NOT NULL,role TEXT NOT NULL,task_type TEXT NOT NULL,payload TEXT NOT NULL,output_schema TEXT NOT NULL,status TEXT NOT NULL,result TEXT,result_hash TEXT,created REAL NOT NULL, UNIQUE(run_id,role,task_type,task_version));""")
        self.db.execute("CREATE TABLE IF NOT EXISTS source_attempts(run_id TEXT,query_id TEXT,cursor TEXT,attempt INTEGER,status TEXT,result TEXT,PRIMARY KEY(run_id,query_id,cursor,attempt))")
        self.db.execute("CREATE TABLE IF NOT EXISTS source_queries(run_id TEXT,query_id TEXT,source TEXT,query TEXT,parent_query_id TEXT,input_refs TEXT,status TEXT,reason TEXT,PRIMARY KEY(run_id,query_id))")
        self.db.execute("CREATE TABLE IF NOT EXISTS discovery_evidence(evidence_id TEXT PRIMARY KEY,run_id TEXT NOT NULL,document_id TEXT NOT NULL,version_id TEXT NOT NULL,payload TEXT NOT NULL,visibility TEXT NOT NULL,company_id TEXT)")
        self.db.execute("CREATE TABLE IF NOT EXISTS frozen_reports(run_id TEXT PRIMARY KEY,payload TEXT NOT NULL,created REAL NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS monitor_runs(run_id TEXT PRIMARY KEY,monitor_id TEXT NOT NULL,cycle_id TEXT NOT NULL,profile TEXT NOT NULL)")
        self.db.commit(); self.monitors=MonitorStore(self.root); self.reviews=ReviewStore(self.root); self.graph=self._graph()
    def close(self):
        self.db.close()
        self.monitors.close(); self.reviews.close()
        self._lock.release()
    def __enter__(self): return self
    def __exit__(self,*_): self.close()
    def _acquire_lock(self):
        try:
            self._lock.acquire(timeout=0)
        except Timeout as error: raise InvestigationError("RH_WORKSPACE_BUSY","another investigation service owns this workspace") from error
    def doctor(self): return {"ok":True,"mode":"offline","network":"disabled","data_mode":"synthetic","missing":[],"capabilities":{"langgraph":True,"model_api":False,"sources":"synthetic_only"}}
    def validate_plan(self, plan):
        if not isinstance(plan,dict): raise ValidationError("plan must be an object")
        search_plan=plan.get("search_plan",plan if "queries" in plan else None)
        if search_plan is not None:
            queries=search_plan.get("queries") if isinstance(search_plan,dict) else None
            self._validate_queries(queries)
            return {"valid":True,"mode":"offline","queries":len(queries),"sources":sorted({item["source"] for item in queries})}
        validate_spec(plan)
        if not isinstance(plan.get("research_question"),str) or not plan["research_question"].strip(): raise ValidationError()
        if plan.get("status") not in (None,"ready"): raise InvestigationError("RH_PLAN_STATUS","plan must be ready")
        return {"valid":True,"mode":"offline","sources":plan.get("sources",[]),"budget":plan.get("budget",{})}
    def create_investigation(self,spec,runtime,scenario=None):
        validate_spec(spec)
        validate_runtime(runtime)
        if spec.get("status")!="ready" or runtime.get("mode")!="host" or runtime.get("data_mode")!="synthetic": raise InvestigationError("RH_PRECONDITION","ready synthetic host inputs are required")
        scenario=scenario or {}
        if not isinstance(scenario,dict) or not isinstance(scenario.get("sources",[]),list): raise InvestigationError("RH_SCENARIO","scenario.sources must be a list")
        scenario=dict(scenario); scenario["baseline_snapshot"]=baseline_snapshot(scenario.get("references",[]),runtime)
        blocked=[x.get("document_id") for x in scenario.get("references",[]) if not policy_allows(x,runtime)]
        run="inv-"+uuid.uuid4().hex[:12]; now=time.time(); budget=dict(runtime.get("budget",{})); budget.setdefault("max_tasks",8); budget.setdefault("max_source_calls",32); budget["reserved_tasks"]=0; budget["reserved_source_calls"]=0
        self.db.execute("INSERT INTO investigations VALUES (?,?,?,?,?,?,?,?,?,?,?)",(run,json.dumps(spec),json.dumps(runtime),json.dumps(scenario),"running","planning",json.dumps(budget),now,now,None,"[]")); self.db.commit()
        if blocked:
            self._trace(run,"planning_gate","policy_blocked",{"code":"RH_POLICY_BLOCKED","references":blocked})
            self._set(run,status="policy_blocked",stage="policy_blocked")
            return {"run_id":run,"stage":"policy_blocked","status":"policy_blocked"}
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
        if row["role"] == "business_judgment": self._record_monitor_judgments(row,result)
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
        r=self._run(run_id); coverage=self._coverage(run_id)
        waiting="model_task" if r["status"]=="waiting_model" else ("policy_blocked" if r["status"]=="policy_blocked" else None)
        return {"run_id":run_id,"status":r["status"],"stage":r["stage"],"waiting_reason":waiting,"budget":json.loads(r["budget"]),"coverage":coverage,"stage_trace":json.loads(r["trace"]),"outcome":r["status"] if r["status"] in ("completed","partial","policy_blocked") else "waiting"}
    def get_result(self,run_id):
        r=self._run(run_id)
        if not r["result"]: raise InvestigationError("RH_RESULT_PENDING","investigation has not reached verification")
        return json.loads(r["result"])
    def get_artifacts(self,run_id): return self.get_result(run_id).get("artifacts",[])
    def get_discovery_evidence(self,evidence_id,runtime=None):
        row=self.db.execute("SELECT payload,visibility,company_id FROM discovery_evidence WHERE evidence_id=?",(evidence_id,)).fetchone()
        if not row: raise NotFoundError()
        item=json.loads(row["payload"])
        if row["visibility"] != "public" and not runtime:
            raise InvestigationError("RH_POLICY_BLOCKED","confidential discovery evidence requires an authorized runtime")
        if row["visibility"] != "public" and not policy_allows({"visibility":row["visibility"],"company_id":row["company_id"]},runtime):
            raise InvestigationError("RH_POLICY_BLOCKED","discovery evidence is not authorized for this runtime")
        return item
    def build_report_data(self,run_id):
        frozen=self.db.execute("SELECT payload FROM frozen_reports WHERE run_id=?",(run_id,)).fetchone()
        if not frozen: raise InvestigationError("RH_REPORT_DATA","report data has not been frozen")
        return json.loads(frozen["payload"])
    def export_report(self,run_id,languages=None):
        from .investigation_reporting import export_reports
        data=self.build_report_data(run_id); exported=export_reports(self.root,run_id,data,languages)
        row=self._run(run_id); result=json.loads(row["result"]); result["artifacts"]=exported["artifacts"]
        self.db.execute("UPDATE investigations SET result=?,updated=? WHERE id=?",(json.dumps(result),time.time(),run_id));self.db.commit();return exported
    def validate_monitor(self,profile,monitor_spec,runtime):
        validate_runtime(runtime)
        if not isinstance(profile,dict) or not profile.get("company_id") or not profile.get("rule_version") or not isinstance(monitor_spec,dict) or not monitor_spec.get("name"): raise ValidationError("monitor profile, rule_version, and name are required")
        if profile.get("visibility","public") != "public" and not policy_allows(profile,runtime): raise InvestigationError("RH_POLICY_BLOCKED","monitor profile is not authorized for this runtime")
        return {"valid":True,"mode":"offline","scheduler":"disabled"}
    def create_monitor(self,profile,monitor_spec,runtime,scenario=None):
        self.validate_monitor(profile,monitor_spec,runtime)
        state=self.monitors.create(profile,monitor_spec,runtime)
        return {"monitor_id":state["monitor_id"],"status":state["status"],"scheduler":"disabled"}
    def update_monitor_profile(self,monitor_id,profile):
        return self.monitors.update_profile(monitor_id,profile)
    def monitor_status(self,monitor_id=None): return self.monitors.status(monitor_id)
    def pause_monitor(self,monitor_id): return self.monitors.pause(monitor_id)
    def resume_monitor(self,monitor_id): return self.monitors.resume(monitor_id)
    def review_list(self,monitor_id=None): return self.reviews.review_list(monitor_id)
    def review_decide(self,issue_id,decision,note=""): return self.reviews.review_decide(issue_id,decision,note)
    def run_monitor_once(self,monitor_id,scenario=None):
        scenario=scenario or {}
        required=("cycle_key","window_start","window_end")
        if not isinstance(scenario,dict) or any(not scenario.get(key) for key in required): raise InvestigationError("RH_MONITOR_SCENARIO","cycle_key and explicit window are required")
        cycle=self.monitors.begin_cycle(monitor_id,scenario["cycle_key"],scenario["window_start"],scenario["window_end"])
        if cycle["reused"]:
            state=self.monitors.status(monitor_id); prior=next(item for item in state["cycles"] if item["cycle_id"]==cycle["cycle_id"])
            if prior["run_id"]: return {"monitor_id":monitor_id,"run_id":prior["run_id"],"reused":True}
        config=self.monitors.get_configuration(monitor_id)
        docs=list(scenario.get("sources",[])); failed=any(page.get("error") for page in scenario.get("transport_pages",[]) if isinstance(page,dict))
        stored=[]
        for doc in docs:
            item=dict(doc); item["content_sha256"]=hashlib.sha256((str(item.get("text",""))+str(item.get("base64_bytes",""))).encode()).hexdigest(); stored.append(item)
        self.monitors.record_collection(cycle["cycle_id"],stored,not failed,{"source_status":"partial" if failed else "complete","cycle_key":scenario["cycle_key"]})
        spec={"status":"ready","project_id":"monitor-"+monitor_id,"revision":config["profile_revision"],"research_question":config["profile"].get("scope",monitor_id),"report_targets":[{"deliverable_type":"patent_monitor_digest","languages":config["monitor_spec"].get("report_languages",[])}],"references":scenario.get("references",[])}
        run=self.create_investigation(spec,config["runtime"],scenario)["run_id"]
        self.monitors.bind_run(cycle["cycle_id"],run); self.db.execute("INSERT INTO monitor_runs VALUES (?,?,?,?)",(run,monitor_id,cycle["cycle_id"],json.dumps(config["profile"]))); self.db.commit(); self.monitors.reserve_tasks(monitor_id,1)
        return {"monitor_id":monitor_id,"run_id":run,"cycle_id":cycle["cycle_id"],"reused":False}

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
        reference_ids={x.get("document_id") for x in json.loads(r["scenario"]).get("references",[])}
        evidence_ids={x.get("evidence_id") for x in json.loads(r["scenario"]).get("baseline_snapshot",[])}
        self._validate_queries(q,reference_ids,evidence_ids)
        runtime=json.loads(r["runtime"])
        # Source screen tasks are all-or-partial as one planning checkpoint.
        self._reserve_available(s["run_id"],len(q))
        any_task=False; partial=False
        for item in q:
            role="paper_search" if item["source"]=="synthetic-paper" else "patent_search"
            source=item["source"]; query_id=item.get("query_id") or "q-"+hashlib.sha256((source+item["query"]+str(item.get("parent_query_id",""))).encode()).hexdigest()[:12]
            self.db.execute("INSERT OR IGNORE INTO source_queries VALUES (?,?,?,?,?,?,?,?)",(s["run_id"],query_id,source,item["query"],item.get("parent_query_id"),json.dumps(item.get("input_refs",[])),"pending",None)); self.db.commit()
            if self._query_is_sensitive(item,r) and not policy_allows({"visibility":"confidential","company_id":runtime.get("data_policy",{}).get("company_id")},runtime,query=True):
                self._set_query(s["run_id"],query_id,"policy_blocked","RH_POLICY_BLOCKED: query egress is not allowed"); partial=True; continue
            candidates, status, reason=self._search_pages(s["run_id"],source,query_id,runtime,r)
            self._set_query(s["run_id"],query_id,status,reason)
            if status != "complete": partial=True
            visible=self._visible_candidates(candidates,runtime,r)
            if not visible:
                partial=True; continue
            try:
                self._task(s["run_id"],role,"screen:"+query_id,{"input_refs":["task:planning",*item.get("input_refs",[])],"query":item["query"],"query_id":query_id,"parent_query_id":item.get("parent_query_id"),"candidates":visible})
                any_task=True
            except InvestigationError as error:
                if error.code != "RH_MODEL_BUDGET": raise
                self._set_query(s["run_id"],query_id,"partial","model budget exhausted"); partial=True
        if not any_task:
            self._finish_source_partial(s["run_id"], "No authorized candidates are available." if not partial else "Source collection is partial.")
            return {"run_id":s["run_id"],"next":"end"}
        self._set(s["run_id"],stage="source",status="waiting_model"); self._trace(s["run_id"],"planning_gate","planned"); return {"run_id":s["run_id"],"next":"end"}
    def _source(self,s):
        r=self._run(s["run_id"])
        if r["stage"]=="planning" or self._pending(s["run_id"]): return {"run_id":s["run_id"],"next":"end"}
        if r["stage"]!="source":return {"run_id":s["run_id"],"next":"acquire_normalize"}
        self._set(s["run_id"],stage="acquire_normalize",status="running"); self._trace(s["run_id"],"source_task","screened"); return {"run_id":s["run_id"],"next":"acquire_normalize"}
    def _acquire(self,s):
        r=self._run(s["run_id"])
        if r["stage"]!="acquire_normalize":return {"run_id":s["run_id"],"next":"analysis_task"}
        selected={x["document_id"] for task in self._screens(s["run_id"]) for x in task["candidates"] if x["relevance"]!="irrelevant"}; evidence=[]; acquisition_issues=[]
        runtime=json.loads(r["runtime"])
        for doc in self._sources(r):
            if doc.get("document_id") not in selected: continue
            if not policy_allows(doc,runtime):
                self._trace(s["run_id"],"acquire_normalize","blocked",{"waiting_reason":{"code":"RH_POLICY_BLOCKED","scope":"model_payload","detail":"restricted"}}); continue
            try: evidence.extend(normalize(doc))
            except SourceError as error:
                issue={"code":error.code,"status":"open","document_id":doc.get("document_id"),"version_id":str(doc.get("version","synthetic-v1")),"message":error.message}
                acquisition_issues.append(issue); self._trace(s["run_id"],"acquire_normalize","source_failure",issue)
        for item in evidence:
            doc=next((x for x in self._sources(r) if x.get("document_id")==item["document_id"]),{})
            self.db.execute("INSERT OR IGNORE INTO discovery_evidence VALUES (?,?,?,?,?,?,?)",(item["evidence_id"],s["run_id"],item["document_id"],item["version_id"],json.dumps(item),doc.get("visibility","public"),doc.get("company_id")))
        self.db.commit()
        baseline=json.loads(r["scenario"]).get("baseline_snapshot",[])
        self._reserve_available(s["run_id"],2)
        monitor=self._monitor_context(s["run_id"])
        payload={"input_refs":["stage:acquire_normalize"],"evidence":evidence,"discovery_evidence":evidence,"baseline_evidence":baseline,"acquisition_issues":acquisition_issues,"report_targets":json.loads(r["spec"]).get("report_targets",[]),**({"monitor":monitor} if monitor else {})}
        self._task(s["run_id"],"evidence_analysis","extract",payload)
        judge_evidence=[item for item in evidence if not monitor or self._monitor_needs_judgment(monitor,item)]
        if judge_evidence:self._task(s["run_id"],"business_judgment","judge",{**payload,"documents":[{"document_id":e["document_id"],"evidence_id":e["evidence_id"]} for e in judge_evidence]})
        self._set(s["run_id"],stage="analysis",status="waiting_model");self._trace(s["run_id"],"acquire_normalize","normalized",{"evidence_count":len(evidence)});return {"run_id":s["run_id"],"next":"end"}
    def _analysis(self,s):
        r=self._run(s["run_id"])
        if r["stage"]=="acquire_normalize" or self._pending(s["run_id"]):return {"run_id":s["run_id"],"next":"end"}
        if r["stage"]!="analysis":return {"run_id":s["run_id"],"next":"verification_gate"}
        findings=self._done(s["run_id"],"evidence_analysis","extract")[0]["findings"]; evidence=json.loads(self.db.execute("SELECT payload FROM model_tasks WHERE run_id=? AND role='evidence_analysis' AND task_type='extract'",(s["run_id"],)).fetchone()["payload"])["evidence"]
        self._task(s["run_id"],"synthesis","synthesize",{"input_refs":["task:evidence_analysis"],"findings":findings,"evidence":evidence,"spec":json.loads(r["spec"]),"report_targets":json.loads(r["spec"]).get("report_targets",[])});self._set(s["run_id"],stage="verification",status="waiting_model");self._trace(s["run_id"],"analysis_task","analyzed",{"finding_count":len(findings)});return {"run_id":s["run_id"],"next":"end"}
    def _verify(self,s):
        r=self._run(s["run_id"])
        if r["stage"]!="verification" or self._pending(s["run_id"]):return {"run_id":s["run_id"],"next":"end"}
        synthesis=self._done(s["run_id"],"synthesis","synthesize")[0]["claims"]
        extract_payload=json.loads(self.db.execute("SELECT payload FROM model_tasks WHERE run_id=? AND role='evidence_analysis' AND task_type='extract'",(s["run_id"],)).fetchone()["payload"])
        if not self._done(s["run_id"],"writing","write"):
            self._task(s["run_id"],"writing","write",{"input_refs":["task:synthesis"],"claims":synthesis,"findings":self._done(s["run_id"],"evidence_analysis","extract")[0]["findings"],"evidence":extract_payload["evidence"],"spec":json.loads(r["spec"]),"report_targets":json.loads(r["spec"]).get("report_targets",[])});return {"run_id":s["run_id"],"next":"end"}
        if not self._done(s["run_id"],"verification","verify"):
            self._task(s["run_id"],"verification","verify",{"input_refs":["task:writing"],"sections":self._done(s["run_id"],"writing","write")[0]["sections"],"claims":synthesis,"findings":self._done(s["run_id"],"evidence_analysis","extract")[0]["findings"],"evidence":extract_payload["evidence"],"spec":json.loads(r["spec"])});return {"run_id":s["run_id"],"next":"end"}
        v=self._done(s["run_id"],"verification","verify")[0]["verification"]; coverage=self._coverage(s["run_id"]); findings=self._done(s["run_id"],"evidence_analysis","extract")[0]["findings"]; evidence=extract_payload["evidence"]
        from .investigation_report_data import build_report_data
        bibliography=[self._bibliography(doc) for doc in self._sources(r) if any(x["document_id"]==doc.get("document_id") for x in evidence)]
        acquisition_issues=extract_payload.get("acquisition_issues",[])
        try:
            report=build_report_data(s["run_id"],json.loads(r["spec"]),evidence,findings,synthesis,self._done(s["run_id"],"writing","write")[0]["sections"],v,bibliography,coverage,acquisition_issues,"run-"+s["run_id"]); report["baseline_evidence"]=extract_payload.get("baseline_evidence",[])
        except Exception as error:
            report={"synthetic":True,"run_id":s["run_id"],"report_version":"run-"+s["run_id"],"research_question":json.loads(r["spec"])["research_question"],"report_targets":json.loads(r["spec"]).get("report_targets",[]),"findings":findings,"evidence":evidence,"claims":[],"sections":[],"bibliography":bibliography,"coverage":coverage,"issues":[*acquisition_issues,{"code":"RH_REPORT_DATA","message":str(error)}]}
        self.db.execute("INSERT OR REPLACE INTO frozen_reports VALUES (?,?,?)",(s["run_id"],json.dumps(report),time.time())); self.db.commit()
        legacy=any("claim_id" not in claim for claim in synthesis) or any("body" not in section or "claim_ids" not in section for section in self._done(s["run_id"],"writing","write")[0]["sections"])
        outcome="completed" if v["status"]=="supported" and coverage["complete"] and (legacy or not report.get("issues")) else "partial"; result={"run_id":s["run_id"],"synthetic":True,"outcome":outcome,"conclusion":v["conclusion"],"verification":v,"findings":findings,"evidence":evidence,"baseline_evidence":extract_payload.get("baseline_evidence",[]),"artifacts":[],"coverage":coverage,"issues":report.get("issues",[])}
        self.db.execute("UPDATE investigations SET stage='completed',status=?,result=?,updated=? WHERE id=?",(outcome,json.dumps(result),time.time(),s["run_id"]));self.db.commit();self._trace(s["run_id"],"verification_gate",v["status"]);return {"run_id":s["run_id"],"next":"end"}

    def _task(self,run,role,typ,payload):
        b=json.loads(self._run(run)["budget"])
        if b["reserved_tasks"]>=b["max_tasks"]:raise InvestigationError("RH_MODEL_BUDGET","model task budget exhausted")
        monitor=self._monitor_context(run)
        if monitor:self.monitors.reserve_tasks(monitor["monitor_id"],1)
        p={"input_refs":payload.get("input_refs",[]),"allowed_operations":["submit_structured_result"],**payload}; self.db.execute("INSERT INTO model_tasks VALUES (?,?,?,?,?,?,?,?,?,?,?)",("task-"+uuid.uuid4().hex[:12],run,1,role,typ,json.dumps(p),json.dumps(get_task_schema(role)),"pending",None,None,time.time()));b["reserved_tasks"]+=1;self.db.execute("UPDATE investigations SET budget=?,updated=? WHERE id=?",(json.dumps(b),time.time(),run));self.db.commit()
    def _monitor_context(self,run):
        row=self.db.execute("SELECT monitor_id,cycle_id,profile FROM monitor_runs WHERE run_id=?",(run,)).fetchone()
        return {"monitor_id":row["monitor_id"],"cycle_id":row["cycle_id"],"profile":json.loads(row["profile"])} if row else None
    def _monitor_needs_judgment(self,monitor,evidence):
        state=self.monitors.status(monitor["monitor_id"]); current=monitor["cycle_id"]
        for cycle in state["cycles"]:
            if cycle["cycle_id"] == current or cycle["rule_version"] != monitor["profile"]["rule_version"]: continue
            for document in cycle["documents"]:
                if document["document_id"] == evidence["document_id"] and document["document_version"] == evidence["version_id"]:
                    return any(item["document_id"] == evidence["document_id"] and item["document_version"] == evidence["version_id"] for item in cycle["judgment_backlog"])
        return True
    def _record_monitor_judgments(self,row,result):
        payload=json.loads(row["payload"]); monitor=payload.get("monitor")
        if not monitor:return
        evidence={item["document_id"]:item for item in payload["evidence"]}
        for judgment in result["judgments"]:
            item=evidence[judgment["document_id"]]
            saved=self.reviews.record_judgment(monitor["monitor_id"],monitor["profile"]["company_id"],item["document_id"],item["version_id"],monitor["profile"]["rule_version"],judgment,[item["evidence_id"]])
            self.monitors.mark_judged(monitor["cycle_id"],item["document_id"],item["version_id"],saved["issue_id"])
    def _validate_queries(self,queries,reference_ids=None,evidence_ids=None):
        errors=list(Draft202012Validator(get_task_schema("planning")).iter_errors({"search_plan":{"queries":queries}}))
        if errors: raise InvestigationError("RH_QUERY_IDENTITY","query plan failed schema validation")
        ids=[]
        for item in queries:
            if item["source"] not in {"synthetic-paper","synthetic-patent"}: raise InvestigationError("RH_QUERY_IDENTITY","query source is not available in offline mode")
            ids.append(item["query_id"])
        if len(ids)!=len(set(ids)): raise InvestigationError("RH_QUERY_IDENTITY","query_id must be unique within a run")
        known=set(ids)
        for item in queries:
            parent=item["parent_query_id"]
            if parent is not None and (parent not in known or parent==item["query_id"]): raise InvestigationError("RH_QUERY_REFERENCE","parent_query_id must name a different actual query")
            for ref in item["input_refs"]:
                if not isinstance(ref,str): raise InvestigationError("RH_QUERY_REFERENCE","input_refs must be strings")
                if reference_ids is None or evidence_ids is None: continue
                if ref.startswith("baseline:") and ref[9:] not in reference_ids: raise InvestigationError("RH_QUERY_REFERENCE","input_refs names an unknown baseline")
                if ref.startswith("query:") and ref[6:] not in known: raise InvestigationError("RH_QUERY_REFERENCE","input_refs names an unknown query")
                if not (ref in evidence_ids or ref.startswith("baseline:") or ref.startswith("query:")): raise InvestigationError("RH_QUERY_REFERENCE","input_refs must name actual baseline evidence or query")
    def _reserve_available(self,run,count):
        b=json.loads(self._run(run)["budget"])
        if b["reserved_tasks"]+count>b["max_tasks"]:raise InvestigationError("RH_MODEL_BUDGET","model task budget exhausted")
    def _refs(self,row,result):
        p=json.loads(row["payload"]); role=row["role"]
        if role == "planning":
            queries=result["search_plan"]["queries"]
            run=self._run(row["run_id"]); references=json.loads(run["scenario"]).get("references",[]); docs={x.get("document_id") for x in references}; evidence={x.get("evidence_id") for x in json.loads(run["scenario"]).get("baseline_snapshot",[])}
            self._validate_queries(queries,docs,evidence)
        elif role in ("paper_search","patent_search"):
            if not {x["document_id"] for x in result["candidates"]}<={x["document_id"] for x in p["candidates"]}:raise InvestigationError("RH_RESULT_REFERENCE","candidate is not in source task")
        elif role=="evidence_analysis":
            if not all(set(x["evidence_ids"])<={e["evidence_id"] for e in p["evidence"]} for x in result["findings"]):raise InvestigationError("RH_RESULT_REFERENCE","finding cites unknown evidence")
        elif role=="business_judgment":
            if not {x["document_id"] for x in result["judgments"]}<={x["document_id"] for x in p["documents"]}:raise InvestigationError("RH_RESULT_REFERENCE","judgment cites unknown document")
        elif role=="synthesis":
            findings=self._done(row["run_id"],"evidence_analysis","extract")[0]["findings"]
            if any(any(i>=len(findings) for i in x["finding_refs"]) for x in result["claims"]):raise InvestigationError("RH_RESULT_REFERENCE","claim references unknown finding")
            evidence=json.loads(self.db.execute("SELECT payload FROM model_tasks WHERE run_id=? AND role='evidence_analysis' AND task_type='extract'",(row["run_id"],)).fetchone()["payload"])["evidence"]
            for claim in result["claims"]: self._check_claim(claim,evidence)
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
        transport=SyntheticTransport(json.loads(run["scenario"]).get("transport_pages",[])); cursor=None; found=[]; seen=set(); max_pages=int(runtime.get("budget",{}).get("max_pages_per_query",32))
        while True:
            if len(seen)>=max_pages or cursor in seen:
                self._trace(run_id,"source_task","source_partial",{"query_id":query_id,"code":"RH_SOURCE_CURSOR_LOOP"}); return found,"partial","cursor loop or page limit"
            done=self.db.execute("SELECT result FROM source_attempts WHERE run_id=? AND query_id=? AND cursor IS ? AND status='success' ORDER BY attempt DESC LIMIT 1",(run_id,query_id,cursor)).fetchone()
            if done: page=json.loads(done["result"])
            else:
                while True:
                    pending=self.db.execute("SELECT 1 FROM source_attempts WHERE run_id=? AND query_id=? AND cursor IS ? AND status='pending'",(run_id,query_id,cursor)).fetchone()
                    if pending:
                        self._trace(run_id,"source_task","source_partial",{"query_id":query_id,"code":"RH_SOURCE_UNCERTAIN"}); return found,"partial","uncertain prior source call"
                    budget=json.loads(self._run(run_id)["budget"])
                    if budget["reserved_source_calls"]>=budget["max_source_calls"]:
                        self._trace(run_id,"source_task","source_partial",{"query_id":query_id,"code":"RH_SOURCE_BUDGET"}); return found,"partial","source call budget exhausted"
                    attempt=self.db.execute("SELECT COUNT(*) FROM source_attempts WHERE run_id=? AND query_id=? AND cursor IS ?",(run_id,query_id,cursor)).fetchone()[0]+1
                    budget["reserved_source_calls"]+=1; self.db.execute("BEGIN IMMEDIATE")
                    self.db.execute("UPDATE investigations SET budget=?,updated=? WHERE id=?",(json.dumps(budget),time.time(),run_id))
                    self.db.execute("INSERT INTO source_attempts VALUES (?,?,?,?,?,?)",(run_id,query_id,cursor,attempt,"pending","{}")); self.db.commit()
                    try: page=transport.search(source,query_id,cursor,attempt=attempt)
                    except SourceError as error:
                        self.db.execute("UPDATE source_attempts SET status=? WHERE run_id=? AND query_id=? AND cursor IS ? AND attempt=?",(error.code,run_id,query_id,cursor,attempt));self.db.commit()
                        if error.code in {"RH_SOURCE_RATE_LIMIT","RH_SOURCE_TIMEOUT","RH_SOURCE_SERVER_ERROR"} and attempt<3: continue
                        self._trace(run_id,"source_task","source_partial",{"query_id":query_id,"code":error.code}); return found,"partial",error.code
                    self.db.execute("UPDATE source_attempts SET status='success',result=? WHERE run_id=? AND query_id=? AND cursor IS ? AND attempt=?",(json.dumps(page),run_id,query_id,cursor,attempt));self.db.commit(); break
            seen.add(cursor)
            found.extend(page["candidates"]); cursor=page["next_cursor"]
            if cursor is None:return found,"complete",None

    def _screens(self,run):
        return [json.loads(x["result"]) for x in self.db.execute("SELECT result FROM model_tasks WHERE run_id=? AND task_type LIKE 'screen:%' AND status='completed'",(run,))]

    def _set_query(self,run,query_id,status,reason):
        self.db.execute("UPDATE source_queries SET status=?,reason=? WHERE run_id=? AND query_id=?",(status,reason,run,query_id)); self.db.commit()

    def _query_is_sensitive(self,item,run):
        refs=set(item.get("input_refs",[])); baseline={"baseline:"+x["document_id"] for x in json.loads(run["scenario"]).get("references",[]) if x.get("visibility")=="confidential"}
        return bool(refs & baseline) or bool(json.loads(run["scenario"]).get("baseline_snapshot")) and any(x.get("visibility")=="confidential" for x in json.loads(run["scenario"]).get("references",[]))

    def _visible_candidates(self,candidates,runtime,run):
        records={x.get("document_id"):x for x in self._sources(run)}; unique={}; out=[]
        for candidate in candidates:
            if not isinstance(candidate,dict) or not isinstance(candidate.get("document_id"),str) or not candidate["document_id"]:
                self._trace(run["id"],"source_task","source_partial",{"code":"RH_SOURCE_INVALID_RESPONSE"}); continue
            record=records.get(candidate.get("document_id"),candidate)
            if not policy_allows(record,runtime): continue
            key=canonical_identity(dict(record,**candidate))
            if key in unique: continue
            unique[key]=candidate; out.append({"document_id":candidate["document_id"],"title":candidate.get("title","")})
        return out

    def _bibliography(self,document):
        """Project source metadata without inventing missing citation fields."""
        item={"id":document.get("document_id"),"citation_key":"ref"+hashlib.sha256(str(document.get("document_id")).encode()).hexdigest()[:12],"title":document.get("title") or document.get("document_id"),"doi":document.get("doi"),"year":document.get("year"),"type":"misc"}
        if document.get("authors"): item["author"]=" and ".join(str(x) for x in document["authors"])
        if document.get("publication_number"): item["note"]="publication "+str(document["publication_number"])
        return {key:value for key,value in item.items() if value not in (None,"")}

    def _coverage(self,run):
        queries=[dict(x) for x in self.db.execute("SELECT query_id,source,query,parent_query_id,input_refs,status,reason FROM source_queries WHERE run_id=? ORDER BY rowid",(run,))]
        for item in queries:
            item["input_refs"]=json.loads(item["input_refs"])
            if item["status"] == "policy_blocked":
                item.pop("query",None); item["input_refs"]=[]
        attempts=[dict(x) for x in self.db.execute("SELECT query_id,cursor,attempt,status FROM source_attempts WHERE run_id=? ORDER BY query_id,attempt",(run,))]
        return {"queries":queries,"attempts":attempts,"complete":bool(queries) and all(x["status"]=="complete" for x in queries)}

    def _finish_source_partial(self,run,message):
        result={"run_id":run,"synthetic":True,"outcome":"partial","conclusion":message,"verification":None,"findings":[],"evidence":[],"artifacts":[],"issues":[{"code":"RH_SOURCE_PARTIAL","status":"open"}],"coverage":self._coverage(run)}
        self.db.execute("UPDATE investigations SET status='partial',stage='completed',result=?,updated=? WHERE id=?",(json.dumps(result),time.time(),run));self.db.commit()
    def _set(self,run,**kw):
        kw["updated"]=time.time();self.db.execute("UPDATE investigations SET "+",".join(f"{k}=?" for k in kw)+" WHERE id=?",(*kw.values(),run));self.db.commit()
    def _trace(self,run,node,event,extra=None):
        r=self._run(run);x=json.loads(r["trace"]);x.append({"node":node,"event":event,**(extra or {})});self.db.execute("UPDATE investigations SET trace=?,updated=? WHERE id=?",(json.dumps(x),time.time(),run));self.db.commit()
