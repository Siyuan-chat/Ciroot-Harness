"""Independent D19 query-path tests with synthetic sources and blocked network."""
import argparse, copy, json, os, socket, subprocess, sys, tempfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--source-root',required=True,type=Path);p.add_argument('--checkpoint',required=True);p.add_argument('--output',required=True,type=Path);p.add_argument('--case')
a=p.parse_args();sys.path.insert(0,str(a.source_root.resolve()/'src'))
socket.socket.connect=lambda *_a,**_k:(_ for _ in ()).throw(AssertionError('No P1 external network'))
from research_harness.investigation import InvestigationService
from research_harness.errors import HarnessError
S={'status':'ready','project_id':'ind-query','revision':1,'research_question':'SYNTHETIC Meridian indigo separator investigation','report_targets':['technical_report','literature_review'],'references':[]}
R={'mode':'host','data_mode':'synthetic','budget':{'max_tasks':20,'max_source_calls':12}}
def doc(name,**kw):return dict({'source':'synthetic-paper','document_id':name,'version':'v1','title':'SYNTHETIC '+name,'text':'SYNTHETIC indigo separator record '+name+'.'},**kw)
def q(name,source='synthetic-paper'):return {'query_id':name,'source':source,'query':'indigo separator '+name,'input_refs':[],'parent_query_id':None}
def pg(query,docs,cursor=None,next_cursor=None,**kw):return dict({'source':query['source'],'query_id':query['query_id'],'cursor':cursor,'candidates':docs,'next_cursor':next_cursor},**kw)
def start(s,docs,pages,queries,rt=None,refs=None):
 run=s.create_investigation(copy.deepcopy(S),copy.deepcopy(rt or R),{'sources':docs,'transport_pages':pages,'references':refs or []})['run_id']
 task=s.get_pending_tasks(run)[0];s.submit_model_result(run,task['task_id'],{'search_plan':{'queries':queries}},task['task_version']);s.advance_investigation(run);return run

def finish(s,run):
 for _ in range(20):
  tasks=s.get_pending_tasks(run)
  for t in tasks:
   role=t['role'];pl=t['payload']
   if role in ('paper_search','patent_search'):r={'candidates':[{'document_id':x['document_id'],'relevance':'relevant','reason':'SYNTHETIC independent selection'} for x in pl['candidates']]}
   elif role=='evidence_analysis':r={'findings':[{'finding_id':'f0','finding':'SYNTHETIC retained public evidence','evidence_ids':[x['evidence_id'] for x in pl['evidence']],'value':None,'unit':None,'conditions':None}]}
   elif role=='business_judgment':r={'judgments':[{'document_id':x['document_id'],'relevance':'relevant','human_review_required':False,'reason':'SYNTHETIC scope'} for x in pl['documents']]}
   elif role=='synthesis':
    e=pl['evidence'][0];r={'claims':[{'claim_id':'c0','claim':e['text'],'finding_refs':[0],'evidence_refs':[e['evidence_id']],'quote':e['text'],'document_id':e['document_id'],'version_id':e['version_id']}]}
   elif role=='writing':r={'sections':[{'deliverable_type':kind,'language':'en','section_id':'results','title':'SYNTHETIC report','body':'SYNTHETIC public evidence remains available for the bounded investigation.','claim_ids':['c0']} for kind in ('technical_report','literature_review')]}
   elif role=='verification':r={'verification':{'status':'supported','conclusion':'SYNTHETIC retained public evidence','supported_claim_refs':[0]}}
   else:raise AssertionError('Unexpected role '+role)
   s.submit_model_result(run,t['task_id'],r,t['task_version'])
  s.advance_investigation(run)
  if s.status(run)['outcome'] in ('completed','partial') and not s.get_pending_tasks(run):return s.get_result(run)
 raise AssertionError('No bounded completion')

def multi():
 with tempfile.TemporaryDirectory() as tmp:
  s=InvestigationService(tmp)
  try:
   d1=doc('paper-a',doi='https://doi.org/10.8642/INDIGO');du=doc('paper-duplicate',doi='10.8642/indigo');d2=doc('paper-b');d3=doc('paper-c')
   pa=doc('ZZ8642A1',source='synthetic-patent',publication_number='ZZ8642A1',family_id='family8642');pb=doc('ZZ8642B1',source='synthetic-patent',publication_number='ZZ8642B1',family_id='family8642')
   queries=[q('qp1'),q('qp2'),q('qpat','synthetic-patent')];pages=[pg(queries[0],[d1,du],next_cursor='next'),pg(queries[0],[d2],cursor='next'),pg(queries[1],[d3]),pg(queries[2],[pa,pb])]
   run=start(s,[d1,du,d2,d3,pa,pb],pages,queries);ts=s.get_pending_tasks(run)
   assert {t['payload']['query_id'] for t in ts}=={'qp1','qp2','qpat'},'Queries lost or task identities collided'
   ids={x['document_id'] for t in ts for x in t['payload']['candidates']};assert len(ids)==5 and {'ZZ8642A1','ZZ8642B1'}<=ids,'DOI/publication identity not preserved'
   before=s.status(run)['budget'];assert before['reserved_source_calls']==4
   s.close();s=InvestigationService(tmp);s.resume_investigation(run);assert s.status(run)['budget']==before and s.get_pending_tasks(run)==ts
   return {'queries':3,'source_calls':4,'unique_candidates':5}
  finally:s.close()
