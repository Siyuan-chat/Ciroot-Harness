# Commit-specific independent acceptance probe; all input text is synthetic.
# Prerequisite: archive bc0df21 into .local/acceptance/bc0df21/source as described in the review.
import sys, json, copy, os, subprocess, hashlib, uuid
from pathlib import Path
root=Path(__file__).resolve().parents[1]
base=root/".local/acceptance/bc0df21"
source=base/"source"
sys.path.insert(0,str(source/"src"))
from research_harness.contracts import validate_spec,validate_runtime
from research_harness.service import Harness
spec=json.loads((source/"examples/polymer-design.draft.json").read_text(encoding="utf-8-sig"))
runtime=json.loads((source/"examples/runtime.example.json").read_text(encoding="utf-8-sig"))
results={}
bad={}
for name, path, value in [
 ("negative_candidate_budget",["execution","budget","max_candidates"],-1),
 ("automatic_global_rules",["human_review","global_rule_updates"],"automatic"),
 ("invalid_date",["scope","publication_date_from"],"2026-02-30"),
 ("empty_reports",["languages","reports"],[])]:
 c=copy.deepcopy(spec); ptr=c
 for key in path[:-1]:ptr=ptr[key]
 ptr[path[-1]]=value
 try:validate_spec(c);bad[name]="ACCEPTED_INVALID"
 except Exception as e:bad[name]=type(e).__name__
c=copy.deepcopy(spec)
c["criteria"]=[{"id":"threshold_a","description":"contract test","mode":"threshold","target":{},"required_conditions":{},"required":True,"minimum_evidence":"fulltext"}]
try:validate_spec(c);bad["empty_threshold_target"]="ACCEPTED_INVALID"
except Exception as e:bad["empty_threshold_target"]=type(e).__name__
c=copy.deepcopy(runtime);c["llm"]["api_key"]="SYNTHETIC_NOT_A_SECRET"
try:validate_runtime(c);bad["inline_api_key"]="ACCEPTED_INVALID"
except Exception as e:bad["inline_api_key"]=type(e).__name__
results["contract_probes"]=bad
case=base/("probes-"+uuid.uuid4().hex[:8]);case.mkdir()
s=copy.deepcopy(spec);s.update(status="ready",unresolved_questions=[])
r=copy.deepcopy(runtime)
r["llm"].update(model="fixture-local",local=True)
r["retrieval"]["mode"]="lexical_test_only"
for cfg in r["sources"].values():cfg["enabled"]=False
sp=case/"research.json";rp=case/"runtime.json"
rp.write_text(json.dumps(r),encoding="utf-8")
h=Harness(case/"workspace")
ids=[]
for n in (1,2):
 p=case/f"reference{n}.txt";p.write_text(f"SYNTHETIC reference {n}. No scientific measurements.",encoding="utf-8")
 ids.append(h.import_document(p,"baseline","paper"))
s["reference_library"]["collection_ids"]=[]
s["reference_library"]["document_ids"]=[ids[0]]
sp.write_text(json.dumps(s),encoding="utf-8")
rid=h.run(sp,rp)
out=case/"workspace/reports"/rid/"report.json"
before=out.read_bytes();before_data=json.loads(before)
results["baseline_selection"]={"requested":[ids[0]],"actual":before_data["baseline_document_ids"],"respected":before_data["baseline_document_ids"]==[ids[0]]}
p=case/"later-discovery.txt";p.write_text("SYNTHETIC document added after run completed.",encoding="utf-8")
later=h.import_document(p,"discovery","paper")
h.report(rid,["zh","en","ja"])
after=out.read_bytes();after_data=json.loads(after)
results["historical_report"]={"same_path_overwritten":before!=after,"documents_before":len(before_data["documents"]),"documents_after":len(after_data["documents"]),"later_document_in_old_run":later in [d["id"] for d in after_data["documents"]]}
h.store.close()
env=os.environ.copy();env["PYTHONPATH"]=str(source/"src");env["PYTHONDONTWRITEBYTECODE"]="1"
for key in ("RH_LLM_API_KEY","OPENALEX_API_KEY","EPO_CONSUMER_KEY","EPO_CONSUMER_SECRET"):env.pop(key,None)
def cli(args,cwd=case):
 p=subprocess.run([sys.executable,"-m","research_harness.cli",*args],cwd=cwd,env=env,capture_output=True,text=True,encoding="utf-8",errors="replace")
 return {"returncode":p.returncode,"stdout":p.stdout,"stderr":p.stderr}
clidir=case/"validate-only";clidir.mkdir(exist_ok=True)
val=cli(["validate","--spec",str(sp)],clidir)
results["validate_side_effects"]={"returncode":val["returncode"],"created":[p.name for p in clidir.iterdir()]}
r=copy.deepcopy(runtime);r["llm"]["model"]="missing-model-probe";r["retrieval"]["embedding"]["model"]="missing-embedding-probe"
rp.write_text(json.dumps(r),encoding="utf-8")
probe=cli(["run","--spec",str(sp),"--runtime",str(rp),"--workspace",str(case/"live-preflight")])
results["run_missing_credentials"]=probe
if probe["returncode"]==0:
 run_id=json.loads(probe["stdout"])["run_id"]
 facts=json.loads((case/"live-preflight/reports"/run_id/"report.json").read_text(encoding="utf-8"))
 results["run_missing_credentials"]["reported_status"]=facts["status"]
results["resume_missing_run"]=cli(["resume","nonexistent-run","--runtime",str(rp),"--workspace",str(case/"live-preflight")])
results["chat_command"]=cli(["chat","--help"])
(base/"acceptance-probes.json").write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(results,ensure_ascii=False,indent=2))

violations = [
 any(v == "ACCEPTED_INVALID" for v in results["contract_probes"].values()),
 not results["baseline_selection"]["respected"],
 results["historical_report"]["same_path_overwritten"],
 bool(results["validate_side_effects"]["created"]),
 results["run_missing_credentials"]["returncode"] == 0,
 results["resume_missing_run"]["returncode"] == 0,
 results["chat_command"]["returncode"] != 0,
]
raise SystemExit(1 if any(violations) else 0)
