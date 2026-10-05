"""Offline, resumable D19-P1 investigation orchestration."""
from __future__ import annotations

import base64, hashlib, json, os, re, sqlite3, time, uuid
import requests
from xml.etree import ElementTree
from pathlib import Path
from urllib.parse import urlsplit
from jsonschema import Draft202012Validator
from langgraph.graph import StateGraph, START, END
from .errors import HarnessError, NotFoundError, ValidationError
from .investigation_sources import SourceError, SyntheticTransport, OpenAlexTransport, baseline_snapshot, normalize, policy_allows, canonical_identity
from . import literature
from .epo import EpoClient, parse_section, parse_family, parse_availability
from .rag import RagLibrary, RagError
from .investigation_contracts import get_task_schema, validate_spec, validate_runtime
from .investigation_monitoring import MonitorStore
from .investigation_review import ReviewStore
from .patent_source_gateway import PatentSourceGateway
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
 "planning": schema("search_plan", {"type":"object","required":["queries"],"additionalProperties":False,"properties":{"queries":{"type":"array","minItems":1,"items":{"type":"object","required":["source","query"],"additionalProperties":False,"properties":{"source":{"enum":["synthetic-paper","synthetic-patent","openalex"]},"query":{"type":"string","minLength":1}}}}}}),
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
TASK_SCHEMAS["synthesis"]["properties"]["claims"]["items"]["properties"].update({"claim_id":{"type":"string"},"evidence_refs":{"type":"array","items":{"type":"string"}},"quote":{"type":"string"},"document_id":{"type":"string"},"version_id":{"type":"string"},"parse_revision_id":{"type":"string"}})
TASK_SCHEMAS["writing"]["properties"]["sections"]["items"]["properties"].update({"deliverable_type":{"enum":["technical_report","literature_review","patent_monitor_digest"]},"language":{"type":"string"},"section_id":{"type":"string"},"body":{"type":"string"},"claim_ids":{"type":"array","items":{"type":"string"}},"section_kind":{"enum":["fact","explanation","method"]},"block_kind":{"enum":["fact","explanation","method"]}})
TASK_SCHEMAS["planning"]["properties"]["search_plan"]["properties"]["queries"]["items"]["properties"].update({"query_id":{"type":"string"},"parent_query_id":{"type":["string","null"]},"input_refs":{"type":"array","items":{"type":"string"}}})