def partial():
 with tempfile.TemporaryDirectory() as tmp:
  s=InvestigationService(tmp)
  try:
   d=doc('public-good');qs=[q('good'),q('failed','synthetic-patent')]
   run=start(s,[d],[pg(qs[0],[d]),pg(qs[1],[],error='forbidden')],qs);r=finish(s,run)
   assert r['outcome']=='partial','Source failure was promoted to complete'
   assert r['evidence'] and any(e['document_id']=='public-good' for e in r['evidence'])
   assert s.status(run)['budget']['reserved_source_calls']==2,'403 was retried or not counted'
   assert 'FORBIDDEN' in json.dumps(r).upper() or 'FORBIDDEN' in json.dumps(s.status(run)).upper(),'Failed source missing from observable result/coverage'
   return 'Successful evidence retained with partial outcome'
  finally:s.close()
def budget():
 with tempfile.TemporaryDirectory() as tmp:
  s=InvestigationService(tmp)
  try:
   d=doc('first-page');query=q('budget');rt=copy.deepcopy(R);rt['budget']['max_source_calls']=1
   run=start(s,[d],[pg(query,[d],next_cursor='second'),pg(query,[],cursor='second')],[query],rt)
   before=s.status(run)['budget'];assert before['reserved_source_calls']==1
   for _ in range(3):s.resume_investigation(run)
   assert s.status(run)['budget']==before
   state=s.status(run);assert state['outcome']=='partial' or s.get_pending_tasks(run),'Source budget produced empty waiting state'
   return {'budget':before,'state':state['status']}
  finally:s.close()
def blocked_baseline():
 with tempfile.TemporaryDirectory() as tmp:
  s=InvestigationService(tmp)
  try:
   secret=doc('private-base',visibility='confidential',company_id='meridian',text='PRIVATE_BASELINE_8642')
   rt=copy.deepcopy(R);rt.update({'model_id':'unapproved','data_policy':{'company_id':'meridian','allowed_models':['approved'],'allow_query_egress':False}})
   run=s.create_investigation(S,rt,{'references':[secret],'sources':[],'transport_pages':[]})['run_id']
   assert s.get_pending_tasks(run)==[],'Denied required baseline was silently omitted while planning continued'
   state=s.status(run);assert 'RH_POLICY_BLOCKED' in json.dumps(state) and 'PRIVATE_BASELINE_8642' not in json.dumps(state)
   return 'Required confidential baseline blocks before model task'
  finally:s.close()
def query_egress():
 with tempfile.TemporaryDirectory() as tmp:
  s=InvestigationService(tmp)
  try:
   secret=doc('private-base',visibility='confidential',company_id='meridian',text='PRIVATE_QUERY_8642')
   rt=copy.deepcopy(R);rt.update({'model_id':'approved','data_policy':{'company_id':'meridian','allowed_models':['approved'],'allow_query_egress':False}})
   query=q('derived');query['query']='PRIVATE_QUERY_8642'
   run=start(s,[],[pg(query,[])],[query],rt,[secret]);st=s.status(run)
   assert st['budget']['reserved_source_calls']==0,'Forbidden derived query executed'
   assert not s.get_pending_tasks(run) and 'RH_POLICY_BLOCKED' in json.dumps(st)
   assert 'PRIVATE_QUERY_8642' not in json.dumps(st), 'Sensitive blocked query leaked in general status coverage'
   return 'Approved model does not imply query egress permission'
  finally:s.close()
def source_visibility():
 with tempfile.TemporaryDirectory() as tmp:
  s=InvestigationService(tmp)
  try:
   secret=doc('private-source',visibility='confidential',company_id='other',title='PRIVATE_TITLE_8642');safe=doc('public-safe');query=q('visible')
   # A transport metadata record cannot erase the source document classification.
   stripped={'document_id':secret['document_id'],'title':secret['title']}
   run=start(s,[secret,safe],[pg(query,[stripped,safe])],[query]);tasks=s.get_pending_tasks(run)
   body=json.dumps(tasks);assert 'PRIVATE_TITLE_8642' not in body and 'private-source' not in body,'Transport metadata bypassed stored confidentiality'
   assert 'public-safe' in body
   return 'Policy checked before candidate identity/title disclosure'
  finally:s.close()