class InvestigationService:
    def __init__(self, workspace, *, source_request_callback=None):
        self.root=Path(workspace); self.root.mkdir(parents=True, exist_ok=True)
        self._lock=FileLock(str(self.root/".investigation.write.lock"))
        self._acquire_lock()
        # The JSONL supervisor executes the bounded core RPC callback on a
        # dedicated thread so its deadline can be enforced. SQLite remains
        # serialized by this service/workspace boundary, while allowing that
        # callback to use the same connection.
        self.db=sqlite3.connect(self.root/"investigation.sqlite",check_same_thread=False); self.db.row_factory=sqlite3.Row
        self.db.executescript("""CREATE TABLE IF NOT EXISTS investigations(id TEXT PRIMARY KEY,spec TEXT NOT NULL,runtime TEXT NOT NULL,scenario TEXT NOT NULL,status TEXT NOT NULL,stage TEXT NOT NULL,budget TEXT NOT NULL,created REAL NOT NULL,updated REAL NOT NULL,result TEXT,trace TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS model_tasks(id TEXT PRIMARY KEY,run_id TEXT NOT NULL,task_version INTEGER NOT NULL,role TEXT NOT NULL,task_type TEXT NOT NULL,payload TEXT NOT NULL,output_schema TEXT NOT NULL,status TEXT NOT NULL,result TEXT,result_hash TEXT,created REAL NOT NULL, UNIQUE(run_id,role,task_type,task_version));""")
        self.db.execute("CREATE TABLE IF NOT EXISTS source_attempts(run_id TEXT,query_id TEXT,cursor TEXT,attempt INTEGER,status TEXT,result TEXT,PRIMARY KEY(run_id,query_id,cursor,attempt))")
        self.db.execute("CREATE TABLE IF NOT EXISTS source_queries(run_id TEXT,query_id TEXT,source TEXT,query TEXT,parent_query_id TEXT,input_refs TEXT,status TEXT,reason TEXT,PRIMARY KEY(run_id,query_id))")
        self.db.execute("CREATE TABLE IF NOT EXISTS discovery_evidence(evidence_id TEXT PRIMARY KEY,run_id TEXT NOT NULL,document_id TEXT NOT NULL,version_id TEXT NOT NULL,payload TEXT NOT NULL,visibility TEXT NOT NULL,company_id TEXT)")
        self.db.execute("CREATE TABLE IF NOT EXISTS discovery_documents(run_id TEXT NOT NULL,document_id TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(run_id,document_id))")
        self.db.execute("CREATE TABLE IF NOT EXISTS attached_discovery_evidence(run_id TEXT PRIMARY KEY,payload TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS frozen_reports(run_id TEXT PRIMARY KEY,payload TEXT NOT NULL,created REAL NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS epo_query_details(run_id TEXT,query_id TEXT,payload TEXT NOT NULL,PRIMARY KEY(run_id,query_id))")
        self.db.execute("CREATE TABLE IF NOT EXISTS source_query_details(run_id TEXT,query_id TEXT,payload TEXT NOT NULL,PRIMARY KEY(run_id,query_id))")
        self.db.execute("CREATE TABLE IF NOT EXISTS model_api_calls(id TEXT PRIMARY KEY,run_id TEXT NOT NULL,task_id TEXT NOT NULL,task_version INTEGER NOT NULL,status TEXT NOT NULL,usage TEXT,created REAL NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS model_call_events(id INTEGER PRIMARY KEY AUTOINCREMENT,call_id TEXT NOT NULL,event TEXT NOT NULL,details TEXT,created REAL NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS model_call_receipts(call_id TEXT PRIMARY KEY,context_path TEXT NOT NULL,context_hash TEXT NOT NULL,response_path TEXT,response_hash TEXT,logical_hash TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS engine_task_leases(id TEXT PRIMARY KEY,run_id TEXT NOT NULL,task_id TEXT NOT NULL,task_version INTEGER NOT NULL,status TEXT NOT NULL,created REAL NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS engine_model_calls(call_id TEXT PRIMARY KEY,lease_id TEXT NOT NULL,request_id TEXT NOT NULL,kind TEXT NOT NULL,purpose TEXT NOT NULL,UNIQUE(lease_id,request_id))")
        self.db.execute("CREATE TABLE IF NOT EXISTS engine_receipts(id TEXT PRIMARY KEY,run_id TEXT NOT NULL,task_id TEXT NOT NULL,task_version INTEGER NOT NULL,lease_id TEXT NOT NULL,path TEXT NOT NULL,sha256 TEXT NOT NULL,created REAL NOT NULL,UNIQUE(lease_id))")
        self.db.execute("CREATE TABLE IF NOT EXISTS monitor_runs(run_id TEXT PRIMARY KEY,monitor_id TEXT NOT NULL,cycle_id TEXT NOT NULL,profile TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS monitor_cycle_facts(monitor_id TEXT NOT NULL,cycle_key TEXT NOT NULL,fingerprint TEXT NOT NULL,PRIMARY KEY(monitor_id,cycle_key))")
        self.db.execute("CREATE TABLE IF NOT EXISTS monitor_defaults(monitor_id TEXT PRIMARY KEY,scenario TEXT NOT NULL)")
        self.db.commit(); self._epo_clients={}; self._source_request_callback=source_request_callback; self.monitors=MonitorStore(self.root); self.reviews=ReviewStore(self.root); self.graph=self._graph()
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
    def doctor(self):
        present=bool(os.environ.get("OPENALEX_API_KEY"))
        epo_present=bool(os.environ.get("EPO_CONSUMER_KEY") and os.environ.get("EPO_CONSUMER_SECRET"))
        return {"ok":True,"modes":["host","api"],"network":"opt_in","data_modes":["synthetic","live"],"missing":[],"capabilities":{"langgraph":True,"model_api":{"adapters":["openai","anthropic","deepseek","qwen","kimi","openai_compatible"],"online":"not_checked"},"sources":{"synthetic":True,"openalex":{"available":True,"anonymous":True,"api_key":"present" if present else "missing"},"epo":{"available":True,"credentials":"present" if epo_present else "missing"}}}}
    def diagnose_patent_sources(self,run_id):
        self._run(run_id)
        return PatentSourceGateway(self,self._source_request_callback).diagnose(run_id)
    def execute_patent_source(self,run_id,task_id,task_version,request_id,source,operation,params,*,input_refs):
        """Run one authorized source operation through the shared budgeted gateway."""
        run=self._run(run_id)
        if run["status"] in {"stopped","completed","partial","failed","policy_blocked","cancelled"}:
            raise InvestigationError("RH_PATENT_RUN_TERMINAL","source dispatch requires an active run")
        task=self.db.execute("SELECT task_version,status,payload FROM model_tasks WHERE id=? AND run_id=?",(task_id,run_id)).fetchone()
        if not task or task["status"]!="pending" or task["task_version"]!=task_version:
            raise InvestigationError("RH_TASK_VERSION","source operation requires the current pending task version")
        payload=json.loads(task["payload"])
        if "execute_patent_source" not in payload.get("allowed_operations",[]):
            raise InvestigationError("RH_TASK_OPERATION","task does not authorize patent source operations")
        current_budget=json.loads(run["budget"])
        maximum=current_budget.get("max_source_calls"); used=current_budget.get("reserved_source_calls")
        if type(maximum) is int and type(used) is int and used>=maximum:
            from .patent_sources.contracts import pending
            return pending(source,operation,"budget_denied","RH_PATENT_BUDGET","source call budget is exhausted")
        return PatentSourceGateway(self,self._source_request_callback).execute(
            run_id,task_id,task_version,request_id,source,operation,params,input_refs=input_refs)
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
    def add_epo_query(self,run_id,item):
        """Add one bounded CQL revision to the same live run before acquisition."""
        run=self._run(run_id); runtime=json.loads(run["runtime"])
        if run["stage"]!="source" or self._pending(run_id) or "epo" not in runtime.get("sources",{}):
            raise InvestigationError("RH_QUERY_STAGE","EPO query revisions require an idle live source stage")
        if not isinstance(item,dict) or item.get("source")!="epo":
            raise InvestigationError("RH_QUERY_IDENTITY","EPO query revision is invalid")
        existing=self._saved_queries(run_id)
        if len([x for x in existing if x["source"]=="epo"])>=(2 if "reference_rag_evidence_ids" in json.loads(run["scenario"]) else 3):
            raise InvestigationError("RH_QUERY_BUDGET","P4 query version limit is exhausted")
        if "reference_rag_evidence_ids" in json.loads(run["scenario"]) and (not item.get("parent_query_id") or not item.get("revision_reason")):
            raise InvestigationError("RH_QUERY_REFERENCE","evidence-led revision needs a parent and reason")
        scenario=json.loads(run["scenario"])
        self._validate_queries([*existing,item],{x.get("document_id") for x in scenario.get("references",[])},{x.get("evidence_id") for x in scenario.get("baseline_snapshot",[])},runtime,scenario)
        query_id=item["query_id"]
        self._reserve_available(run_id,1)
        self.db.execute("INSERT INTO source_queries VALUES (?,?,?,?,?,?,?,?)",(run_id,query_id,"epo",item["query"],item.get("parent_query_id"),json.dumps(item.get("input_refs",[])),"pending",None))
        details={key:item.get(key) for key in ("intent","terms_basis","revision_reason","filters") if key in item}
        self.db.execute("INSERT INTO epo_query_details VALUES (?,?,?)",(run_id,query_id,json.dumps(details,ensure_ascii=False))); self.db.commit()
        self._store_query_details(run_id,item)
        if self._query_is_sensitive(item,run) and not policy_allows({"visibility":"confidential","company_id":runtime.get("data_policy",{}).get("company_id")},runtime,query=True):
            self._set_query(run_id,query_id,"policy_blocked","RH_POLICY_BLOCKED: query egress is not allowed")
            return {"query_id":query_id,"status":"policy_blocked","candidate_count":0}
        candidates,status,reason=self._search_epo_pages(run_id,query_id,item["query"],runtime)
        self._set_query(run_id,query_id,status,reason)
        visible=self._visible_candidates(candidates,runtime,self._run(run_id))
        if visible:
            self._task(run_id,"patent_search","screen:"+query_id,{"input_refs":(["query:"+item["parent_query_id"]] if item.get("parent_query_id") else [])+item.get("input_refs",[]),"query":item["query"],"query_id":query_id,"parent_query_id":item.get("parent_query_id"),"candidates":visible})
        return {"query_id":query_id,"status":status,"candidate_count":len(visible),"reason":reason}
    def add_openalex_query(self,run_id,item):
        """Execute a bounded evidence-led OpenAlex revision in the current source stage."""
        run=self._run(run_id); runtime=json.loads(run["runtime"])
        if run["stage"]!="source" or self._pending(run_id) or "openalex" not in runtime.get("sources",{}):
            raise InvestigationError("RH_QUERY_STAGE","OpenAlex query revisions require an idle live source stage")
        if not isinstance(item,dict) or item.get("source")!="openalex" or not item.get("parent_query_id"):
            raise InvestigationError("RH_QUERY_IDENTITY","OpenAlex revision needs a parent query")
        if "reference_rag_evidence_ids" in json.loads(run["scenario"]) and not item.get("revision_reason"):
            raise InvestigationError("RH_QUERY_REFERENCE","evidence-led revision needs a reason")
        existing=self._saved_queries(run_id)
        if len([x for x in existing if x["source"]=="openalex"])>=2:
            raise InvestigationError("RH_QUERY_BUDGET","OpenAlex query version limit is exhausted")
        scenario=json.loads(run["scenario"])
        self._validate_queries([*existing,item],{x.get("document_id") for x in scenario.get("references",[])},{x.get("evidence_id") for x in scenario.get("baseline_snapshot",[])},runtime,scenario)
        self._reserve_available(run_id,1)
        query_id=item["query_id"]
        self.db.execute("INSERT INTO source_queries VALUES (?,?,?,?,?,?,?,?)",(run_id,query_id,"openalex",item["query"],item["parent_query_id"],json.dumps(item["input_refs"]),"pending",None))
        self._store_query_details(run_id,item)
        if self._query_is_sensitive(item,run) and not policy_allows({"visibility":"confidential","company_id":runtime.get("data_policy",{}).get("company_id")},runtime,query=True):
            self._set_query(run_id,query_id,"policy_blocked","RH_POLICY_BLOCKED: query egress is not allowed")
            return {"query_id":query_id,"status":"policy_blocked","candidate_count":0}
        candidates,status,reason=self._search_live_pages(run_id,query_id,item["query"],runtime)
        self._set_query(run_id,query_id,status,reason)
        visible=self._visible_candidates(candidates,runtime,self._run(run_id))
        if visible:
            self._task(run_id,"paper_search","screen:"+query_id,{"input_refs":["query:"+item["parent_query_id"],*item["input_refs"]],"query":item["query"],"query_id":query_id,"parent_query_id":item["parent_query_id"],"candidates":visible})
        return {"query_id":query_id,"status":status,"candidate_count":len(visible),"reason":reason}
    def _saved_queries(self,run_id):
        result=[]
        for row in self.db.execute("SELECT query_id,source,query,parent_query_id,input_refs FROM source_queries WHERE run_id=? ORDER BY rowid",(run_id,)):
            detail=self.db.execute("SELECT payload FROM source_query_details WHERE run_id=? AND query_id=?",(run_id,row["query_id"])).fetchone()
            result.append({"query_id":row["query_id"],"source":row["source"],"query":row["query"],"parent_query_id":row["parent_query_id"],"input_refs":json.loads(row["input_refs"]),**(json.loads(detail["payload"]) if detail else {})})
        return result
    def _store_query_details(self,run_id,item):
        details={key:item[key] for key in ("intent","terms_basis","term_evidence","evidence_gap","revision_reason","filters") if key in item}
        self.db.execute("INSERT OR REPLACE INTO source_query_details VALUES (?,?,?)",(run_id,item["query_id"],json.dumps(details,ensure_ascii=False))); self.db.commit()
    def create_investigation(self,spec,runtime,scenario=None):
        validate_spec(spec)
        validate_runtime(runtime)
        live=runtime.get("data_mode")=="live"
        if spec.get("status")!="ready" or runtime.get("mode") not in {"host","api"} or runtime.get("data_mode") not in {"synthetic","live"}: raise InvestigationError("RH_PRECONDITION","ready investigation inputs are required")
        if runtime.get("mode")=="api":
            config=runtime["model_api"]
            from .provider_profiles import validate_profile
            profile=validate_profile(config)
            if not profile["local"] and not os.environ.get(config["api_key_env"]): raise InvestigationError("RH_MODEL_KEY_MISSING","configured model API credential is missing")
            runtime={**runtime,"model_id":config["model"]}
        if live and runtime.get("allow_network") is not True: raise InvestigationError("RH_PRECONDITION","live source requires explicit network opt-in")
        scenario=scenario or {}
        if not isinstance(scenario,dict) or not isinstance(scenario.get("sources",[]),list): raise InvestigationError("RH_SCENARIO","scenario.sources must be a list")
        if live and (scenario.get("sources") or scenario.get("transport_pages")):
            raise InvestigationError("RH_LIVE_FIXTURE","live runs cannot use synthetic source fixtures")
        scenario=dict(scenario)
        source_limits=scenario.get("source_call_limits",{})
        if not isinstance(source_limits,dict) or any(source not in {"epo","openalex"} or type(limit) is not int or limit<1 for source,limit in source_limits.items()):
            raise InvestigationError("RH_SOURCE_BUDGET","source call limits are invalid")
        explicit_reference_evidence=scenario.get("reference_evidence",[])
        registered_snapshot=scenario.get("registered_reference_snapshot")
        if registered_snapshot is not None:
            if not isinstance(registered_snapshot,dict) or any(not isinstance(registered_snapshot.get(key),str) or not registered_snapshot[key] for key in ("workspace_id","library_id","collection_id")) or not isinstance(registered_snapshot.get("member_document_versions"),list) or not isinstance(registered_snapshot.get("index_snapshot"),dict):
                raise InvestigationError("RH_REFERENCE_SNAPSHOT","registered reference snapshot is invalid")
            if scenario.get("reference_rag_workspace") is not None:
                raise InvestigationError("RH_REFERENCE_SNAPSHOT","registered evidence cannot be mixed with live RAG retrieval")
            frozen_versions={item.get("document_id"):item.get("current_version_id") for item in registered_snapshot["member_document_versions"] if isinstance(item,dict)}
            if len(frozen_versions)!=len(registered_snapshot["member_document_versions"]) or any(not doc or not version for doc,version in frozen_versions.items()):
                raise InvestigationError("RH_REFERENCE_SNAPSHOT","registered document versions are invalid")
            if any("current_parse_revision_id" in item and (not isinstance(item["current_parse_revision_id"],str) or not item["current_parse_revision_id"]) for item in registered_snapshot["member_document_versions"] if isinstance(item,dict)):
                raise InvestigationError("RH_REFERENCE_SNAPSHOT","registered parse revisions are invalid")
            if not isinstance(explicit_reference_evidence,list) or any(not isinstance(item,dict) or item.get("document_id") not in frozen_versions or item.get("version_id")!=frozen_versions[item.get("document_id")] for item in explicit_reference_evidence):
                raise InvestigationError("RH_REFERENCE_SNAPSHOT","reference evidence does not match the frozen library versions")
            frozen_revisions={item.get("document_id"):item.get("current_parse_revision_id") for item in registered_snapshot["member_document_versions"] if isinstance(item,dict) and item.get("current_parse_revision_id")}
            if frozen_revisions and any(item.get("document_id") in frozen_revisions and item.get("parse_revision_id")!=frozen_revisions[item.get("document_id")] for item in explicit_reference_evidence):
                raise InvestigationError("RH_REFERENCE_SNAPSHOT","reference evidence does not match the frozen parse revisions")
        rag_workspace=scenario.get("reference_rag_workspace")
        if rag_workspace is not None:
            if not live or explicit_reference_evidence:
                raise InvestigationError("RH_REFERENCE_EVIDENCE","read-only RAG planning cannot mix with supplied reference evidence")
            top_k=scenario.get("reference_rag_top_k",8)
            if type(top_k) is not int or not 1 <= top_k <= 30:
                raise InvestigationError("RH_REFERENCE_EVIDENCE","reference RAG top_k is invalid")
            try:
                with RagLibrary(rag_workspace,read_only=True) as library:
                    reference_policy={item.get("document_id"):item for item in scenario.get("references",[]) if isinstance(item,dict)}
                    allowed_documents=[document_id for document_id,policy in reference_policy.items() if document_id and policy.get("visibility")=="public"]
                    rag_result=library.search_evidence(spec["research_question"],top_k=top_k,filters={"document_ids":allowed_documents})
                    explicit_reference_evidence=[]
                    for item in rag_result["items"]:
                        policy=reference_policy.get(item["document_id"],{})
                        explicit_reference_evidence.append({**item,"context":library.get_evidence_context(item["evidence_id"],before=1,after=1)["items"],"visibility":"public" if policy.get("visibility")=="public" else "confidential","company_id":policy.get("company_id")})
                    scenario["reference_rag_diagnostics"]=rag_result["diagnostics"]
                    if not explicit_reference_evidence:
                        scenario["reference_rag_diagnostics"]["evidence_gap"]="no reference RAG evidence matched the research question"
            except (RagError,sqlite3.Error,OSError) as error:
                raise InvestigationError(getattr(error,"code","RH_REFERENCE_RAG"),"read-only reference RAG retrieval failed") from error
            scenario["reference_rag_evidence_ids"]=[item["evidence_id"] for item in explicit_reference_evidence]
        if (live or registered_snapshot is not None) and (not isinstance(explicit_reference_evidence,list) or any(not isinstance(item,dict) or not item.get("evidence_id") or not item.get("document_id") or not item.get("version_id") or not isinstance(item.get("text"),str) or not item["text"] or not isinstance(item.get("locator"),dict) or not (item["locator"].get("kind") and item["locator"].get("value") or isinstance(item["locator"].get("line_start"),int) and item["locator"]["line_start"]>=1 and isinstance(item["locator"].get("line_end"),int) and item["locator"]["line_end"]>=item["locator"]["line_start"] or item["locator"].get("pages")) for item in explicit_reference_evidence)):
            raise InvestigationError("RH_REFERENCE_EVIDENCE","live runs require explicit reference_evidence")
        if registered_snapshot is not None:
            scenario["reference_rag_evidence_ids"]=[item["evidence_id"] for item in explicit_reference_evidence]
            scenario.setdefault("reference_rag_diagnostics",{"mode":"hybrid","evidence_gap":"no evidence matched in the selected library scope"})
        scenario["baseline_snapshot"]=explicit_reference_evidence if live or registered_snapshot is not None else baseline_snapshot(scenario.get("references",[]),runtime)
        blocked=[x.get("document_id") for x in scenario.get("references",[]) if not policy_allows(x,runtime)]
        if live or registered_snapshot is not None: blocked.extend(x.get("evidence_id") for x in explicit_reference_evidence if not policy_allows(x,runtime))
        run="inv-"+uuid.uuid4().hex[:12]; now=time.time(); budget=dict(runtime.get("budget",{})); budget.setdefault("max_tasks",8); budget.setdefault("max_source_calls",0); budget.setdefault("max_source_bytes",0); budget.setdefault("max_source_response_bytes",0); budget.setdefault("max_downloads",0); budget.setdefault("max_download_calls",0); budget.setdefault("max_download_bytes",0); budget["reserved_tasks"]=0; budget["reserved_model_calls"]=0; budget["reserved_source_calls"]=0; budget["reserved_source_bytes"]=0; budget["reserved_openalex_calls"]=0; budget["reserved_download_calls"]=0; budget["reserved_download_bytes"]=0; budget["reserved_downloads"]=0; budget["received_download_bytes"]=0; budget["received_source_bytes"]=0
        self.db.execute("INSERT INTO investigations VALUES (?,?,?,?,?,?,?,?,?,?,?)",(run,json.dumps(spec),json.dumps(runtime),json.dumps(scenario),"running","planning",json.dumps(budget),now,now,None,"[]")); self.db.commit()
        if blocked:
            self._trace(run,"planning_gate","policy_blocked",{"code":"RH_POLICY_BLOCKED","references":blocked})
            self._set(run,status="policy_blocked",stage="policy_blocked")
            return {"run_id":run,"stage":"policy_blocked","status":"policy_blocked"}
        self._task(run,"planning","plan",{"input_refs":[item["evidence_id"] for item in scenario["baseline_snapshot"] if isinstance(item,dict) and isinstance(item.get("evidence_id"),str)],"spec":spec,"scenario_refs":["scenario:sources"],"baseline_evidence":scenario["baseline_snapshot"],"reference_rag_diagnostics":scenario.get("reference_rag_diagnostics"),"reference_rag_evidence_ids":scenario.get("reference_rag_evidence_ids",[])}); self._set(run,status="waiting_model",stage="planning")
        return {"run_id":run,"stage":"planning","status":"waiting_model"}
    def get_pending_tasks(self,run_id):
        self._run(run_id); rows=self.db.execute("SELECT * FROM model_tasks WHERE run_id=? AND status='pending' ORDER BY created,id",(run_id,))
        output=[]
        for r in rows:
            payload=json.loads(r["payload"])
            if self._has_unresolved_source_query(run_id):
                continue
            if self.db.execute("SELECT 1 FROM model_api_calls WHERE task_id=? AND task_version=? AND status IN ('reserved','prepared','dispatching','response_received','outcome_unknown')",(r["id"],r["task_version"])).fetchone(): continue
            if self.db.execute("SELECT 1 FROM engine_task_leases WHERE task_id=? AND task_version=? AND status IN ('reserved','dispatching','outcome_unknown','accepted')",(r["id"],r["task_version"])).fetchone(): continue
            operations=["submit_structured_result"]
            run_row=self._run(run_id); runtime=json.loads(run_row["runtime"])
            if self._source_task_allowed(run_row,r["role"],r["task_type"],runtime):
                operations.append("execute_patent_source")
            output.append({"task_id":r["id"],"task_version":r["task_version"],"role":r["role"],"task_type":r["task_type"],"input_refs":payload.get("input_refs",[]),"payload":payload,"output_schema":json.loads(r["output_schema"]),"allowed_operations":operations})
        return output
    def _has_unresolved_source_query(self,run_id,task_id=None,task_version=None):
        # Source query leases are created before the first physical attempt, so
        # this guard must include dispatching logical queries with no attempt row.
        return (self.db.execute("SELECT 1 FROM source_queries WHERE run_id=? AND status IN ('pending','dispatching','outcome_unknown') LIMIT 1",(run_id,)).fetchone() is not None
                or self.db.execute("SELECT 1 FROM source_attempts WHERE run_id=? AND status IN ('pending','dispatching','outcome_unknown') LIMIT 1",(run_id,)).fetchone() is not None)
    @staticmethod
    def _source_task_allowed(run_row,role,task_type,runtime):
        profiles=runtime.get("patent_sources")
        if run_row["status"] in {"stopped","completed","partial","failed","policy_blocked","cancelled"} or not isinstance(profiles,dict): return False
        if not any(isinstance(value,dict) and value.get("enabled") is True for value in profiles.values()): return False
        allowed={("planning","planning"): {"plan"}, ("planning","patent_search"): {"screen:*"}, ("planning","paper_search"): {"screen:*"},
                 ("source","patent_search"): {"search","screen","source_screening"},
                 ("source","paper_search"): {"search","screen","source_screening"},
                 ("source","evidence_analysis"): {"extract"}, ("analysis","evidence_analysis"): {"extract"}}
        candidates=allowed.get((run_row["stage"],role),set())
        return task_type in candidates or ("screen:*" in candidates and task_type.startswith("screen:"))
    def reserve_model_call(self,run_id,task_id,task_version):
        run=self._run(run_id)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            run=self._run(run_id); task=self.db.execute("SELECT task_version,status FROM model_tasks WHERE id=? AND run_id=?",(task_id,run_id)).fetchone()
            if not task or task["status"]!="pending" or task["task_version"]!=task_version: raise InvestigationError("RH_TASK_VERSION","model task is no longer pending")
            if self._has_unresolved_source_query(run_id): raise InvestigationError("RH_SOURCE_CALL_IN_FLIGHT","a source request is unresolved")
            if json.loads(run["runtime"]).get("mode")!="api": raise InvestigationError("RH_MODEL_MODE","run is not configured for model API execution")
            if self.db.execute("SELECT 1 FROM engine_task_leases WHERE run_id=? AND status IN ('reserved','dispatching','outcome_unknown') LIMIT 1",(run_id,)).fetchone(): raise InvestigationError("RH_ENGINE_LEASE","an engine request is unresolved")
            if self.db.execute("SELECT 1 FROM model_api_calls WHERE task_id=? AND task_version=? AND status IN ('reserved','prepared','dispatching','response_received','outcome_unknown')",(task_id,task_version)).fetchone(): raise InvestigationError("RH_MODEL_CALL_IN_FLIGHT","this task version already has an unresolved model call")
            budget=json.loads(run["budget"])
            if budget.get("reserved_model_calls",0)>=budget["max_model_calls"]: raise InvestigationError("RH_MODEL_CALL_BUDGET","model API call budget exhausted")
            call_id="call-"+uuid.uuid4().hex[:16]; budget["reserved_model_calls"]=budget.get("reserved_model_calls",0)+1
            now=time.time(); self.db.execute("INSERT INTO model_api_calls VALUES (?,?,?,?,?,?,?)",(call_id,run_id,task_id,task_version,"reserved",None,now))
            self.db.execute("INSERT INTO model_call_events(call_id,event,created) VALUES (?,?,?)",(call_id,"reserved",now))
            self.db.execute("UPDATE investigations SET budget=?,updated=? WHERE id=?",(json.dumps(budget),now,run_id)); self.db.commit()
        except Exception:
            self.db.rollback(); raise
        return call_id
    def reserve_engine_lease(self,run_id,task_id,task_version):
        """Atomically claim the engine send-right for exactly one task version."""
        self.db.execute("BEGIN IMMEDIATE")
        try:
            run=self._run(run_id)
            if run["status"] in {"stopped","completed","partial","failed","policy_blocked","cancelled"}: raise InvestigationError("RH_RUN_INACTIVE","engine lease requires an active run")
            row=self.db.execute("SELECT status FROM model_tasks WHERE id=? AND run_id=? AND task_version=? AND status='pending'",(task_id,run_id,task_version)).fetchone()
            if not row: raise InvestigationError("RH_TASK_VERSION","engine task is no longer pending")
            if self._has_unresolved_source_query(run_id): raise InvestigationError("RH_SOURCE_CALL_IN_FLIGHT","a source request is unresolved")
            if self.db.execute("SELECT 1 FROM model_api_calls WHERE run_id=? AND status IN ('reserved','prepared','dispatching','response_received','outcome_unknown') LIMIT 1",(run_id,)).fetchone(): raise InvestigationError("RH_MODEL_CALL_IN_FLIGHT","a model request is unresolved")
            if self.db.execute("SELECT 1 FROM engine_task_leases WHERE task_id=? AND task_version=? AND status IN ('reserved','dispatching','outcome_unknown','accepted')",(task_id,task_version)).fetchone():
                raise InvestigationError("RH_ENGINE_LEASE","task version already has an engine lease")
            if self.db.execute("SELECT 1 FROM engine_task_leases WHERE run_id=? AND status IN ('reserved','dispatching','outcome_unknown') LIMIT 1",(run_id,)).fetchone(): raise InvestigationError("RH_ENGINE_LEASE","another engine request is unresolved")
            lease="engine-"+uuid.uuid4().hex[:16]; now=time.time()
            self.db.execute("INSERT INTO engine_task_leases VALUES (?,?,?,?,?,?)",(lease,run_id,task_id,task_version,"reserved",now)); self.db.commit(); return lease
        except Exception:
            self.db.rollback(); raise
    def mark_engine_dispatching(self,lease_id):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            changed=self.db.execute("UPDATE engine_task_leases SET status='dispatching' WHERE id=? AND status='reserved'",(lease_id,)).rowcount
            if changed!=1: raise InvestigationError("RH_ENGINE_LEASE","engine lease is not reserved")
            self.db.commit()
        except Exception: self.db.rollback(); raise
    def finish_engine_lease(self,lease_id,status):
        if status not in {"accepted","failed","outcome_unknown"}: raise InvestigationError("RH_ENGINE_LEASE","invalid engine terminal state")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row=self.db.execute("SELECT status FROM engine_task_leases WHERE id=?",(lease_id,)).fetchone()
            if not row or row["status"]!="dispatching": raise InvestigationError("RH_ENGINE_LEASE","engine lease is terminal or was never dispatched")
            unresolved=self.db.execute("SELECT 1 FROM engine_model_calls e JOIN model_api_calls m ON m.id=e.call_id WHERE e.lease_id=? AND m.status IN ('reserved','prepared','dispatching','response_received','outcome_unknown')",(lease_id,)).fetchone()
            if unresolved:
                if status=="accepted": raise InvestigationError("RH_ENGINE_LEASE","accepted engine lease requires no unresolved child calls")
                status="outcome_unknown"
            if status=="accepted":
                parent=self.db.execute("SELECT task_id,task_version FROM engine_task_leases WHERE id=?",(lease_id,)).fetchone()
                task=self.db.execute("SELECT status FROM model_tasks WHERE id=? AND task_version=?",(parent["task_id"],parent["task_version"])).fetchone()
                if not task or task["status"]!="completed" or unresolved or not self.db.execute("SELECT 1 FROM engine_model_calls e JOIN model_api_calls m ON m.id=e.call_id WHERE e.lease_id=? AND m.status='accepted'",(lease_id,)).fetchone():
                    raise InvestigationError("RH_ENGINE_LEASE","accepted engine lease requires an accepted task result and no unresolved child calls")
            changed=self.db.execute("UPDATE engine_task_leases SET status=? WHERE id=? AND status='dispatching'",(status,lease_id)).rowcount
            if changed!=1: raise InvestigationError("RH_ENGINE_LEASE","engine lease changed before finalization")
            self.db.commit()
        except Exception: self.db.rollback(); raise
    def reserve_engine_model_call(self,lease_id,request_id,kind,purpose):
        if kind not in {"model_call","embedding","retrieve_frozen"} or not isinstance(request_id,str) or not request_id or not isinstance(purpose,str) or not purpose:
            raise InvestigationError("RH_ENGINE_RPC","invalid engine broker request")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            lease=self.db.execute("SELECT run_id,task_id,task_version,status FROM engine_task_leases WHERE id=?",(lease_id,)).fetchone()
            if not lease or lease["status"]!="dispatching": raise InvestigationError("RH_ENGINE_LEASE","engine does not own an active dispatch lease")
            if self.db.execute("SELECT 1 FROM engine_model_calls WHERE lease_id=? AND request_id=?",(lease_id,request_id)).fetchone(): raise InvestigationError("RH_ENGINE_RPC","engine request id was already reserved")
            if self.db.execute("SELECT 1 FROM engine_model_calls e JOIN model_api_calls m ON m.id=e.call_id WHERE e.lease_id=? AND m.status IN ('reserved','prepared','dispatching','response_received','outcome_unknown')",(lease_id,)).fetchone(): raise InvestigationError("RH_MODEL_CALL_IN_FLIGHT","engine already has an unresolved broker call")
            run=self._run(lease["run_id"]); task=self.db.execute("SELECT task_version,status FROM model_tasks WHERE id=? AND run_id=?",(lease["task_id"],lease["run_id"])).fetchone()
            if self._has_unresolved_source_query(lease["run_id"]): raise InvestigationError("RH_SOURCE_CALL_IN_FLIGHT","a source request is unresolved")
            if not task or task["status"]!="pending" or task["task_version"]!=lease["task_version"]: raise InvestigationError("RH_TASK_VERSION","engine task is no longer pending")
            budget=json.loads(run["budget"])
            if budget.get("reserved_model_calls",0)>=budget["max_model_calls"]: raise InvestigationError("RH_MODEL_CALL_BUDGET","model API call budget exhausted")
            call_id="call-"+uuid.uuid4().hex[:16]; budget["reserved_model_calls"]=budget.get("reserved_model_calls",0)+1
            now=time.time(); self.db.execute("INSERT INTO model_api_calls VALUES (?,?,?,?,?,?,?)",(call_id,lease["run_id"],lease["task_id"],lease["task_version"],"reserved",None,now))
            self.db.execute("INSERT INTO model_call_events(call_id,event,created) VALUES (?,?,?)",(call_id,"reserved",now))
            ledger_kind = {"embedding":"embedding", "retrieve_frozen":"retrieval", "model_call":"model"}[kind]
            self.db.execute("INSERT INTO engine_model_calls VALUES (?,?,?,?,?)",(call_id,lease_id,request_id,ledger_kind,purpose))
            self.db.execute("UPDATE investigations SET budget=?,updated=? WHERE id=?",(json.dumps(budget),now,lease["run_id"])); self.db.commit()
        except Exception:
            self.db.rollback(); raise
        return call_id
    def engine_context(self,run_id,task,rpc,profile,authorization=None):
        from .investigation_context import build_context_bundle
        prompt=json.dumps(rpc["request"],ensure_ascii=False,sort_keys=True,separators=(",",":"))
        evidence=task["payload"].get("evidence",[])
        evidence_ids=[item.get("evidence_id") for item in evidence if isinstance(item,dict) and isinstance(item.get("evidence_id"),str)] if isinstance(evidence,list) else []
        request=rpc["request"]
        selected_context={key:request[key] for key in ("texts","input","context_ids","citation_ids") if key in request}
        messages=request.get("messages",[])
        prompt_text="\n".join(item.get("content","") for item in messages if isinstance(item,dict) and isinstance(item.get("content"),str)) if isinstance(messages,list) else ""
        prompt_context_ids=sorted(set(re.findall(r"pqac-[A-Za-z0-9_-]+",prompt_text)))
        selected_context["paperqa_context_ids_in_request"] = prompt_context_ids
        budget=self.status(run_id)["budget"]
        return build_context_bundle(run_id=run_id,task_id=task["task_id"],task_version=task["task_version"],payload=task["payload"],
            output_schema=task["output_schema"],prompt=prompt,profile={k:v for k,v in profile.items() if k not in {"api_key_env"}},
            included_refs=task.get("input_refs",[]),template_version="paperqa-2026.8.12",budget={**{k:budget.get(k) for k in ("max_model_calls","reserved_model_calls")},"kind":rpc["op"]},
            authorization=authorization or {"result":"unknown","policy":"core broker"},retrieval_selection={"offered_frozen_evidence_ids":evidence_ids,
                "request_selection":selected_context,"selection_status":"context_ids_available" if prompt_context_ids else "not_available_in_this_rpc"})
    def record_engine_receipt(self,run_id,task,lease_id,result,resolution,authorization):
        from .investigation_context import canonical_bytes
        directory=self.root/"engine_receipts"; directory.mkdir(parents=True,exist_ok=True)
        receipt_id="engine-receipt-"+uuid.uuid4().hex[:16]; target=directory/(receipt_id+".json")
        body={"run_id":run_id,"task_id":task["task_id"],"task_version":task["task_version"],"lease_id":lease_id,
              "engine_result":result,"resolution":resolution,"authorization":authorization}
        data=canonical_bytes(body); digest=hashlib.sha256(data).hexdigest(); temporary=target.with_name(target.name+"."+uuid.uuid4().hex+".tmp"); created=False
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if self.db.execute("SELECT 1 FROM engine_receipts WHERE lease_id=?",(lease_id,)).fetchone() or self.db.execute("SELECT status FROM engine_task_leases WHERE id=?",(lease_id,)).fetchone()["status"]!="dispatching":
                raise InvestigationError("RH_ENGINE_RECEIPT","engine receipt already exists or lease is not dispatching")
            temporary.write_bytes(data); os.replace(temporary,target); created=True
            self.db.execute("INSERT INTO engine_receipts VALUES (?,?,?,?,?,?,?,?)",(receipt_id,run_id,task["task_id"],task["task_version"],lease_id,str(target.relative_to(self.root)),digest,time.time()))
            self.db.commit()
        except Exception:
            self.db.rollback(); temporary.unlink(missing_ok=True)
            if created: target.unlink(missing_ok=True)
            raise
        return receipt_id
    def read_engine_receipt(self,receipt_id):
        row=self.db.execute("SELECT * FROM engine_receipts WHERE id=?",(receipt_id,)).fetchone()
        if not row: raise NotFoundError()
        base=self.root.resolve(); path=(base/row["path"]).resolve()
        if base not in path.parents or not path.is_file(): raise InvestigationError("RH_ENGINE_RECEIPT_PATH","engine receipt path is invalid")
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=row["sha256"]: raise InvestigationError("RH_ENGINE_RECEIPT_HASH","engine receipt hash does not match")
        return json.loads(raw)
    def add_engine_coverage_issue(self,run_id,task_id,task_version,receipt_id,gaps,issues,excluded_claims):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row=self.db.execute("SELECT payload,task_version,status FROM model_tasks WHERE id=? AND run_id=?",(task_id,run_id)).fetchone()
            if not row or row["task_version"]!=task_version or row["status"]!="pending": raise InvestigationError("RH_TASK_VERSION","engine task changed before recording coverage gaps")
            payload=json.loads(row["payload"]); coverage={"code":"RH_ENGINE_COVERAGE_GAP","status":"open","receipt_id":receipt_id,"gaps":gaps,"issues":[item.get("code") for item in issues],"excluded_claims":excluded_claims}
            payload["acquisition_issues"]=[*payload.get("acquisition_issues",[]),coverage]
            self.db.execute("UPDATE model_tasks SET payload=? WHERE id=? AND task_version=? AND status='pending'",(json.dumps(payload,ensure_ascii=False),task_id,task_version)); self.db.commit()
        except Exception: self.db.rollback(); raise
    def run_local_embedding(self,runtime,texts):
        import subprocess,sys
        config=runtime.get("research_engine",{}).get("local_embedding",{})
        python=config.get("python_executable"); model=config.get("model"); cache=config.get("cache_dir")
        if not all(isinstance(value,str) and value for value in (python,model,cache)) or not Path(python).is_absolute() or not Path(cache).is_absolute():
            raise InvestigationError("RH_ENGINE_EMBEDDING_PENDING","local embedding executable, model and cache must be explicitly configured")
        if not isinstance(texts,list) or any(not isinstance(value,str) for value in texts): raise InvestigationError("RH_ENGINE_EMBEDDING","embedding input must be text array")
        code="import json,socket,sys; deny=lambda *a,**k: (_ for _ in ()).throw(PermissionError('network disabled')); socket.create_connection=deny; socket.getaddrinfo=deny; socket.socket.connect=deny; from fastembed import TextEmbedding; from fastembed.common.model_description import ModelSource,PoolingType; cfg=json.loads(sys.stdin.read()); supported={x['model'] for x in TextEmbedding.list_supported_models()}; (TextEmbedding.add_custom_model(model=cfg['model'],pooling=PoolingType.MEAN,normalization=True,sources=ModelSource(hf=cfg['model']),dim=384,model_file='onnx/model.onnx',license='mit') if cfg['model']=='intfloat/multilingual-e5-small' and cfg['model'] not in supported else None); e=TextEmbedding(model_name=cfg['model'],cache_dir=cfg['cache'],threads=2); print(json.dumps([v.tolist() for v in e.embed(cfg['texts'])]))"
        proc=subprocess.run([python,"-c",code],input=json.dumps({"model":model,"cache":cache,"texts":texts}),text=True,capture_output=True,timeout=120,check=False,env=self._embedding_environment())
        if proc.returncode: raise InvestigationError("RH_ENGINE_EMBEDDING_FAILED","local embedding execution failed")
        try: return json.loads(proc.stdout)
        except ValueError as error: raise InvestigationError("RH_ENGINE_EMBEDDING_FAILED","local embedding output is invalid") from error
    @staticmethod
    def _embedding_environment():
        allowed={"SYSTEMROOT","WINDIR","TEMP","TMP","PATH"}
        return {key:value for key,value in os.environ.items() if key.upper() in allowed} | {"PYTHONNOUSERSITE":"1","PYTHONUTF8":"1","HF_HUB_OFFLINE":"1"}
    def local_embedding_model_supported(self,runtime):
        import subprocess
        config=runtime.get("research_engine",{}).get("local_embedding",{}); python=config.get("python_executable"); model=config.get("model")
        if not isinstance(python,str) or not Path(python).is_absolute() or not Path(python).is_file() or not isinstance(model,str): return False
        code="import json,socket,sys; deny=lambda *a,**k: (_ for _ in ()).throw(PermissionError('network disabled')); socket.create_connection=deny; socket.getaddrinfo=deny; socket.socket.connect=deny; from fastembed import TextEmbedding; from fastembed.common.model_description import ModelSource,PoolingType; model=sys.argv[1]; supported={x['model'] for x in TextEmbedding.list_supported_models()}; (TextEmbedding.add_custom_model(model=model,pooling=PoolingType.MEAN,normalization=True,sources=ModelSource(hf=model),dim=384,model_file='onnx/model.onnx',license='mit') if model=='intfloat/multilingual-e5-small' and model not in supported else None); print(json.dumps(sorted({x['model'] for x in TextEmbedding.list_supported_models()})))"
        proc=subprocess.run([python,"-c",code,model],text=True,capture_output=True,timeout=30,check=False,env=self._embedding_environment())
        if proc.returncode: return False
        try: return model in json.loads(proc.stdout)
        except (ValueError,TypeError): return False
    def prepare_model_call(self,call_id,body,context):
        from .investigation_context import canonical_bytes, verify_context_bundle
        if not verify_context_bundle(context): raise InvestigationError("RH_CONTEXT_INVALID","context receipt failed hash verification")
        directory=self.root/"model_context"; directory.mkdir(parents=True,exist_ok=True)
        target=directory/(call_id+".json"); data=canonical_bytes({"request_body":body,"context":context}); digest=hashlib.sha256(data).hexdigest()
        temporary=target.with_name(target.name+"."+uuid.uuid4().hex+".tmp"); created=False
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row=self.db.execute("SELECT status FROM model_api_calls WHERE id=?",(call_id,)).fetchone()
            if not row or row["status"]!="reserved" or self.db.execute("SELECT 1 FROM model_call_receipts WHERE call_id=?",(call_id,)).fetchone() or target.exists():
                raise InvestigationError("RH_MODEL_CALL_STATE","model call is not an unprepared reservation")
            temporary.write_bytes(data); os.replace(temporary,target); created=True
            now=time.time(); changed=self.db.execute("UPDATE model_api_calls SET status='prepared' WHERE id=? AND status='reserved'",(call_id,)).rowcount
            if changed!=1: raise InvestigationError("RH_MODEL_CALL_STATE","model call reservation changed before prepare")
            self.db.execute("INSERT INTO model_call_receipts(call_id,context_path,context_hash,logical_hash) VALUES (?,?,?,?)",(call_id,str(target.relative_to(self.root)),digest,context["logical_sha256"]))
            self.db.execute("INSERT INTO model_call_events(call_id,event,details,created) VALUES (?,?,?,?)",(call_id,"prepared",json.dumps({"context_sha256":digest}),now)); self.db.commit()
        except Exception:
            self.db.rollback(); temporary.unlink(missing_ok=True)
            if created: target.unlink(missing_ok=True)
            raise
    def mark_model_call_dispatching(self,call_id):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            now=time.time(); changed=self.db.execute("UPDATE model_api_calls SET status='dispatching' WHERE id=? AND status='prepared'",(call_id,)).rowcount
            if changed!=1: raise InvestigationError("RH_MODEL_CALL_STATE","model call is not prepared for dispatch")
            self.db.execute("INSERT INTO model_call_events(call_id,event,created) VALUES (?,?,?)",(call_id,"dispatching",now)); self.db.commit()
        except Exception:
            self.db.rollback(); raise
    def record_model_response(self,call_id,response_bytes):
        directory=self.root/"model_context"; target=directory/(call_id+".response"); digest=hashlib.sha256(response_bytes).hexdigest(); temporary=target.with_name(target.name+"."+uuid.uuid4().hex+".tmp"); created=False
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row=self.db.execute("SELECT status FROM model_api_calls WHERE id=?",(call_id,)).fetchone()
            if not row or row["status"]!="dispatching" or target.exists(): raise InvestigationError("RH_MODEL_CALL_STATE","model call cannot accept another response")
            temporary.write_bytes(response_bytes); os.replace(temporary,target); created=True
            now=time.time(); changed=self.db.execute("UPDATE model_api_calls SET status='response_received' WHERE id=? AND status='dispatching'",(call_id,)).rowcount
            if changed!=1: raise InvestigationError("RH_MODEL_CALL_STATE","model call changed before response receipt")
            changed=self.db.execute("UPDATE model_call_receipts SET response_path=?,response_hash=? WHERE call_id=? AND response_path IS NULL",(str(target.relative_to(self.root)),digest,call_id)).rowcount
            if changed!=1: raise InvestigationError("RH_MODEL_CALL_STATE","model call receipt already has a response")
            self.db.execute("INSERT INTO model_call_events(call_id,event,details,created) VALUES (?,?,?,?)",(call_id,"response_received",json.dumps({"response_sha256":digest}),now)); self.db.commit()
        except Exception:
            self.db.rollback(); temporary.unlink(missing_ok=True)
            if created: target.unlink(missing_ok=True)
            raise
    def read_model_call_receipt(self,call_id):
        from .investigation_context import verify_context_bundle
        row=self.db.execute("SELECT r.*,c.status FROM model_call_receipts r JOIN model_api_calls c ON c.id=r.call_id WHERE r.call_id=?",(call_id,)).fetchone()
        if not row: raise NotFoundError()
        base=self.root.resolve()
        def read_verified(relative,digest):
            path=(base/relative).resolve()
            if base not in path.parents or not path.is_file(): raise InvestigationError("RH_RECEIPT_PATH","saved model receipt path is invalid")
            raw=path.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=digest: raise InvestigationError("RH_RECEIPT_HASH","saved model receipt hash does not match")
            return raw
        saved=json.loads(read_verified(row["context_path"],row["context_hash"]))
        if saved["context"].get("logical_sha256")!=row["logical_hash"] or not verify_context_bundle(saved["context"]): raise InvestigationError("RH_RECEIPT_HASH","saved model context receipt is invalid")
        response=None
        if row["response_path"]: response=read_verified(row["response_path"],row["response_hash"])
        return {"request_body":saved["request_body"],"context":saved["context"],"response_bytes":response,"status":row["status"]}
    def finish_model_call(self,call_id,status,usage):
        if status not in {"accepted","failed"}: raise InvestigationError("RH_MODEL_CALL_STATE","invalid model call terminal result")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row=self.db.execute("SELECT c.status,c.task_id,c.task_version,t.status AS task_status,t.task_version AS current_version, e.lease_id FROM model_api_calls c LEFT JOIN model_tasks t ON t.id=c.task_id LEFT JOIN engine_model_calls e ON e.call_id=c.id WHERE c.id=?",(call_id,)).fetchone()
            if not row: raise NotFoundError()
            if row["status"] in {"accepted","failed","outcome_unknown"}: raise InvestigationError("RH_MODEL_CALL_STATE","model call is already terminal")
            if status=="accepted":
                engine_call = row["lease_id"] is not None
                if row["status"]!="response_received" or row["current_version"]!=row["task_version"] or (not engine_call and row["task_status"]!="completed"):
                    raise InvestigationError("RH_MODEL_CALL_STATE","accepted call requires a received response and accepted task result")
                final="accepted"
            elif row["status"]=="dispatching": final="outcome_unknown"
            elif row["status"] in {"reserved","prepared","response_received"}: final="failed"
            else: raise InvestigationError("RH_MODEL_CALL_STATE","model call cannot be finalized from this state")
            changed=self.db.execute("UPDATE model_api_calls SET status=?,usage=? WHERE id=? AND status=?",(final,json.dumps(usage) if usage is not None else None,call_id,row["status"])).rowcount
            if changed!=1: raise InvestigationError("RH_MODEL_CALL_STATE","model call changed before finalization")
            self.db.execute("INSERT INTO model_call_events(call_id,event,created) VALUES (?,?,?)",(call_id,final,time.time())); self.db.commit()
        except Exception:
            self.db.rollback(); raise
    def close_model_call_budget(self,run_id):
        row=self._run(run_id)
        if row["status"] in {"completed","partial","failed","policy_blocked"}: return
        result={"run_id":run_id,"synthetic":self._synthetic_run(run_id),"outcome":"partial","conclusion":"Model API call budget exhausted.","artifacts":[],"issues":[{"code":"RH_MODEL_CALL_BUDGET","status":"open"}]}
        self.db.execute("UPDATE investigations SET status='partial',stage='budget_exhausted',result=?,updated=? WHERE id=?",(json.dumps(result),time.time(),run_id))
        self.db.commit()
    def submit_model_result(self,run_id,task_id,result,task_version):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            run=self._run(run_id)
            if run["status"] == "stopped": raise InvestigationError("RH_RUN_STOPPED","resume run before submitting a task")
            if self._has_unresolved_source_query(run_id): raise InvestigationError("RH_SOURCE_CALL_IN_FLIGHT","a source request is unresolved")
            row=self.db.execute("SELECT * FROM model_tasks WHERE id=? AND run_id=?",(task_id,run_id)).fetchone()
            if not row: raise NotFoundError()
            if row["task_version"]!=task_version: raise InvestigationError("RH_TASK_VERSION","task version is stale")
            raw=json.dumps(result,ensure_ascii=False,sort_keys=True,separators=(",",":")); digest=hashlib.sha256(raw.encode()).hexdigest()
            if row["status"]=="completed":
                if row["result_hash"]==digest:
                    self.db.commit(); return {"status":"reused","task_id":task_id}
                raise InvestigationError("RH_TASK_CONFLICT","different task result was submitted")
            errors=list(Draft202012Validator(json.loads(row["output_schema"])).iter_errors(result))
            if errors: raise InvestigationError("RH_MODEL_RESULT_INVALID","model result failed schema validation at "+".".join(map(str,errors[0].absolute_path))+": "+errors[0].message)
            self._refs(row,result); self.db.execute("UPDATE model_tasks SET status='completed',result=?,result_hash=? WHERE id=? AND status='pending'",(raw,digest,task_id))
            if self.db.execute("SELECT changes()").fetchone()[0]!=1: raise InvestigationError("RH_TASK_CONFLICT","task changed before result submission")
            self.db.commit()
        except Exception:
            self.db.rollback(); raise
        if row["role"] == "business_judgment": self._record_monitor_judgments(row,result)
        return {"status":"accepted","task_id":task_id}
    def advance_investigation(self,run_id):
        if self._run(run_id)["status"] == "stopped":
            return {"run_id":run_id,"outcome":"stopped","stage":self._run(run_id)["stage"]}
        try: self.graph.invoke({"run_id":run_id})
        except InvestigationError as error:
            if error.code not in {"RH_MODEL_BUDGET","RH_MONITOR_BUDGET"}: raise
            extracted=self._done(run_id,"evidence_analysis","extract")
            evidence_row=self.db.execute("SELECT payload FROM model_tasks WHERE run_id=? AND role='evidence_analysis' AND task_type='extract'",(run_id,)).fetchone()
            result={"run_id":run_id,"synthetic":self._synthetic_run(run_id),"outcome":"partial","conclusion":"Task budget exhausted before the next stage.","verification":None,"findings":extracted[0]["findings"] if extracted else [],"evidence":json.loads(evidence_row["payload"])["evidence"] if evidence_row else [],"artifacts":[],"issues":[{"code":error.code,"status":"open"}]}
            self.db.execute("UPDATE investigations SET status='partial',stage='budget_exhausted',result=?,updated=? WHERE id=?",(json.dumps(result),time.time(),run_id)); self.db.commit()
        s=self.status(run_id)
        if s["status"] in ("completed","partial"): return {"run_id":run_id,"outcome":s["status"],"stage":"completed"}
        return {"run_id":run_id,"outcome":"waiting","waiting_reason":"model_task","stage":s["stage"]}
    def resume_investigation(self,run_id):
        if self._run(run_id)["status"] == "stopped":
            pending=bool(self._pending(run_id))
            self._set(run_id,status="waiting_model" if pending else "running")
        return self.advance_investigation(run_id)
    def request_stop(self,run_id):
        row=self._run(run_id)
        if row["status"] in ("completed","partial","failed","policy_blocked","stopped"):
            return self.status(run_id)
        self._set(run_id,status="stopped")
        return self.status(run_id)
    def status(self,run_id=None):
        if run_id is None:return {"runs":[self.status(r["id"]) for r in self.db.execute("SELECT id FROM investigations ORDER BY created DESC")]}
        r=self._run(run_id); coverage=self._coverage(run_id)
        runtime_config=json.loads(r["runtime"]); data_mode=runtime_config.get("data_mode")
        waiting="model_task" if r["status"]=="waiting_model" else ("policy_blocked" if r["status"]=="policy_blocked" else None)
        return {"run_id":run_id,"status":r["status"],"stage":r["stage"],"waiting_reason":waiting,"budget":json.loads(r["budget"]),"coverage":coverage,"stage_trace":json.loads(r["trace"]),"outcome":r["status"] if r["status"] in ("completed","partial","policy_blocked","stopped") else "waiting","data_mode":data_mode,"mode":runtime_config.get("mode"),"synthetic":data_mode=="synthetic"}
    def get_result(self,run_id):
        r=self._run(run_id)
        if not r["result"]: raise InvestigationError("RH_RESULT_PENDING","investigation has not reached verification")
        return json.loads(r["result"])
    def get_artifacts(self,run_id): return self.get_result(run_id).get("artifacts",[])
    def get_discovery_evidence(self,evidence_id,runtime=None):
        row=self.db.execute("SELECT payload,visibility,company_id FROM discovery_evidence WHERE evidence_id=?",(evidence_id,)).fetchone()
        if not row:
            for frozen in self.db.execute("SELECT payload FROM frozen_reports ORDER BY created DESC"):
                report=json.loads(frozen["payload"])
                item=next((item for item in report.get("evidence",[]) if item.get("evidence_id")==evidence_id),None)
                if item:
                    if item.get("visibility","public") != "public" and (not runtime or not policy_allows(item,runtime)):
                        raise InvestigationError("RH_POLICY_BLOCKED","report evidence is not authorized for this runtime")
                    return item
            raise NotFoundError()
        item=json.loads(row["payload"])
        if row["visibility"] != "public" and not runtime:
            raise InvestigationError("RH_POLICY_BLOCKED","confidential discovery evidence requires an authorized runtime")
        if row["visibility"] != "public" and not policy_allows({"visibility":row["visibility"],"company_id":row["company_id"]},runtime):
            raise InvestigationError("RH_POLICY_BLOCKED","discovery evidence is not authorized for this runtime")
        return item
    def get_discovery_document(self,run_id,document_id):
        self._run(run_id)
        row=self.db.execute("SELECT payload FROM discovery_documents WHERE run_id=? AND document_id=?",(run_id,document_id)).fetchone()
        if row: return json.loads(row["payload"])
        frozen=self.db.execute("SELECT payload FROM frozen_reports WHERE run_id=?",(run_id,)).fetchone()
        if not frozen: raise NotFoundError()
        report=json.loads(frozen["payload"])
        bibliography=next((item for item in report.get("bibliography",[]) if item.get("id")==document_id),None)
        if not bibliography: raise NotFoundError()
        def same_identity(item):
            if bibliography.get("publication_id"):
                return item.get("publication_id")==bibliography["publication_id"]
            if bibliography.get("doi"):
                return str(item.get("doi","")).lower()==str(bibliography["doi"]).lower()
            return False
        matches=[]
        for candidate in self.db.execute("SELECT payload FROM discovery_documents WHERE run_id=?",(run_id,)):
            item=json.loads(candidate["payload"])
            if same_identity(item): matches.append(item)
        if len(matches)==1:
            return {**matches[0],"canonical_document_id":document_id}
        excerpts=[item for item in report.get("evidence",[]) if item.get("document_id")==document_id]
        sections=[]
        for item in excerpts:
            locator=item.get("locator") or {}
            path=str(locator.get("value","")).lower()
            section="claims" if "/claim" in path else "description" if "/description" in path else "evidence"
            sections.append({"section":section,"locator":locator,"text":item.get("text",""),"evidence_id":item.get("evidence_id"),**{key:item[key] for key in ("parse_revision_id","source_sha256") if item.get(key)}})
        return {**bibliography,"document_id":document_id,"content_scope":"frozen_evidence_excerpts","epo_sections":sections,"text":"\n\n".join(item["text"] for item in sections),"fulltext_availability":None}
    def attach_discovery_evidence(self,run_id,evidence,mappings,bibliography=None):
        """Bind explicit C2 RAG facts to an acquired live document before analysis."""
        run=self._run(run_id)
        if json.loads(run["runtime"]).get("data_mode") != "live":
            raise InvestigationError("RH_FACT_INPUT","discovery RAG evidence can only be attached to a live run")
        if run["stage"] != "analysis" or self.db.execute("SELECT 1 FROM model_tasks WHERE run_id=? AND role='evidence_analysis' AND task_type='extract' AND status='pending'",(run_id,)).fetchone() is None:
            raise InvestigationError("RH_FACT_SNAPSHOT","discovery evidence can only be attached before analysis submission")
        if self.db.execute("SELECT 1 FROM model_tasks WHERE run_id=? AND role='business_judgment' AND status='completed'",(run_id,)).fetchone():
            raise InvestigationError("RH_FACT_SNAPSHOT","completed business judgment cannot receive new facts")
        if not all(isinstance(value,list) for value in (evidence,mappings,bibliography or [])):
            raise InvestigationError("RH_FACT_INPUT","evidence, mappings, and bibliography must be lists")
        acquired={item.get("document_id"):item for item in self._sources(run) if item.get("version")=="openalex-oa-pdf" or item.get("source")=="epo" and item.get("content_type")=="application/xml"}
        downloads={row["cursor"]:json.loads(row["result"]) for row in self.db.execute("SELECT cursor,result FROM source_attempts WHERE run_id=? AND query_id='download-document' AND status='success'",(run_id,)) if row["result"]}
        by_rag={(item.get("rag_document_id"),item.get("rag_version_id"),item.get("parse_revision_id")):item for item in mappings if isinstance(item,dict)}
        if len(by_rag) != len(mappings): raise InvestigationError("RH_FACT_INPUT","each RAG document/version mapping must be unique")
        resolved_mappings=[]
        for item in evidence:
            if not isinstance(item,dict) or not all(isinstance(item.get(key),str) and item[key] for key in ("evidence_id","document_id","version_id","text")) or not isinstance(item.get("locator"),dict):
                raise InvestigationError("RH_FACT_INPUT","RAG evidence needs identity, text, and locator")
            mapping=by_rag.get((item["document_id"],item["version_id"],item.get("parse_revision_id")))
            if mapping is None and item.get("parse_revision_id"):
                mapping=by_rag.get((item["document_id"],item["version_id"],None))
            if not mapping: raise InvestigationError("RH_FACT_IDENTITY","RAG evidence has no identity mapping")
            if item.get("parse_revision_id") and mapping.get("parse_revision_id") and mapping.get("parse_revision_id")!=item["parse_revision_id"]:
                raise InvestigationError("RH_FACT_IDENTITY","RAG mapping parse revision does not match evidence")
            if item.get("source_sha256") and mapping.get("source_sha256") and mapping.get("source_sha256")!=item["source_sha256"]:
                raise InvestigationError("RH_FACT_IDENTITY","RAG mapping source hash does not match evidence")
            resolved_mappings.append({**mapping,**{key:item[key] for key in ("parse_revision_id","source_sha256") if item.get(key)}})
            source=acquired.get(mapping.get("investigation_document_id")); download=downloads.get(mapping.get("investigation_document_id"))
            if not source or source.get("version") != mapping.get("investigation_version_id") or source.get("source")=="openalex" and not download:
                raise InvestigationError("RH_FACT_IDENTITY","mapping does not name an acquired document version")
            fingerprint=download.get("sha256") if download else source.get("content_sha256")
            if canonical_identity(source) != canonical_identity(mapping) or fingerprint != mapping.get("sha256"):
                raise InvestigationError("RH_FACT_IDENTITY","mapping source identity or content fingerprint does not match")
        payload={"evidence":evidence,"mappings":resolved_mappings,"bibliography":bibliography or []}
        encoded=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":"))
        existing=self.db.execute("SELECT payload FROM attached_discovery_evidence WHERE run_id=?",(run_id,)).fetchone()
        if existing:
            if existing["payload"] == encoded:return {"status":"reused","run_id":run_id,"evidence_count":len(evidence)}
            raise InvestigationError("RH_FACT_SNAPSHOT","discovery evidence is already attached")
        extract=self.db.execute("SELECT payload FROM model_tasks WHERE run_id=? AND role='evidence_analysis' AND task_type='extract' AND status='pending'",(run_id,)).fetchone()
        current=json.loads(extract["payload"])
        ids=[item.get("evidence_id") for item in [*current["evidence"],*evidence]]
        if len(ids) != len(set(ids)): raise InvestigationError("RH_FACT_IDENTITY","evidence IDs must be unique in the fact snapshot")
        self.db.execute("INSERT INTO attached_discovery_evidence VALUES (?,?)",(run_id,encoded))
        fact_document_ids={item.get("document_id") for item in [*current["evidence"],*evidence]}
        attached_bibliography=[item for item in bibliography or [] if isinstance(item,dict) and item.get("id") in fact_document_ids]
        complete_bibliography=[*current.get("bibliography",[]),*attached_bibliography]
        known_bibliography={item.get("id") for item in complete_bibliography if isinstance(item,dict)}
        complete_bibliography.extend(self._bibliography({"document_id":document_id}) for document_id in sorted(fact_document_ids) if document_id and document_id not in known_bibliography)
        updated={**current,"evidence":[*current["evidence"],*evidence],"bibliography":complete_bibliography}
        for row in self.db.execute("SELECT id,payload FROM model_tasks WHERE run_id=? AND status='pending' AND role IN ('evidence_analysis','business_judgment')",(run_id,)):
            task=json.loads(row["payload"]); task.update(updated)
            self.db.execute("UPDATE model_tasks SET payload=?,task_version=task_version+1 WHERE id=?",(json.dumps(task),row["id"]))
        self.db.commit()
        return {"status":"attached","run_id":run_id,"evidence_count":len(evidence)}
    def _fact_payload(self,run,acquired_evidence):
        scenario=json.loads(run["scenario"])
        baseline=scenario.get("baseline_snapshot",[])
        documents={item.get("document_id"):item for item in self._sources(run)}
        facts=[*baseline,*acquired_evidence]
        fact_document_ids={item.get("document_id") for item in facts}
        reference_bibliography=[item for item in scenario.get("reference_bibliography",[]) if isinstance(item,dict) and item.get("id") in fact_document_ids]
        acquired=[self._bibliography(item) for document_id,item in documents.items() if document_id in fact_document_ids]
        bibliography=[*reference_bibliography,*acquired]
        known_bibliography={item.get("id") for item in bibliography if isinstance(item,dict)}
        bibliography.extend(self._bibliography({"document_id":document_id}) for document_id in sorted(fact_document_ids) if document_id and document_id not in known_bibliography)
        return {"evidence":facts,"baseline_evidence":baseline,"bibliography":bibliography}
    def build_report_data(self,run_id):
        frozen=self.db.execute("SELECT payload FROM frozen_reports WHERE run_id=?",(run_id,)).fetchone()
        if not frozen: raise InvestigationError("RH_REPORT_DATA","report data has not been frozen")
        return json.loads(frozen["payload"])
    def export_report(self,run_id,languages=None):
        from .investigation_reporting import export_reports
        data=self.build_report_data(run_id); exported=export_reports(self.root,run_id,data,languages)
        has_query_details=self.db.execute("SELECT 1 FROM source_query_details WHERE run_id=?",(run_id,)).fetchone() is not None
        if "epo" in json.loads(self._run(run_id)["runtime"]).get("sources",{}) or has_query_details:
            exported["artifacts"].extend(self._export_epo_history(run_id,data["report_version"]))
        row=self._run(run_id); result=json.loads(row["result"]); result["artifacts"]=exported["artifacts"]
        self.db.execute("UPDATE investigations SET result=?,updated=? WHERE id=?",(json.dumps(result),time.time(),run_id));self.db.commit();return exported

    def _export_epo_history(self,run_id,version):
        target=self.root/"reports"/run_id/version
        queries=[]
        evidence_led=False
        for row in self.db.execute("SELECT * FROM source_queries WHERE run_id=? ORDER BY rowid",(run_id,)):
            item=dict(row); item.pop("run_id"); item["input_refs"]=json.loads(item["input_refs"])
            detail=self.db.execute("SELECT payload FROM source_query_details WHERE run_id=? AND query_id=?",(run_id,item["query_id"])).fetchone()
            if detail: evidence_led=True
            else: detail=self.db.execute("SELECT payload FROM epo_query_details WHERE run_id=? AND query_id=?",(run_id,item["query_id"])).fetchone()
            item.update(json.loads(detail["payload"]) if detail else {})
            item["syntax"]="OPS CQL" if item["source"]=="epo" else item["source"]
            item["attempts"]=[dict(x) for x in self.db.execute("SELECT cursor,attempt,status,result FROM source_attempts WHERE run_id=? AND query_id=? ORDER BY rowid",(run_id,item["query_id"]))]
            for attempt in item["attempts"]:
                result=json.loads(attempt.pop("result") or "{}")
                attempt["candidate_ids"]=[x.get("publication_id") or x.get("document_id") for x in result.get("candidates",[]) if x.get("publication_id") or x.get("document_id")]
                attempt["total"]=result.get("total")
            screen=self.db.execute("SELECT result FROM model_tasks WHERE run_id=? AND task_type=? AND status='completed'",(run_id,"screen:"+item["query_id"])).fetchone()
            item["screening"]=json.loads(screen["result"])["candidates"] if screen else []
            queries.append(item)
        requests_log=[json.loads(x["result"]) | {"status":x["status"],"attempt":x["attempt"],"request_id":x["cursor"]} for x in self.db.execute("SELECT cursor,attempt,status,result FROM source_attempts WHERE run_id=? AND query_id='epo-http' ORDER BY rowid",(run_id,))]
        documents=[json.loads(x["payload"]) for x in self.db.execute("SELECT payload FROM discovery_documents WHERE run_id=? ORDER BY rowid",(run_id,)) if json.loads(x["payload"]).get("source")=="epo"]
        for document in documents:
            document.pop("text",None); document.pop("epo_sections",None)
        history={"run_id":run_id,"source":"epo","queries":queries,"requests":requests_log,"publications":documents,"coverage":self._coverage(run_id),"budget":json.loads(self._run(run_id)["budget"])}
        if evidence_led:
            scenario=json.loads(self._run(run_id)["scenario"])
            cited={ref for query in queries for ref in query["input_refs"]}
            history["source"]="+".join(sorted({query["source"] for query in queries}))
            history["reference_evidence"]=[{key:hit.get(key) for key in ("evidence_id","document_id","version_id","locator","text")}
                                           for hit in scenario.get("baseline_snapshot",[]) if hit.get("evidence_id") in cited]
            history["source_attempts"]=[dict(row) for row in self.db.execute("SELECT query_id,cursor,attempt,status FROM source_attempts WHERE run_id=? AND query_id!='epo-http' ORDER BY rowid",(run_id,))]
        history_path=target/"search-history.json"; strategy_path=target/"search-strategy.zh-CN.md"
        history_text=json.dumps(history,ensure_ascii=False,indent=2)+"\n"
        strategy=["# 联合检索策略与执行记录" if evidence_led else "# EPO OPS 检索策略与执行记录","","来源：OpenAlex 与 EPO OPS。各查询按其来源语法记录，只有请求状态成功才视为实际执行。" if evidence_led else "来源：EPO OPS。下列 CQL 仅在状态和请求记录显示成功时视为实际执行。","",f"运行：`{run_id}`。","", "## 查询"]
        for item in queries:
            strategy.extend(["",f"### {item['query_id']} ({item['status']})",f"来源与语法：{item['syntax']}","```text",item["query"],"```",f"意图：{item.get('intent') or '未记录'}；术语依据：{item.get('terms_basis') or '未记录'}。",f"父查询：{item.get('parent_query_id') or '无'}；修改理由：{item.get('revision_reason') or '未记录'}。",f"过滤：{json.dumps(item.get('filters',{}),ensure_ascii=False)}；命中页：{len(item['attempts'])}。"])
        strategy.extend(["","## 覆盖与请求","",f"来源 HTTP 尝试总账：{history['budget']['reserved_source_calls']}；已接收字节：{history['budget']['received_source_bytes']}。" if evidence_led else f"OPS HTTP 尝试：{history['budget']['reserved_source_calls']}；已接收字节：{history['budget']['received_source_bytes']}。","逐请求状态、UTC 时间、范围、候选与原始 XML 路径见 `search-history.json`。",""])
        for path,body,kind in ((history_path,history_text,"search_history"),(strategy_path,"\n".join(strategy),"search_strategy")):
            if path.exists() and path.read_text(encoding="utf-8")!=body:
                raise InvestigationError("RH_REPORT_EXPORT","refusing to overwrite changed search history")
            path.write_text(body,encoding="utf-8")
        return [{"type":kind,"path":str(path.relative_to(self.root)).replace("\\","/"),"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"version":version} for path,kind in ((history_path,"search_history"),(strategy_path,"search_strategy"))]
    def validate_monitor(self,profile,monitor_spec,runtime):
        validate_runtime(runtime)
        if not isinstance(profile,dict) or not profile.get("company_id") or not profile.get("rule_version") or not isinstance(monitor_spec,dict) or not monitor_spec.get("name"): raise ValidationError("monitor profile, rule_version, and name are required")
        if profile.get("visibility","public") != "public" and not policy_allows(profile,runtime): raise InvestigationError("RH_POLICY_BLOCKED","monitor profile is not authorized for this runtime")
        return {"valid":True,"mode":"offline","scheduler":"disabled"}
    def create_monitor(self,profile,monitor_spec,runtime,scenario=None):
        self.validate_monitor(profile,monitor_spec,runtime)
        state=self.monitors.create(profile,monitor_spec,runtime)
        defaults=scenario or {}
        if not isinstance(defaults,dict): raise InvestigationError("RH_MONITOR_SCENARIO","monitor scenario must be an object")
        prior=self.db.execute("SELECT scenario FROM monitor_defaults WHERE monitor_id=?",(state["monitor_id"],)).fetchone()
        encoded=json.dumps(defaults,ensure_ascii=False,sort_keys=True)
        if prior and prior["scenario"] != encoded: raise InvestigationError("RH_MONITOR_SCENARIO","existing monitor defaults cannot be replaced")
        self.db.execute("INSERT OR IGNORE INTO monitor_defaults VALUES (?,?)",(state["monitor_id"],encoded)); self.db.commit()
        return {"monitor_id":state["monitor_id"],"status":state["status"],"scheduler":"disabled"}
    def update_monitor_profile(self,monitor_id,profile):
        return self.monitors.update_profile(monitor_id,profile)
    def monitor_status(self,monitor_id=None): return self.monitors.status(monitor_id)
    def pause_monitor(self,monitor_id): return self.monitors.pause(monitor_id)
    def resume_monitor(self,monitor_id): return self.monitors.resume(monitor_id)
    def review_list(self,monitor_id=None): return self.reviews.review_list(monitor_id)
    def review_decide(self,issue_id,decision,note=""): return self.reviews.review_decide(issue_id,decision,note)
    def run_monitor_once(self,monitor_id,scenario=None):
        saved=self.db.execute("SELECT scenario FROM monitor_defaults WHERE monitor_id=?",(monitor_id,)).fetchone()
        defaults=json.loads(saved["scenario"]) if saved else {}
        scenario={**defaults,**(scenario or {})}
        required=("cycle_key","window_start","window_end")
        if not isinstance(scenario,dict) or any(not scenario.get(key) for key in required): raise InvestigationError("RH_MONITOR_SCENARIO","cycle_key and explicit window are required")
        facts={key:scenario.get(key) for key in ("cycle_key","window_start","window_end","sources","references","transport_pages")}; fingerprint=hashlib.sha256(json.dumps(facts,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        prior=self.db.execute("SELECT fingerprint FROM monitor_cycle_facts WHERE monitor_id=? AND cycle_key=?",(monitor_id,scenario["cycle_key"])).fetchone()
        if prior and prior["fingerprint"] != fingerprint: raise InvestigationError("RH_MONITOR_CYCLE_CONFLICT","cycle_key facts cannot be changed")
        cycle=self.monitors.begin_cycle(monitor_id,scenario["cycle_key"],scenario["window_start"],scenario["window_end"])
        if cycle["reused"]:
            state=self.monitors.status(monitor_id); prior=next(item for item in state["cycles"] if item["cycle_id"]==cycle["cycle_id"])
            if prior["run_id"]: return {"monitor_id":monitor_id,"run_id":prior["run_id"],"reused":True}
        config=self.monitors.get_configuration(monitor_id)
        self.validate_monitor(config["profile"],config["monitor_spec"],config["runtime"])
        self.db.execute("INSERT OR IGNORE INTO monitor_cycle_facts VALUES (?,?,?)",(monitor_id,scenario["cycle_key"],fingerprint)); self.db.commit()
        spec={"status":"ready","project_id":"monitor-"+monitor_id,"revision":config["profile_revision"],"research_question":config["profile"].get("scope",monitor_id),"report_targets":[{"deliverable_type":"patent_monitor_digest","languages":config["monitor_spec"].get("report_languages",[])}],"references":scenario.get("references",[])}
        run=self.create_investigation(spec,config["runtime"],scenario)["run_id"]
        self.monitors.bind_run(cycle["cycle_id"],run); self.db.execute("INSERT INTO monitor_runs VALUES (?,?,?,?)",(run,monitor_id,cycle["cycle_id"],json.dumps(config["profile"]))); self.db.commit()
        try:self.monitors.reserve_tasks(monitor_id,1)
        except Exception:
            result={"run_id":run,"synthetic":True,"outcome":"partial","conclusion":"Monitor task budget exhausted before planning.","verification":None,"findings":[],"evidence":[],"artifacts":[],"issues":[{"code":"RH_MONITOR_BUDGET","status":"open"}],"coverage":self._coverage(run)}
            self.db.execute("UPDATE investigations SET status='partial',stage='budget_exhausted',result=?,updated=? WHERE id=?",(json.dumps(result),time.time(),run)); self.db.commit()
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
        scenario=json.loads(r["scenario"])
        reference_ids={x.get("document_id") for x in scenario.get("references",[])}
        evidence_ids={x.get("evidence_id") for x in scenario.get("baseline_snapshot",[])}
        self._validate_queries(q,reference_ids,evidence_ids,json.loads(r["runtime"]),scenario)
        runtime=json.loads(r["runtime"])
        if "epo" in runtime.get("sources",{}) and len([item for item in q if item["source"]=="epo"])>3:
            raise InvestigationError("RH_QUERY_BUDGET","P4 allows at most three EPO query versions")
        # Source screen tasks are all-or-partial as one planning checkpoint.
        self._reserve_available(s["run_id"],len(q))
        any_task=False; partial=False
        for item in q:
            role="paper_search" if item["source"] in {"synthetic-paper","openalex"} else "patent_search"
            source=item["source"]; query_id=item.get("query_id") or "q-"+hashlib.sha256((source+item["query"]+str(item.get("parent_query_id",""))).encode()).hexdigest()[:12]
            self.db.execute("INSERT OR IGNORE INTO source_queries VALUES (?,?,?,?,?,?,?,?)",(s["run_id"],query_id,source,item["query"],item.get("parent_query_id"),json.dumps(item.get("input_refs",[])),"pending",None)); self.db.commit()
            self._store_query_details(s["run_id"],{**item,"query_id":query_id})
            if source=="epo":
                detail={key:item.get(key) for key in ("intent","terms_basis","revision_reason","filters") if key in item}
                self.db.execute("INSERT OR IGNORE INTO epo_query_details VALUES (?,?,?)",(s["run_id"],query_id,json.dumps(detail,ensure_ascii=False))); self.db.commit()
            if self._query_is_sensitive(item,r) and not policy_allows({"visibility":"confidential","company_id":runtime.get("data_policy",{}).get("company_id")},runtime,query=True):
                self._set_query(s["run_id"],query_id,"policy_blocked","RH_POLICY_BLOCKED: query egress is not allowed"); partial=True; continue
            candidates, status, reason=self._search_pages(s["run_id"],source,query_id,item["query"],runtime,r)
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
        monitor=self._monitor_context(s["run_id"])
        if monitor:
            selected={item["document_id"] for item in candidates if isinstance(item,dict) and item.get("document_id")} if 'candidates' in locals() else set()
            documents=[]
            for document in self._sources(r):
                if document.get("document_id") in selected and policy_allows(document,runtime):
                    item=dict(document); item["content_sha256"]=hashlib.sha256((str(item.get("text",""))+str(item.get("base64_bytes",""))).encode()).hexdigest(); documents.append(item)
            self.monitors.record_collection(monitor["cycle_id"],documents,not partial,{"source_status":"complete" if not partial else "partial","queries":self._coverage(s["run_id"])["queries"]})
        if not any_task:
            if "reference_rag_evidence_ids" in scenario:
                self._set(s["run_id"],stage="source",status="waiting_revision")
                self._trace(s["run_id"],"source_task","no_candidates",{"revision_available":True})
                return {"run_id":s["run_id"],"next":"end"}
            self._finish_source_partial(s["run_id"], "No authorized candidates are available." if not partial else "Source collection is partial.")
            return {"run_id":s["run_id"],"next":"end"}
        self._set(s["run_id"],stage="source",status="waiting_model"); self._trace(s["run_id"],"planning_gate","planned"); return {"run_id":s["run_id"],"next":"end"}
    def _source(self,s):
        r=self._run(s["run_id"])
        if r["stage"]=="planning" or self._pending(s["run_id"]): return {"run_id":s["run_id"],"next":"end"}
        if r["stage"]!="source":return {"run_id":s["run_id"],"next":"acquire_normalize"}
        if not self._screens(s["run_id"]):
            self._finish_source_partial(s["run_id"],"No screened candidate is available after bounded queries.")
            return {"run_id":s["run_id"],"next":"end"}
        self._set(s["run_id"],stage="acquire_normalize",status="running"); self._trace(s["run_id"],"source_task","screened"); return {"run_id":s["run_id"],"next":"acquire_normalize"}
    def _acquire(self,s):
        r=self._run(s["run_id"])
        if r["stage"]!="acquire_normalize":return {"run_id":s["run_id"],"next":"analysis_task"}
        selected=[]; seen=set()
        for task in self._screens(s["run_id"]):
            for candidate in task["candidates"]:
                document_id=candidate["document_id"]
                if candidate["relevance"] != "irrelevant" and document_id not in seen:
                    selected.append(document_id); seen.add(document_id)
        evidence=[]; acquisition_issues=[]
        runtime=json.loads(r["runtime"])
        if runtime.get("data_mode")=="live":
            acquisition_issues.extend(self._acquire_live_documents(s["run_id"],runtime,selected))
            if "epo" in runtime.get("sources",{}):
                acquisition_issues.extend(self._acquire_epo_documents(s["run_id"],runtime,selected))
        for doc in self._sources(r):
            if doc.get("document_id") not in selected: continue
            if doc.get("source")=="epo" and doc.get("content_type")!="application/xml": continue
            if not policy_allows(doc,runtime):
                self._trace(s["run_id"],"acquire_normalize","blocked",{"waiting_reason":{"code":"RH_POLICY_BLOCKED","scope":"model_payload","detail":"restricted"}}); continue
            try:
                normalized=normalize(doc)
                if doc.get("source")=="epo":
                    for item in normalized:
                        self.db.execute("INSERT OR IGNORE INTO discovery_evidence VALUES (?,?,?,?,?,?,?)",(item["evidence_id"],s["run_id"],item["document_id"],item["version_id"],json.dumps(item),"public",None))
                    continue  # Patent facts enter the analysis snapshot through verified RAG attach.
                evidence.extend(normalized)
            except SourceError as error:
                issue={"code":error.code,"status":"open","document_id":doc.get("document_id"),"version_id":str(doc.get("version","synthetic-v1")),"message":error.message}
                acquisition_issues.append(issue); self._trace(s["run_id"],"acquire_normalize","source_failure",issue)
        for item in evidence:
            doc=next((x for x in self._sources(r) if x.get("document_id")==item["document_id"]),{})
            self.db.execute("INSERT OR IGNORE INTO discovery_evidence VALUES (?,?,?,?,?,?,?)",(item["evidence_id"],s["run_id"],item["document_id"],item["version_id"],json.dumps(item),doc.get("visibility","public"),doc.get("company_id")))
        self.db.commit()
        facts=self._fact_payload(r,evidence)
        self._reserve_available(s["run_id"],2)
        monitor=self._monitor_context(s["run_id"])
        payload={"input_refs":["stage:acquire_normalize"],**facts,"discovery_evidence":evidence,"acquisition_issues":acquisition_issues,"report_targets":json.loads(r["spec"]).get("report_targets",[]),**({"monitor":monitor} if monitor else {})}
        self._task(s["run_id"],"evidence_analysis","extract",payload)
        judge_evidence=[item for item in evidence if not monitor or self._monitor_needs_judgment(monitor,item)]
        if judge_evidence:self._task(s["run_id"],"business_judgment","judge",{**payload,"documents":[{"document_id":e["document_id"],"evidence_id":e["evidence_id"]} for e in judge_evidence]})
        self._set(s["run_id"],stage="analysis",status="waiting_model");self._trace(s["run_id"],"acquire_normalize","normalized",{"evidence_count":len(evidence)});return {"run_id":s["run_id"],"next":"end"}

    def _acquire_live_documents(self,run_id,runtime,selected):
        sources={item.get("document_id"):item for item in self._sources(self._run(run_id)) if item.get("source")=="openalex" and item.get("version") != "openalex-oa-pdf"}
        documents={document_id:sources[document_id] for document_id in selected if document_id in sources}
        pending={row["cursor"] for row in self.db.execute("SELECT cursor FROM source_attempts WHERE run_id=? AND query_id='download-document' AND status='pending'",(run_id,))}
        uncertain=set(documents) & pending
        documents={key:value for key,value in documents.items() if key not in uncertain}
        issues=[{"code":"RH_DOWNLOAD_UNCERTAIN","status":"open","document_id":key,"message":"prior download attempt is unknown and was not resent"} for key in uncertain]
        if not documents:
            return issues
        budget=json.loads(self._run(run_id)["budget"])
        if budget["reserved_downloads"] >= budget["max_downloads"]:
            return [*issues,{"code":"RH_DOWNLOAD_BUDGET","status":"open","message":"download limit exhausted"}]
        service=self
        class CountingSession:
            def __init__(self): self.client=literature.requests.Session(); self.active=None
            def _finish(self,status,result=None,release=True):
                reservation=self.active
                if not reservation:return
                service.db.execute("BEGIN IMMEDIATE")
                try:
                    row=service._run(run_id); current=json.loads(row["budget"])
                    attempt=service.db.execute("SELECT status,result FROM source_attempts WHERE run_id=? AND query_id='download' AND cursor=? AND attempt=?",(run_id,reservation["cursor"],reservation["attempt"])).fetchone()
                    if not attempt or attempt["status"]!="dispatching": service.db.rollback(); return
                    if release:
                        current["reserved_source_bytes"]=max(0,current.get("reserved_source_bytes",0)-reservation["max_bytes"])
                        current["reserved_download_bytes"]=max(0,current.get("reserved_download_bytes",0)-reservation["max_bytes"])
                    safe=json.loads(attempt["result"] or "{}")
                    safe.update(result or {})
                    service.db.execute("UPDATE investigations SET budget=?,updated=? WHERE id=?",(json.dumps(current),time.time(),run_id))
                    service.db.execute("UPDATE source_attempts SET status=?,result=? WHERE run_id=? AND query_id='download' AND cursor=? AND attempt=? AND status='dispatching'",(status,json.dumps(safe),run_id,reservation["cursor"],reservation["attempt"]))
                    service.db.commit()
                    self.active=None
                except Exception:service.db.rollback();raise
            def get(self,url,**kwargs):
                cursor="url-"+hashlib.sha256(str(url).encode()).hexdigest()[:16]
                service.db.execute("BEGIN IMMEDIATE")
                try:
                    run=service._run(run_id); current=json.loads(run["budget"]); limits=json.loads(run["runtime"]).get("budget",{})
                    if run["status"] in {"stopped","completed","partial","failed","policy_blocked","cancelled"}: raise literature.LiteratureError("inactive_run","run is inactive")
                    keys=("max_source_calls","max_source_bytes","max_source_response_bytes","max_download_calls","max_download_bytes")
                    if any(type(current.get(key)) is not int or current[key]<1 for key in keys) or any(current[key]!=limits.get(key,current[key]) for key in keys):
                        raise literature.LiteratureError("source_budget_missing","explicit source and download budgets are required")
                    prior=service.db.execute("SELECT status FROM source_attempts WHERE run_id=? AND query_id='download' AND cursor=? ORDER BY attempt DESC LIMIT 1",(run_id,cursor)).fetchone()
                    if prior and prior["status"] in {"pending","dispatching","outcome_unknown"}: raise literature.LiteratureError("outcome_unknown","prior download request outcome is unknown and cannot be resent")
                    if current.get("reserved_download_calls",0)>=current["max_download_calls"] or current.get("reserved_source_calls",0)>=current["max_source_calls"]:
                        raise literature.LiteratureError("download_call_budget","download/source request budget exhausted")
                    max_bytes=min(current["max_source_response_bytes"],current["max_download_bytes"]-current.get("received_download_bytes",0)-current.get("reserved_download_bytes",0),literature.MAX_FILE_BYTES)
                    if max_bytes<1 or current.get("received_source_bytes",0)+current.get("reserved_source_bytes",0)+max_bytes>current["max_source_bytes"]:
                        raise literature.LiteratureError("byte_budget_exceeded","source/download response bytes cannot be reserved")
                    current["reserved_download_calls"]+=1; current["reserved_source_calls"]+=1
                    current["reserved_download_bytes"]=current.get("reserved_download_bytes",0)+max_bytes
                    current["reserved_source_bytes"]=current.get("reserved_source_bytes",0)+max_bytes
                    number=service.db.execute("SELECT COUNT(*) FROM source_attempts WHERE run_id=? AND query_id='download' AND cursor=?",(run_id,cursor)).fetchone()[0]+1
                    parsed=urlsplit(str(url)); safe_url=f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                    receipt={"kind":"download","method":"GET","url":safe_url,"url_sha256":hashlib.sha256(str(url).encode()).hexdigest(),"header_names":sorted(str(k).lower() for k in kwargs.get("headers",{})),"request_receipt_status":"recorded_before_dispatch"}
                    service.db.execute("UPDATE investigations SET budget=?,updated=? WHERE id=?",(json.dumps(current),time.time(),run_id))
                    service.db.execute("INSERT INTO source_attempts VALUES (?,?,?,?,?,?)",(run_id,"download",cursor,number,"dispatching",json.dumps(receipt))); service.db.commit()
                    self.active={"cursor":cursor,"attempt":number,"max_bytes":max_bytes,"received":0}
                except Exception:service.db.rollback();raise
                try:
                    response=self.client.get(url,**kwargs)
                except Exception:
                    self._finish("outcome_unknown",{"outcome":"unknown"},release=False); raise
                status_code=getattr(response,"status_code",0)
                if not 200<=status_code<300:
                    self._finish("RH_SOURCE_HTTP_"+str(status_code),{"http_status":status_code,"received_bytes":0})
                    return response
                owner=self
                class MeteredResponse:
                    def __init__(self,response):self._response=response;self.status_code=response.status_code;self.headers=response.headers
                    def iter_content(self,chunk_size=65536):
                        try:
                            for chunk in self._response.iter_content(chunk_size=chunk_size):
                                if not chunk:continue
                                yield chunk
                            owner._finish("success",{"http_status":status_code,"received_bytes":owner.active.get("received",0),"request_receipt_status":"recorded"})
                        except Exception:
                            owner._finish("outcome_unknown",{"outcome":"unknown"},release=False);raise
                    def close(self):return self._response.close()
                return MeteredResponse(response)
            def note_received(self,count):
                reservation=self.active
                if not reservation:return
                service.db.execute("BEGIN IMMEDIATE")
                try:
                    row=service._run(run_id); current=json.loads(row["budget"])
                    current["received_source_bytes"]=current.get("received_source_bytes",0)+count
                    current["received_download_bytes"]=current.get("received_download_bytes",0)+count
                    reservation["received"]+=count
                    over=(reservation["received"]>reservation["max_bytes"] or current["received_source_bytes"]+current.get("reserved_source_bytes",0)-reservation["max_bytes"]+reservation["received"]>current["max_source_bytes"] or current["received_download_bytes"]+current.get("reserved_download_bytes",0)-reservation["max_bytes"]+reservation["received"]>current["max_download_bytes"])
                    service.db.execute("UPDATE investigations SET budget=?,updated=? WHERE id=?",(json.dumps(current),time.time(),run_id)); service.db.commit()
                except Exception:service.db.rollback();raise
                if over:
                    self._finish("RH_SOURCE_BYTE_BUDGET",{"received_bytes":reservation["received"]})
                    raise literature.LiteratureError("byte_budget_exceeded","download response exceeded reserved bytes")
        def reserve_document(record):
            current=json.loads(self._run(run_id)["budget"]); document_id=record.get("source_id")
            if current["reserved_downloads"] >= current["max_downloads"]: raise literature.LiteratureError("download_budget", "download limit exhausted")
            current["reserved_downloads"]+=1
            number=self.db.execute("SELECT COUNT(*) FROM source_attempts WHERE run_id=? AND query_id='download-document' AND cursor=?",(run_id,document_id)).fetchone()[0]+1
            self.db.execute("UPDATE investigations SET budget=?,updated=? WHERE id=?",(json.dumps(current),time.time(),run_id))
            self.db.execute("INSERT INTO source_attempts VALUES (?,?,?,?,?,?)",(run_id,"download-document",document_id,number,"pending",json.dumps({"kind":"download-document"}))); self.db.commit()
        session=CountingSession()
        def received(count): session.note_received(count)
        output=self.root/"downloads"/run_id
        records=list(documents.values())
        if "reference_rag_evidence_ids" in json.loads(self._run(run_id)["scenario"]):
            records=[{**record,"locations":sorted(record.get("locations",[]),key=lambda location: 0 if isinstance(location,dict) and location.get("is_oa") and isinstance(location.get("pdf_url"),str) and location["pdf_url"].strip() else 1)} for record in records]
        try:
            catalog=literature.download({"records":records},output,limit=min(budget["max_downloads"]-budget["reserved_downloads"],len(documents)),session=session,max_total_bytes=budget["max_download_bytes"]-budget["received_download_bytes"],on_record_start=reserve_document,on_received=received)
        except literature.LiteratureError as error:
            return [*issues,{"code":"RH_DOWNLOAD_"+error.code.upper(),"status":"open","message":"open-access full text is unavailable"}]
        for outcome in catalog["records"]:
            record=outcome["record"]; document=documents.get(record.get("source_id")); download=outcome["download"]
            if not document: continue
            final="success" if download.get("status")=="success" else "RH_DOWNLOAD_"+str(download.get("error",download.get("status","failed"))).upper()
            self.db.execute("UPDATE source_attempts SET status=?,result=? WHERE run_id=? AND query_id='download-document' AND cursor=? AND status='pending'",(final,json.dumps(download),run_id,record.get("source_id")))
            if download.get("status")=="success" and isinstance(download.get("path"),str):
                path=(output/download["path"]).resolve()
                try:
                    document={**document,"version":"openalex-oa-pdf","content_type":"application/pdf","base64_bytes":base64.b64encode(path.read_bytes()).decode("ascii")}
                    self.db.execute("INSERT OR REPLACE INTO discovery_documents VALUES (?,?,?)",(run_id,document["document_id"],json.dumps(document)))
                except OSError:
                    issues.append({"code":"RH_DOWNLOAD_LOCAL","status":"open","document_id":record.get("source_id"),"message":"downloaded body could not be read"})
            else:
                issues.append({"code":"RH_FULLTEXT_GAP","status":"open","document_id":record.get("source_id"),"message":"only metadata or abstract is available","detail":download.get("error",download.get("status"))})
        self.db.commit()
        if catalog["outcome"]!="completed": issues.append({"code":"RH_DOWNLOAD_PARTIAL","status":"open","message":"open-access acquisition is partial"})
        return issues

    def _epo_client(self,run_id):
        if run_id not in self._epo_clients:
            self._epo_clients[run_id]=EpoClient(lambda operation,method,url,**kw:self._epo_request(run_id,operation,method,url,**kw))
        return self._epo_clients[run_id]

    def _epo_request(self,run_id,operation,method,url,**kwargs):
        auth_sequence=(self.db.execute("SELECT COUNT(*) FROM source_attempts WHERE run_id=? AND query_id='epo-http' AND cursor LIKE 'auth:%'",(run_id,)).fetchone()[0]+1) if operation=="auth" else None
        request_key=hashlib.sha256(json.dumps([operation,url,kwargs.get("params"),kwargs.get("headers",{}).get("X-OPS-Range"),auth_sequence],sort_keys=True).encode()).hexdigest()[:20]
        cursor=operation+":"+request_key
        prior=self.db.execute("SELECT status,result FROM source_attempts WHERE run_id=? AND query_id='epo-http' AND cursor=? ORDER BY attempt DESC LIMIT 1",(run_id,cursor)).fetchone()
        if prior:
            if prior["status"] in {"pending","dispatching","outcome_unknown","RH_SOURCE_TIMEOUT","RH_SOURCE_NETWORK_ERROR"}:
                raise SourceError("RH_SOURCE_UNCERTAIN","prior OPS request outcome is uncertain and was not resent")
            if prior["status"]=="success":
                path=self.root/"epo"/run_id/(cursor.replace(":","-")+".xml")
                if not path.is_file(): raise SourceError("RH_SOURCE_UNCERTAIN","saved OPS response is missing")
                data=path.read_bytes()
                if hashlib.sha256(data).hexdigest()!=json.loads(prior["result"]).get("sha256"):
                    raise SourceError("RH_SOURCE_UNCERTAIN","saved OPS response changed")
                return data
        run=self._run(run_id); runtime=json.loads(run["runtime"]); budget=json.loads(run["budget"])
        if run["status"] in {"stopped","completed","partial","failed","policy_blocked","cancelled"}:
            raise SourceError("RH_SOURCE_INACTIVE","OPS dispatch requires an active run")
        if any(type(budget.get(key)) is not int or budget[key] < 1 for key in ("max_source_calls","max_source_bytes","max_source_response_bytes")):
            raise SourceError("RH_SOURCE_BUDGET","OPS source call and byte budgets must be explicit and positive")
        epo_limit=json.loads(self._run(run_id)["scenario"]).get("source_call_limits",{}).get("epo")
        if epo_limit is not None and self.db.execute("SELECT COUNT(*) FROM source_attempts WHERE run_id=? AND query_id='epo-http'",(run_id,)).fetchone()[0]>=epo_limit:
            raise SourceError("RH_SOURCE_BUDGET","OPS request limit exhausted")
        if budget["reserved_source_calls"]>=budget["max_source_calls"]:
            raise SourceError("RH_SOURCE_BUDGET","OPS request budget exhausted")
        if operation=="auth":
            used=self.db.execute("SELECT COUNT(*) FROM source_attempts WHERE run_id=? AND query_id='epo-http' AND cursor LIKE 'auth:%'",(run_id,)).fetchone()[0]
            if used>=2: raise SourceError("RH_SOURCE_BUDGET","OPS authentication budget exhausted")
        attempt=self.db.execute("SELECT COUNT(*) FROM source_attempts WHERE run_id=? AND query_id='epo-http' AND cursor=?",(run_id,cursor)).fetchone()[0]+1
        if budget.get("received_source_bytes",0)+budget.get("reserved_source_bytes",0)+budget["max_source_response_bytes"]>budget["max_source_bytes"]:
            raise SourceError("RH_SOURCE_BUDGET","OPS response-byte reservation would exceed the run budget")
        safe={"operation":operation,"method":method,"path":url.split("ops.epo.org",1)[-1].split("?",1)[0],"params_sha256":hashlib.sha256(json.dumps(kwargs.get("params",{}),sort_keys=True).encode()).hexdigest(),"range":kwargs.get("headers",{}).get("X-OPS-Range"),"started_utc":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),"request_receipt_status":"prepared"}
        if operation=="search":
            match=self.db.execute("SELECT query_id FROM source_queries WHERE run_id=? AND source='epo' AND query=? ORDER BY rowid LIMIT 1",(run_id,(kwargs.get("params") or {}).get("q"))).fetchone()
            safe["query_id"]=match["query_id"] if match else None
        self.db.execute("BEGIN IMMEDIATE")
        try:
            live=self._run(run_id)
            if live["status"] in {"stopped","completed","partial","failed","policy_blocked","cancelled"} or self.db.execute("SELECT 1 FROM source_attempts WHERE run_id=? AND query_id='epo-http' AND status IN ('pending','dispatching','outcome_unknown') LIMIT 1",(run_id,)).fetchone():
                raise SourceError("RH_SOURCE_INACTIVE","run changed or another source request is unresolved")
            budget=json.loads(live["budget"])
            if budget.get("reserved_source_calls",0)>=budget["max_source_calls"] or budget.get("received_source_bytes",0)+budget.get("reserved_source_bytes",0)+budget["max_source_response_bytes"]>budget["max_source_bytes"]:
                raise SourceError("RH_SOURCE_BUDGET","OPS request or response-byte budget is exhausted")
            if operation=="auth" and self.db.execute("SELECT COUNT(*) FROM source_attempts WHERE run_id=? AND query_id='epo-http' AND cursor LIKE 'auth:%'",(run_id,)).fetchone()[0]>=2:
                raise SourceError("RH_SOURCE_BUDGET","OPS authentication budget exhausted")
            attempt=self.db.execute("SELECT COUNT(*) FROM source_attempts WHERE run_id=? AND query_id='epo-http' AND cursor=?",(run_id,cursor)).fetchone()[0]+1
            budget["reserved_source_calls"]+=1; budget["reserved_source_bytes"]=budget.get("reserved_source_bytes",0)+budget["max_source_response_bytes"]
            self.db.execute("UPDATE investigations SET budget=?,updated=? WHERE id=?",(json.dumps(budget),time.time(),run_id))
            self.db.execute("INSERT INTO source_attempts VALUES (?,?,?,?,?,?)",(run_id,"epo-http",cursor,attempt,"dispatching",json.dumps(safe,ensure_ascii=False)))
            self.db.commit()
        except Exception:
            self.db.rollback(); raise
        status="RH_SOURCE_NETWORK_ERROR"; data=bytearray(); http_status=None; response_complete=False
        try:
            request_kwargs={key:value for key,value in kwargs.items() if key not in {"allow_redirects"}}
            with requests.request(method,url,timeout=30,stream=True,allow_redirects=False,**request_kwargs) as response:
                http_status=response.status_code
                for chunk in response.iter_content(65536):
                    data.extend(chunk)
                    if len(data)>budget["max_source_response_bytes"] or budget["received_source_bytes"]+len(data)>budget["max_source_bytes"]:
                        status="RH_SOURCE_BYTE_BUDGET"; raise SourceError(status,"OPS response exceeds byte budget")
                response_complete=True
                status="success" if 200<=http_status<300 else {401:"RH_SOURCE_AUTHENTICATION",403:"RH_SOURCE_AUTHORIZATION",404:"RH_SOURCE_NOT_FOUND",429:"RH_SOURCE_RATE_LIMIT"}.get(http_status,"RH_SOURCE_HTTP_"+str(http_status))
        except SourceError:
            raise
        except requests.Timeout as exc:
            status="outcome_unknown"; raise SourceError("RH_SOURCE_TIMEOUT","OPS request timed out; outcome is unknown and will not be resent") from exc
        except requests.RequestException as exc:
            status="outcome_unknown"; raise SourceError("RH_SOURCE_NETWORK_ERROR","OPS request failed; outcome is unknown and will not be resent") from exc
        except Exception as exc:
            status="outcome_unknown"; raise SourceError("RH_SOURCE_OUTCOME_UNKNOWN","OPS transport failed; outcome is unknown and will not be resent") from exc
        finally:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                live=self._run(run_id)
                current=self.db.execute("SELECT status FROM source_attempts WHERE run_id=? AND query_id='epo-http' AND cursor=? AND attempt=?",(run_id,cursor,attempt)).fetchone()
                if (live["status"] in {"stopped","completed","partial","failed","policy_blocked","cancelled"} or not current or current["status"]!="dispatching") and status=="success":
                    status="outcome_unknown"; safe["late_response_ignored"]=True
                budget=json.loads(live["budget"])
                if response_complete: budget["reserved_source_bytes"]=max(0,budget.get("reserved_source_bytes",0)-budget["max_source_response_bytes"])
                budget["received_source_bytes"]+=len(data)
                safe.update({"http_status":http_status,"received_bytes":len(data),"finished_utc":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),"request_receipt_status":"recorded"})
                if status=="success" and operation!="auth":
                    raw_dir=self.root/"epo"/run_id; raw_dir.mkdir(parents=True,exist_ok=True)
                    raw=raw_dir/(cursor.replace(":","-")+".xml"); raw.write_bytes(data)
                    safe["raw_xml_path"]=str(raw.relative_to(self.root)).replace("\\","/")
                    safe["sha256"]=hashlib.sha256(data).hexdigest()
                self.db.execute("UPDATE investigations SET budget=?,updated=? WHERE id=?",(json.dumps(budget),time.time(),run_id))
                self.db.execute("UPDATE source_attempts SET status=?,result=? WHERE run_id=? AND query_id='epo-http' AND cursor=? AND attempt=? AND status='dispatching'",(status,json.dumps(safe,ensure_ascii=False),run_id,cursor,attempt))
                self.db.commit()
            except Exception:
                self.db.rollback(); raise
        if status!="success": raise SourceError(status,"OPS returned "+str(http_status))
        return bytes(data)

    def _search_epo_pages(self,run_id,query_id,query,runtime):
        config=runtime["sources"]["epo"]; page_size=int(config.get("page_size",5)); max_pages=min(int(config.get("max_pages",2)),int(runtime["budget"]["max_pages_per_query"])); limit=int(config.get("max_candidates",20))
        found=[]; seen=set(); start=1; client=self._epo_client(run_id)
        while len(seen)<max_pages and len(found)<limit:
            cursor=str(start)
            if cursor in seen: return found,"partial","cursor loop"
            cached=self.db.execute("SELECT result FROM source_attempts WHERE run_id=? AND query_id=? AND cursor=? AND status='success'",(run_id,query_id,cursor)).fetchone()
            if cached: page=json.loads(cached["result"])
            else:
                if self.db.execute("SELECT 1 FROM source_attempts WHERE run_id=? AND query_id=? AND cursor=? AND status IN ('pending','dispatching','outcome_unknown')",(run_id,query_id,cursor)).fetchone():
                    return found,"partial","uncertain prior search page"
                self.db.execute("INSERT INTO source_attempts VALUES (?,?,?,?,?,?)",(run_id,query_id,cursor,1,"pending",json.dumps({"kind":"epo-search-page"}))); self.db.commit()
                try: page,_=client.search(query,start,page_size)
                except SourceError as error:
                    self.db.execute("UPDATE source_attempts SET status=? WHERE run_id=? AND query_id=? AND cursor=?",(error.code,run_id,query_id,cursor)); self.db.commit()
                    return found,"partial",error.code
                self.db.execute("UPDATE source_attempts SET status='success',result=? WHERE run_id=? AND query_id=? AND cursor=?",(json.dumps(page),run_id,query_id,cursor)); self.db.commit()
            seen.add(cursor)
            already={x[0] for x in self.db.execute("SELECT document_id FROM discovery_documents WHERE run_id=?",(run_id,))}
            for document in page["candidates"]:
                if len(found)>=limit or len(already)>=20 and document["document_id"] not in already: break
                self.db.execute("INSERT OR REPLACE INTO discovery_documents VALUES (?,?,?)",(run_id,document["document_id"],json.dumps(document)))
                found.append(document)
                already.add(document["document_id"])
            self.db.commit()
            if page["next_cursor"] is None: return found,"complete",None
            if len(already)>=20: return found,"partial","P4 unique candidate limit"
            start=int(page["next_cursor"])
        return found,"partial","page or candidate limit"

    def _acquire_epo_documents(self,run_id,runtime,selected):
        available={x["document_id"]:x for x in self._sources(self._run(run_id)) if x.get("source")=="epo"}
        ranked=[available[x] for x in selected if x in available]
        issues=[]; client=self._epo_client(run_id)
        if not ranked: return issues
        viable=[]
        for candidate in ranked[:3]:
            try:
                inquiry,_=client.availability(candidate)
            except SourceError as error:
                if error.code in {"RH_SOURCE_AUTHENTICATION","RH_SOURCE_AUTHORIZATION","RH_SOURCE_RATE_LIMIT","RH_SOURCE_BUDGET"}:
                    return [{"code":error.code,"status":"open","document_id":candidate["publication_id"],"section":"fulltext"}]
                continue
            if inquiry["sections"]:
                viable.append((candidate,inquiry))
                if len(inquiry["sections"])==2: break
        if not viable:
            return [{"code":"RH_FULLTEXT_GAP","status":"open","message":"no selected publication has verifiable OPS XML fulltext"}]
        anchor,availability=next(((candidate,inquiry) for candidate,inquiry in viable if len(inquiry["sections"])==2),viable[0])
        try:
            family,_=client.family(anchor)
        except SourceError as error:
            return [{"code":error.code,"status":"open","document_id":anchor["publication_id"],"section":"family"}]
        family_ids={x["publication_id"] for x in family["members"]}
        family_ids.add(anchor["publication_id"])
        chosen=[anchor,*[x for x in ranked[1:] if x["publication_id"] in family_ids][:1]]
        family_id=anchor["publication_id"]
        if family["truncated"]: issues.append({"code":"RH_FAMILY_TRUNCATED","status":"open","document_id":family_id})
        for document in chosen:
            publication=document["publication_id"]
            parts=[]; raw_paths=[]
            for section in ("claims","description"):
                if document is anchor and section not in availability["sections"]:
                    issues.append({"code":"RH_FULLTEXT_GAP","status":"open","document_id":publication,"section":section}); continue
                try:
                    fragments,body=client.section(document,section)
                    parts.extend(fragments)
                    digest=hashlib.sha256(body).hexdigest()
                    saved=next((json.loads(row["result"]) for row in self.db.execute("SELECT result FROM source_attempts WHERE run_id=? AND query_id='epo-http' AND status='success' ORDER BY rowid DESC",(run_id,)) if json.loads(row["result"]).get("sha256")==digest),{})
                    raw_paths.append({"section":section,"sha256":digest,"raw_xml_path":saved.get("raw_xml_path")})
                    if any(part.get("table_gap") for part in fragments):
                        issues.append({"code":"RH_XML_TABLE_GAP","status":"open","document_id":publication,"section":section})
                except SourceError as error:
                    issues.append({"code":error.code,"status":"open","document_id":publication,"section":section})
            if parts:
                wrapper=ElementTree.Element("epo-evidence",publication=publication)
                for part in parts:
                    node=ElementTree.SubElement(wrapper,"claim" if part["section"]=="claims" else "p",id=part["locator"]["value"])
                    node.text=part["text"]
                xml=ElementTree.tostring(wrapper,encoding="unicode")
                full={**document,"family_source":"inpadoc_extended","family_anchor":family_id,"family_members":sorted(family_ids),"fulltext_availability":availability if document is anchor else None,"content_type":"application/xml","text":xml,"epo_sections":parts,"source_xml":raw_paths,"example_partition_status":"explicit" if any(part["section"]=="example" for part in parts) else "unverified","content_sha256":hashlib.sha256(xml.encode()).hexdigest()}
                self.db.execute("INSERT OR REPLACE INTO discovery_documents VALUES (?,?,?)",(run_id,publication,json.dumps(full,ensure_ascii=False))); self.db.commit()
        return issues

    def recover_epo_xml(self,run_id,publication_id):
        """Repair an unsubmitted analysis snapshot from already saved OPS XML only."""
        run=self._run(run_id)
        task=self.db.execute("SELECT id,payload FROM model_tasks WHERE run_id=? AND role='evidence_analysis' AND task_type='extract' AND status='pending'",(run_id,)).fetchone()
        if run["stage"]!="analysis" or not task:
            raise InvestigationError("RH_FACT_SNAPSHOT","saved XML can only be restored before analysis submission")
        row=self.db.execute("SELECT payload FROM discovery_documents WHERE run_id=? AND document_id=?",(run_id,publication_id)).fetchone()
        if not row: raise InvestigationError("RH_FACT_IDENTITY","publication is not in the source results")
        document=json.loads(row["payload"])
        if document.get("source")!="epo": raise InvestigationError("RH_FACT_IDENTITY","source is not OPS")
        if document.get("content_type")=="application/xml":
            return {"status":"reused","publication_id":publication_id,"paragraphs":len(document.get("epo_sections",[]))}
        stored={}
        raw_root=(self.root/"epo"/run_id).resolve()
        epodoc=document["country"]+document["publication_number"]+"."+document["kind"]
        docdb=document["country"]+"."+document["publication_number"]+"."+document["kind"]
        for record in self.db.execute("SELECT result FROM source_attempts WHERE run_id=? AND query_id='epo-http' AND status='success' ORDER BY rowid",(run_id,)):
            meta=json.loads(record["result"])
            if meta.get("operation") not in {"fulltext","family","claims","description"} or not (epodoc in meta.get("path","") or docdb in meta.get("path","")):
                continue
            relative=meta.get("raw_xml_path")
            if not relative: continue
            path=(self.root/relative).resolve()
            if raw_root not in path.parents or not path.is_file(): raise InvestigationError("RH_SOURCE_UNCERTAIN","saved OPS XML is unavailable")
            body=path.read_bytes()
            if hashlib.sha256(body).hexdigest()!=meta.get("sha256"): raise InvestigationError("RH_SOURCE_UNCERTAIN","saved OPS XML changed")
            stored[meta["operation"]]=(body,relative,meta["sha256"])
        if not all(name in stored for name in ("fulltext","family","claims","description")):
            raise InvestigationError("RH_SOURCE_UNCERTAIN","saved OPS XML is incomplete")
        availability=parse_availability(stored["fulltext"][0],document)
        family=parse_family(stored["family"][0])
        parts=[]; raw_paths=[]; issues=[]
        for section in ("claims","description"):
            if section not in availability["sections"]: raise InvestigationError("RH_FULLTEXT_GAP","saved OPS inquiry omits a required section")
            body,relative,digest=stored[section]
            fragments=parse_section(body,section,publication_id)
            parts.extend(fragments); raw_paths.append({"section":section,"sha256":digest,"raw_xml_path":relative})
            if any(part.get("table_gap") for part in fragments): issues.append({"code":"RH_XML_TABLE_GAP","status":"open","document_id":publication_id,"section":section})
        wrapper=ElementTree.Element("epo-evidence",publication=publication_id)
        for part in parts:
            node=ElementTree.SubElement(wrapper,"claim" if part["section"]=="claims" else "p",id=part["locator"]["value"])
            node.text=part["text"]
        xml=ElementTree.tostring(wrapper,encoding="unicode")
        full={**document,"family_source":"inpadoc_extended","family_anchor":publication_id,"family_members":sorted({x["publication_id"] for x in family["members"]}|{publication_id}),"fulltext_availability":availability,"content_type":"application/xml","text":xml,"epo_sections":parts,"source_xml":raw_paths,"example_partition_status":"explicit" if any(part["section"]=="example" for part in parts) else "unverified","content_sha256":hashlib.sha256(xml.encode()).hexdigest()}
        self.db.execute("UPDATE discovery_documents SET payload=? WHERE run_id=? AND document_id=?",(json.dumps(full,ensure_ascii=False),run_id,publication_id))
        for item in normalize(full):
            self.db.execute("INSERT OR IGNORE INTO discovery_evidence VALUES (?,?,?,?,?,?,?)",(item["evidence_id"],run_id,item["document_id"],item["version_id"],json.dumps(item,ensure_ascii=False),"public",None))
        payload=json.loads(task["payload"])
        payload["acquisition_issues"]=[x for x in payload.get("acquisition_issues",[]) if not (x.get("document_id")==publication_id and x.get("code")=="RH_SOURCE_VERSION_UNVERIFIED")]+issues
        self.db.execute("UPDATE model_tasks SET payload=?,task_version=task_version+1 WHERE id=?",(json.dumps(payload,ensure_ascii=False),task["id"]))
        self.db.commit()
        self._trace(run_id,"acquire_normalize","saved_xml_recovered",{"publication_id":publication_id,"paragraphs":len(parts)})
        return {"status":"recovered","publication_id":publication_id,"paragraphs":len(parts),"languages":sorted({x["language"] for x in parts if x.get("language")}),"issues":issues}
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
            self._task(s["run_id"],"writing","write",{"input_refs":["task:synthesis"],"claims":synthesis,"findings":self._done(s["run_id"],"evidence_analysis","extract")[0]["findings"],"evidence":extract_payload["evidence"],"spec":json.loads(r["spec"]),"monitor_snapshot":self._monitor_snapshot(s["run_id"]),"report_targets":json.loads(r["spec"]).get("report_targets",[])});return {"run_id":s["run_id"],"next":"end"}
        if not self._done(s["run_id"],"verification","verify"):
            self._task(s["run_id"],"verification","verify",{"input_refs":["task:writing"],"sections":self._done(s["run_id"],"writing","write")[0]["sections"],"claims":synthesis,"findings":self._done(s["run_id"],"evidence_analysis","extract")[0]["findings"],"evidence":extract_payload["evidence"],"spec":json.loads(r["spec"]),"monitor_snapshot":self._monitor_snapshot(s["run_id"])});return {"run_id":s["run_id"],"next":"end"}
        v=self._done(s["run_id"],"verification","verify")[0]["verification"]; coverage=self._coverage(s["run_id"]); findings=self._done(s["run_id"],"evidence_analysis","extract")[0]["findings"]; evidence=extract_payload["evidence"]
        from .investigation_report_data import build_report_data
        bibliography=extract_payload.get("bibliography",[self._bibliography(doc) for doc in self._sources(r) if any(x["document_id"]==doc.get("document_id") for x in evidence)])
        acquisition_issues=extract_payload.get("acquisition_issues",[])
        try:
            report_spec={**json.loads(r["spec"]),"runtime":json.loads(r["runtime"])}
            report=build_report_data(s["run_id"],report_spec,evidence,findings,synthesis,self._done(s["run_id"],"writing","write")[0]["sections"],v,bibliography,coverage,acquisition_issues,"run-"+s["run_id"]); report["baseline_evidence"]=extract_payload.get("baseline_evidence",[])
            report["monitor"]=self._monitor_snapshot(s["run_id"])
        except Exception as error:
            report={"synthetic":self._synthetic_run(s["run_id"]),"run_id":s["run_id"],"report_version":"run-"+s["run_id"],"research_question":json.loads(r["spec"])["research_question"],"report_targets":json.loads(r["spec"]).get("report_targets",[]),"findings":findings,"evidence":evidence,"claims":[],"sections":[],"bibliography":bibliography,"coverage":coverage,"issues":[*acquisition_issues,{"code":"RH_REPORT_DATA","message":str(error)}]}
        self.db.execute("INSERT OR REPLACE INTO frozen_reports VALUES (?,?,?)",(s["run_id"],json.dumps(report),time.time())); self.db.commit()
        legacy=any("claim_id" not in claim for claim in synthesis) or any("body" not in section or "claim_ids" not in section for section in self._done(s["run_id"],"writing","write")[0]["sections"])
        outcome="completed" if v["status"]=="supported" and coverage["complete"] and (legacy or not report.get("issues")) else "partial"; result={"run_id":s["run_id"],"synthetic":self._synthetic_run(s["run_id"]),"outcome":outcome,"conclusion":v["conclusion"],"verification":v,"findings":findings,"evidence":evidence,"baseline_evidence":extract_payload.get("baseline_evidence",[]),"artifacts":[],"coverage":coverage,"monitor":self._monitor_snapshot(s["run_id"]),"issues":report.get("issues",[])}
        self.db.execute("UPDATE investigations SET stage='completed',status=?,result=?,updated=? WHERE id=?",(outcome,json.dumps(result),time.time(),s["run_id"]));self.db.commit();self._trace(s["run_id"],"verification_gate",v["status"]);return {"run_id":s["run_id"],"next":"end"}

    def _task(self,run,role,typ,payload):
        b=json.loads(self._run(run)["budget"])
        if b["reserved_tasks"]>=b["max_tasks"]:raise InvestigationError("RH_MODEL_BUDGET","model task budget exhausted")
        monitor=self._monitor_context(run)
        if monitor:
            try:self.monitors.reserve_tasks(monitor["monitor_id"],1)
            except Exception as error: raise InvestigationError("RH_MONITOR_BUDGET","monitor task budget exhausted") from error
        run_row=self._run(run); runtime=json.loads(run_row["runtime"])
        operations=["submit_structured_result"]
        if self._source_task_allowed(run_row,role,typ,runtime):
            operations.append("execute_patent_source")
        p={"input_refs":payload.get("input_refs",[]),"allowed_operations":operations,**payload}; self.db.execute("INSERT INTO model_tasks VALUES (?,?,?,?,?,?,?,?,?,?,?)",("task-"+uuid.uuid4().hex[:12],run,1,role,typ,json.dumps(p),json.dumps(get_task_schema(role)),"pending",None,None,time.time()));b["reserved_tasks"]+=1;self.db.execute("UPDATE investigations SET budget=?,updated=? WHERE id=?",(json.dumps(b),time.time(),run));self.db.commit()
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
    def _monitor_snapshot(self,run):
        monitor=self._monitor_context(run)
        if not monitor:return None
        state=self.monitors.status(monitor["monitor_id"]); cycle=next(item for item in state["cycles"] if item["cycle_id"]==monitor["cycle_id"])
        return {"monitor_id":monitor["monitor_id"],"profile":monitor["profile"],"cycle":cycle,"review_issues":self.reviews.review_list(monitor["monitor_id"])}
    def _record_monitor_judgments(self,row,result):
        payload=json.loads(row["payload"]); monitor=payload.get("monitor")
        if not monitor:return
        evidence={item["document_id"]:item for item in payload["evidence"]}
        for judgment in result["judgments"]:
            item=evidence[judgment["document_id"]]
            saved=self.reviews.record_judgment(monitor["monitor_id"],monitor["profile"]["company_id"],item["document_id"],item["version_id"],monitor["profile"]["rule_version"],judgment,[item["evidence_id"]])
            self.monitors.mark_judged(monitor["cycle_id"],item["document_id"],item["version_id"],saved["issue_id"])
    def _validate_queries(self,queries,reference_ids=None,evidence_ids=None,runtime=None,scenario=None):
        errors=list(Draft202012Validator(get_task_schema("planning")).iter_errors({"search_plan":{"queries":queries}}))
        if errors: raise InvestigationError("RH_QUERY_IDENTITY","query plan failed schema validation")
        ids=[]
        for item in queries:
            allowed={"synthetic-paper","synthetic-patent","openalex","epo"} if runtime is None else {"synthetic-paper","synthetic-patent"} if runtime.get("data_mode")=="synthetic" else set(runtime.get("sources",{}))
            if item["source"] not in allowed: raise InvestigationError("RH_QUERY_IDENTITY","query source is unavailable for this runtime")
            ids.append(item["query_id"])
        if len(ids)!=len(set(ids)): raise InvestigationError("RH_QUERY_IDENTITY","query_id must be unique within a run")
        known=set(ids)
        sources_by_id={item["query_id"]:item["source"] for item in queries}
        rag_ids=set((scenario or {}).get("reference_rag_evidence_ids",[]))
        evidence_lookup={x["evidence_id"]:x for x in (scenario or {}).get("baseline_snapshot",[]) if isinstance(x,dict) and x.get("evidence_id")}
        for item in queries:
            parent=item["parent_query_id"]
            if runtime is not None and runtime.get("data_mode")=="live" and not item.get("input_refs"):
                raise InvestigationError("RH_QUERY_REFERENCE","live source queries require explicit frozen input references")
            if parent is not None and (parent not in known or parent==item["query_id"] or sources_by_id[parent]!=item["source"]): raise InvestigationError("RH_QUERY_REFERENCE","parent_query_id must name a different query from the same source")
            if scenario and "reference_rag_evidence_ids" in scenario and parent is not None and not item.get("revision_reason"):
                raise InvestigationError("RH_QUERY_REFERENCE","query revision needs a reason")
            for ref in item["input_refs"]:
                if not isinstance(ref,str): raise InvestigationError("RH_QUERY_REFERENCE","input_refs must be strings")
                if reference_ids is None or evidence_ids is None: continue
                if ref.startswith("baseline:") and ref[9:] not in reference_ids: raise InvestigationError("RH_QUERY_REFERENCE","input_refs names an unknown baseline")
                if ref.startswith("query:") and (ref[6:] not in known or sources_by_id.get(ref[6:])!=item["source"]): raise InvestigationError("RH_QUERY_REFERENCE","input_refs must name a known query from the same source")
                if not (ref in evidence_ids or ref.startswith("baseline:") or ref.startswith("query:")): raise InvestigationError("RH_QUERY_REFERENCE","input_refs must name actual baseline evidence or query")
            if item["source"] in {"openalex","epo"}:
                terms=self._query_terms(item["source"],item["query"])
                if not terms: raise InvestigationError("RH_QUERY_SYNTAX","source query syntax is invalid")
                if scenario and "reference_rag_evidence_ids" in scenario:
                    cited=set(item["input_refs"]) & rag_ids
                    if not cited:
                        if not item.get("evidence_gap"):
                            raise InvestigationError("RH_QUERY_EVIDENCE","query without RAG evidence needs an explicit evidence gap")
                        continue
                    bindings=item.get("term_evidence",[])
                    if not isinstance(bindings,list): raise InvestigationError("RH_QUERY_EVIDENCE","term_evidence must be a list")
                    for term in terms:
                        matched=any(isinstance(binding,dict) and binding.get("evidence_ref") in cited and self._literal(binding.get("term",""))==self._literal(term) and self._literal(term) in self._literal(evidence_lookup[binding["evidence_ref"]].get("text","")) for binding in bindings)
                        if not matched: raise InvestigationError("RH_QUERY_EVIDENCE","query term has no literal support in cited RAG evidence")
    @staticmethod
    def _literal(value):
        return " ".join(re.findall(r"\w+",str(value).casefold(),flags=re.UNICODE))
    @classmethod
    def _query_terms(cls,source,query):
        if not isinstance(query,str) or not query.strip() or len(query)>500:
            return []
        if source=="openalex":
            if re.search(r"[=<>]|\b(?:and|or|not)\b",query,re.I): return []
            return [value for value in re.findall(r"\w+",query,flags=re.UNICODE) if len(value)>1]
        if source=="epo":
            parts=re.split(r"\s+(?:and|or)\s+",query.strip(),flags=re.I)
            if not all(re.fullmatch(r'(?:ta|ti|ab|cl|pa|in|pn)=(?:"[^"\r\n]+"|[\w*-]+)',part,re.I) for part in parts): return []
            return [part.split("=",1)[1].strip('"') for part in parts]
        return [query]
    def _reserve_available(self,run,count):
        b=json.loads(self._run(run)["budget"])
        if b["reserved_tasks"]+count>b["max_tasks"]:raise InvestigationError("RH_MODEL_BUDGET","model task budget exhausted")
    def _refs(self,row,result):
        p=json.loads(row["payload"]); role=row["role"]
        if role == "planning":
            queries=result["search_plan"]["queries"]
            run=self._run(row["run_id"]); references=json.loads(run["scenario"]).get("references",[]); docs={x.get("document_id") for x in references}; evidence={x.get("evidence_id") for x in json.loads(run["scenario"]).get("baseline_snapshot",[])}
            self._validate_queries(queries,docs,evidence,json.loads(run["runtime"]),json.loads(run["scenario"]))
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
            for claim in result["claims"]: self._check_claim(claim,evidence,require_parse_revision=True)
        elif role=="verification":
            claims=self._done(row["run_id"],"synthesis","synthesize")[0]["claims"]
            if any(i>=len(claims) for i in result["verification"]["supported_claim_refs"]):raise InvestigationError("RH_RESULT_REFERENCE","verification references unknown claim")
    def _check_claim(self,claim,evidence,require_parse_revision=False):
        lookup={x["evidence_id"]:x for x in evidence}
        for ref in claim["evidence_refs"]:
            item=lookup.get(ref)
            if not item or claim["document_id"]!=item["document_id"] or claim["version_id"]!=item["version_id"] or not item.get("locator") or claim["quote"] not in item["text"]:raise InvestigationError("RH_RESULT_REFERENCE","claim quotation does not bind to normalized evidence")
            if require_parse_revision and item.get("parse_revision_id") and claim.get("parse_revision_id")!=item["parse_revision_id"]:raise InvestigationError("RH_RESULT_REFERENCE","claim parse revision does not bind to normalized evidence")
    def _done(self,run,role,typ):
        sql="SELECT result FROM model_tasks WHERE run_id=? AND task_type=? AND status='completed'";args=[run,typ]
        if role:sql+=" AND role=?";args.append(role)
        return [json.loads(x["result"]) for x in self.db.execute(sql,args)]
    def _pending(self,run):return self.db.execute("SELECT 1 FROM model_tasks WHERE run_id=? AND status='pending'",(run,)).fetchone() is not None
    def _run(self,run):
        x=self.db.execute("SELECT * FROM investigations WHERE id=?",(run,)).fetchone()
        if not x:raise NotFoundError()
        return x
    def _synthetic_run(self,run): return json.loads(self._run(run)["runtime"]).get("data_mode") == "synthetic"
    def _sources(self,run):
        fixture=json.loads(run["scenario"]).get("sources",[])
        live=[json.loads(row["payload"]) for row in self.db.execute("SELECT payload FROM discovery_documents WHERE run_id=? ORDER BY rowid",(run["id"],))]
        return [*fixture,*live]
    def _search_pages(self,run_id,source,query_id,query,runtime,run):
        if source=="openalex":
            return self._search_live_pages(run_id,query_id,query,runtime)
        if source=="epo":
            return self._search_epo_pages(run_id,query_id,query,runtime)
        live_source=runtime.get("data_mode")=="live"
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
                    if live_source and budget["reserved_source_calls"]>=budget["max_source_calls"]:
                        self._trace(run_id,"source_task","source_partial",{"query_id":query_id,"code":"RH_SOURCE_BUDGET"}); return found,"partial","source call budget exhausted"
                    attempt=self.db.execute("SELECT COUNT(*) FROM source_attempts WHERE run_id=? AND query_id=? AND cursor IS ?",(run_id,query_id,cursor)).fetchone()[0]+1
                    if live_source: budget["reserved_source_calls"]+=1
                    self.db.execute("BEGIN IMMEDIATE")
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

    def _search_live_pages(self,run_id,query_id,query,runtime):
        cursor=None; found=[]; seen=set(); source_config=runtime["sources"]["openalex"]; max_pages=min(int(runtime["budget"].get("max_pages_per_query",32)),int(source_config.get("max_pages",32))); max_candidates=int(source_config.get("max_candidates",100))
        active={"cursor":None,"attempt":None,"maximum":0}
        def reserve_http(meta):
            phase=meta.get("phase") if isinstance(meta,dict) else None
            if phase is None:  # Backward-compatible deterministic transport doubles.
                self.db.execute("BEGIN IMMEDIATE")
                try:
                    run=self._run(run_id); budget=json.loads(run["budget"])
                    if run["status"] in {"stopped","completed","partial","failed","policy_blocked","cancelled"}: raise SourceError("RH_SOURCE_INACTIVE","run is inactive")
                    if budget.get("reserved_source_calls",0)>=budget.get("max_source_calls",0): raise SourceError("RH_SOURCE_BUDGET","source request budget exhausted")
                    budget["reserved_source_calls"]+=1; budget["reserved_openalex_calls"]=budget.get("reserved_openalex_calls",0)+1
                    self.db.execute("UPDATE investigations SET budget=?,updated=? WHERE id=?",(json.dumps(budget),time.time(),run_id)); self.db.commit()
                except Exception: self.db.rollback(); raise
                return
            self.db.execute("BEGIN IMMEDIATE")
            try:
                run=self._run(run_id); budget=json.loads(run["budget"])
                if run["status"] in {"stopped","completed","partial","failed","policy_blocked","cancelled"}: raise SourceError("RH_SOURCE_INACTIVE","run is inactive")
                if phase=="prepared":
                    limits=("max_source_calls","max_source_bytes","max_source_response_bytes")
                    if any(type(budget.get(key)) is not int or budget[key]<1 for key in limits): raise SourceError("RH_SOURCE_BUDGET","OpenAlex numeric source budgets must be explicit and positive")
                    maximum=budget["max_source_response_bytes"]
                    if budget.get("reserved_source_calls",0)>=budget["max_source_calls"] or budget.get("received_source_bytes",0)+budget.get("reserved_source_bytes",0)+maximum>budget["max_source_bytes"]:
                        raise SourceError("RH_SOURCE_BUDGET","OpenAlex source call or byte budget exhausted")
                    openalex_limit=json.loads(run["scenario"]).get("source_call_limits",{}).get("openalex")
                    if openalex_limit is not None and budget.get("reserved_openalex_calls",0)>=openalex_limit: raise SourceError("RH_SOURCE_BUDGET","OpenAlex search request limit exhausted")
                    budget["reserved_source_calls"]+=1; budget["reserved_openalex_calls"]=budget.get("reserved_openalex_calls",0)+1
                    budget["reserved_source_bytes"]=budget.get("reserved_source_bytes",0)+maximum
                    active["maximum"]=maximum
                    params=meta.get("params",{})
                    receipt={"kind":"openalex-search","method":"GET","url":"https://api.openalex.org/works","params_sha256":hashlib.sha256(json.dumps(params,sort_keys=True).encode()).hexdigest(),"header_names":meta.get("header_names",[]),"request_receipt_status":"prepared"}
                    row=self.db.execute("SELECT status FROM source_attempts WHERE run_id=? AND query_id=? AND cursor IS ? AND attempt=?",(run_id,query_id,active["cursor"],active["attempt"])).fetchone()
                    if not row or row["status"]!="pending": raise SourceError("RH_SOURCE_INACTIVE","OpenAlex request lease changed before dispatch")
                    self.db.execute("UPDATE source_attempts SET status='dispatching',result=? WHERE run_id=? AND query_id=? AND cursor IS ? AND attempt=?",(json.dumps(receipt),run_id,query_id,active["cursor"],active["attempt"]))
                elif phase in {"received","response_rejected"}:
                    response_bytes=int(meta.get("response_bytes",0))
                    budget["reserved_source_bytes"]=max(0,budget.get("reserved_source_bytes",0)-active["maximum"])
                    budget["received_source_bytes"]=budget.get("received_source_bytes",0)+response_bytes
                    status="dispatching" if phase=="received" and 200<=int(meta.get("status_code",0))<300 else ("RH_SOURCE_RESPONSE_LIMIT" if phase=="response_rejected" else "RH_SOURCE_HTTP_"+str(meta.get("status_code",0)))
                    row=self.db.execute("SELECT result FROM source_attempts WHERE run_id=? AND query_id=? AND cursor IS ? AND attempt=?",(run_id,query_id,active["cursor"],active["attempt"])).fetchone()
                    receipt=json.loads(row["result"]) if row else {}
                    receipt.update({"request_receipt_status":"recorded","http_status":meta.get("status_code"),"received_bytes":response_bytes})
                    self.db.execute("UPDATE source_attempts SET status=?,result=? WHERE run_id=? AND query_id=? AND cursor IS ? AND attempt=? AND status='dispatching'",(status,json.dumps(receipt),run_id,query_id,active["cursor"],active["attempt"]))
                elif phase=="outcome_unknown":
                    row=self.db.execute("SELECT result FROM source_attempts WHERE run_id=? AND query_id=? AND cursor IS ? AND attempt=?",(run_id,query_id,active["cursor"],active["attempt"])).fetchone()
                    receipt=json.loads(row["result"]) if row else {}
                    receipt["request_receipt_status"]="recorded"; receipt["outcome"]="unknown"
                    self.db.execute("UPDATE source_attempts SET status='outcome_unknown',result=? WHERE run_id=? AND query_id=? AND cursor IS ? AND attempt=? AND status='dispatching'",(json.dumps(receipt),run_id,query_id,active["cursor"],active["attempt"]))
                    self.db.execute("UPDATE source_queries SET status='outcome_unknown',reason='OpenAlex transport outcome is unknown' WHERE run_id=? AND query_id=?",(run_id,query_id))
                self.db.execute("UPDATE investigations SET budget=?,updated=? WHERE id=?",(json.dumps(budget),time.time(),run_id)); self.db.commit()
            except Exception: self.db.rollback(); raise
        transport=OpenAlexTransport({**runtime,"budget":json.loads(self._run(run_id)["budget"])},reserve_http)
        while True:
            if len(seen)>=max_pages or cursor in seen:
                return found,"partial","cursor loop or page limit"
            cached=self.db.execute("SELECT result FROM source_attempts WHERE run_id=? AND query_id=? AND cursor IS ? AND status='success' ORDER BY attempt DESC LIMIT 1",(run_id,query_id,cursor)).fetchone()
            if cached:
                page=json.loads(cached["result"])
            else:
                if self.db.execute("SELECT 1 FROM source_attempts WHERE run_id=? AND query_id=? AND cursor IS ? AND status IN ('pending','dispatching','outcome_unknown')",(run_id,query_id,cursor)).fetchone():
                    return found,"partial","uncertain prior source call"
                page=None
                for _ in range(3):
                    number=self.db.execute("SELECT COUNT(*) FROM source_attempts WHERE run_id=? AND query_id=? AND cursor IS ?",(run_id,query_id,cursor)).fetchone()[0]+1
                    self.db.execute("INSERT INTO source_attempts VALUES (?,?,?,?,?,?)",(run_id,query_id,cursor,number,"pending",json.dumps({"kind":"search"}))); self.db.commit()
                    active.update({"cursor":cursor,"attempt":number,"maximum":0})
                    try:
                        page=transport.search("openalex",query,cursor)
                    except SourceError as error:
                        lease=self.db.execute("SELECT status,result FROM source_attempts WHERE run_id=? AND query_id=? AND cursor IS ? AND attempt=?",(run_id,query_id,cursor,number)).fetchone()
                        receipt=json.loads(lease["result"] or "{}") if lease else {}
                        synthetic_transport=not receipt.get("request_receipt_status")
                        if lease and lease["status"] in {"pending","dispatching"}:
                            terminal=error.code if synthetic_transport else ("outcome_unknown" if error.code in {"RH_SOURCE_TIMEOUT","RH_SOURCE_NETWORK_ERROR","RH_SOURCE_SOURCE_UNAVAILABLE"} else error.code)
                            self.db.execute("UPDATE source_attempts SET status=? WHERE run_id=? AND query_id=? AND cursor IS ? AND attempt=?",(terminal,run_id,query_id,cursor,number)); self.db.commit()
                        known_http=receipt.get("http_status")
                        retry_known=known_http==429 or (isinstance(known_http,int) and known_http>=500)
                        if (synthetic_transport and error.code in {"RH_SOURCE_RATE_LIMIT","RH_SOURCE_TIMEOUT","RH_SOURCE_SOURCE_UNAVAILABLE","RH_SOURCE_NETWORK_ERROR"}) or retry_known:
                            if isinstance(error.retry_after,(int,float)) and error.retry_after > 0: time.sleep(min(error.retry_after,5))
                            continue
                        return found,"partial",error.code
                    self.db.execute("UPDATE source_attempts SET status='success',result=? WHERE run_id=? AND query_id=? AND cursor IS ? AND attempt=?",(json.dumps(page),run_id,query_id,cursor,number)); self.db.commit(); break
                if page is None: return found,"partial","source retry exhausted"
            for document in page["candidates"]:
                if len(found) >= max_candidates: break
                self.db.execute("INSERT OR REPLACE INTO discovery_documents VALUES (?,?,?)",(run_id,document["document_id"],json.dumps(document)))
                found.append(document)
            self.db.commit(); seen.add(cursor); cursor=page["next_cursor"]
            if len(found) >= max_candidates and cursor is not None: return found,"partial","candidate limit"
            if cursor is None:return found,"complete",None

    def _screens(self,run):
        return [json.loads(x["result"]) for x in self.db.execute("SELECT result FROM model_tasks WHERE run_id=? AND task_type LIKE 'screen:%' AND status='completed' ORDER BY created,id",(run,))]

    def _set_query(self,run,query_id,status,reason):
        self.db.execute("UPDATE source_queries SET status=?,reason=? WHERE run_id=? AND query_id=?",(status,reason,run,query_id)); self.db.commit()

    def _query_is_sensitive(self,item,run):
        refs=set(item.get("input_refs",[])); baseline={"baseline:"+x["document_id"] for x in json.loads(run["scenario"]).get("references",[]) if x.get("visibility")=="confidential"}
        snapshots=json.loads(run["scenario"]).get("baseline_snapshot",[])
        evidence_ids={x.get("evidence_id") for x in snapshots if x.get("visibility")=="confidential"}
        legacy_confidential=any(x.get("visibility")=="confidential" for x in json.loads(run["scenario"]).get("references",[]))
        return bool(refs & baseline) or bool(refs & evidence_ids) or legacy_confidential and bool(snapshots) or any(x.get("visibility")=="confidential" for x in snapshots)

    def _visible_candidates(self,candidates,runtime,run):
        records={x.get("document_id"):x for x in self._sources(run)}; unique={}; out=[]
        for candidate in candidates:
            if not isinstance(candidate,dict) or not isinstance(candidate.get("document_id"),str) or not candidate["document_id"]:
                self._trace(run["id"],"source_task","source_partial",{"code":"RH_SOURCE_INVALID_RESPONSE"}); continue
            record=records.get(candidate.get("document_id"),candidate)
            if not policy_allows(record,runtime): continue
            key=canonical_identity(dict(record,**candidate))
            if key in unique: continue
            unique[key]=candidate
            out.append({name:candidate.get(name) for name in ("document_id","title","doi","year","type","abstract","authors","locations","source_id","query_provenance","publication_id","country","publication_number","kind","version","source") if name in candidate})
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
            details=self.db.execute("SELECT payload FROM source_query_details WHERE run_id=? AND query_id=?",(run,item["query_id"])).fetchone()
            if details: item.update(json.loads(details["payload"]))
            if item["status"] == "policy_blocked":
                item.pop("query",None); item["input_refs"]=[]; item.pop("term_evidence",None)
        attempts=[dict(x) for x in self.db.execute("SELECT query_id,cursor,attempt,status FROM source_attempts WHERE run_id=? ORDER BY query_id,attempt",(run,))]
        scenario=json.loads(self._run(run)["scenario"])
        rag_mode="reference_rag_evidence_ids" in scenario
        rag_supported=any(set(item["input_refs"]) & set(scenario.get("reference_rag_evidence_ids",[])) for item in queries)
        coverage={"queries":queries,"attempts":attempts,"complete":bool(queries) and (not rag_mode or rag_supported) and all(x["status"]=="complete" for x in queries)}
        if rag_mode:
            coverage["reference_rag_diagnostics"]=scenario.get("reference_rag_diagnostics")
            coverage["rag_supported_query"]=rag_supported
        return coverage

    def _finish_source_partial(self,run,message):
        result={"run_id":run,"synthetic":self._synthetic_run(run),"outcome":"partial","conclusion":message,"verification":None,"findings":[],"evidence":[],"artifacts":[],"issues":[{"code":"RH_SOURCE_PARTIAL","status":"open"}],"coverage":self._coverage(run)}
        self.db.execute("UPDATE investigations SET status='partial',stage='completed',result=?,updated=? WHERE id=?",(json.dumps(result),time.time(),run));self.db.commit()
    def _set(self,run,**kw):
        kw["updated"]=time.time();self.db.execute("UPDATE investigations SET "+",".join(f"{k}=?" for k in kw)+" WHERE id=?",(*kw.values(),run));self.db.commit()
    def _trace(self,run,node,event,extra=None):
        r=self._run(run);x=json.loads(r["trace"]);x.append({"node":node,"event":event,**(extra or {})});self.db.execute("UPDATE investigations SET trace=?,updated=? WHERE id=?",(json.dumps(x),time.time(),run));self.db.commit()