def cyclic():
 if a.case!='cycle':
  with tempfile.TemporaryDirectory() as tmp:
   cp=subprocess.run([sys.executable,__file__,'--source-root',str(a.source_root.resolve()),'--checkpoint',a.checkpoint,'--output',str(Path(tmp)/'cycle.json'),'--case','cycle'],capture_output=True,text=True,timeout=12,env=dict(os.environ,LANGCHAIN_TRACING_V2='false',LANGSMITH_TRACING='false'))
   assert cp.returncode==0,cp.stdout+cp.stderr
   return 'Repeated cursor terminates with incomplete coverage'
 with tempfile.TemporaryDirectory() as tmp:
  s=InvestigationService(tmp)
  try:
   d=doc('cycle-doc');query=q('cycle');run=start(s,[d],[pg(query,[d],next_cursor='loop'),pg(query,[d],cursor='loop',next_cursor='loop')],[query]);assert s.status(run)['budget']['reserved_source_calls']<=12
   assert 'cycle' in json.dumps(s.status(run)).lower() or 'partial' in json.dumps(s.status(run)).lower()
  finally:s.close()

def fault_sequences():
 for errors in (['rate_limit'],['timeout','server_error']):
  with tempfile.TemporaryDirectory() as tmp:
   s=InvestigationService(tmp)
   try:
    d=doc('retry-success');query=q('retry');pages=[pg(query,[],error=code,attempt=i+1) for i,code in enumerate(errors)]+[pg(query,[d],attempt=len(errors)+1)]
    run=start(s,[d],pages,[query]);st=s.status(run)
    assert st['coverage']['complete'] is True and s.get_pending_tasks(run), 'Transient failure did not reach provided successful response'
    assert st['budget']['reserved_source_calls']==len(errors)+1, 'Retry accounting incorrect'
    s.resume_investigation(run);assert s.status(run)['budget']==st['budget']
   finally:s.close()
 for code in ('unauthorized','uncertain','invalid_json'):
  with tempfile.TemporaryDirectory() as tmp:
   s=InvestigationService(tmp)
   try:
    query=q('terminal');run=start(s,[],[pg(query,[],error=code)],[query]);before=s.status(run)
    for _ in range(3):s.resume_investigation(run)
    assert s.status(run)['budget']['reserved_source_calls']==1 and s.status(run)['budget']==before['budget'], 'Terminal/uncertain operation was repeated'
    assert s.status(run)['outcome']=='partial'
   finally:s.close()
 return 'Transient retries consume actual attempts; auth/uncertain/malformed remain bounded'
def malformed_candidate():
 with tempfile.TemporaryDirectory() as tmp:
  s=InvestigationService(tmp)
  try:
   query=q('malformed');run=start(s,[],[pg(query,[{'title':'Record without identity'}])],[query])
   assert s.status(run)['outcome']=='partial' and not s.get_pending_tasks(run)
   return 'Malformed record produces explicit source failure'
  finally:s.close()
def invalid_lineage():
 with tempfile.TemporaryDirectory() as tmp:
  s=InvestigationService(tmp)
  try:
   run=s.create_investigation(S,R,{'sources':[],'references':[],'transport_pages':[]})['run_id'];task=s.get_pending_tasks(run)[0]
   for change in ({'input_refs':['not-a-real-evidence-id']},{'parent_query_id':'missing-parent'},{'parent_query_id':'unknown-ref'},{'source':'not-an-enabled-source'}):
    query=q('unknown-ref');query.update(change)
    try:s.submit_model_result(run,task['task_id'],{'search_plan':{'queries':[query]}},task['task_version'])
    except HarnessError:pass
    else:raise AssertionError('Invalid query consumed planning task: '+str(change))
    assert s.get_pending_tasks(run)[0]['task_id']==task['task_id'] and s.status(run)['budget']['reserved_source_calls']==0
   return 'Invalid evidence/parent/source rejected before consuming planning result'
  finally:s.close()

checks=[]
for name,fn in [('multi',multi),('partial',partial),('budget',budget),('baseline-policy',blocked_baseline),('query-egress',query_egress),('source-policy',source_visibility),('cycle',cyclic),('fault-sequences',fault_sequences),('malformed-candidate',malformed_candidate),('invalid-lineage',invalid_lineage)]:
 if a.case and a.case!=name:continue
 try:detail=fn();checks.append({'id':name,'status':'passed','detail':detail})
 except Exception as e:checks.append({'id':name,'status':'failed','type':type(e).__name__,'detail':str(e)[:900]})
r={'checkpoint':a.checkpoint,'synthetic':True,'scope':'C2-B public service query, recovery and policy checks','checks':checks};a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(r,ensure_ascii=False));raise SystemExit(0 if all(x['status']=='passed' for x in checks) else 1)
