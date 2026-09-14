"""Independent synthetic public monitor/review lifecycle; no scheduler or live API."""
import argparse,copy,csv,json,socket,sys,tempfile
from pathlib import Path
from probe_investigation_service import answer
P={'company_id':'violet','rule_version':'rule1','scope':'SYNTHETIC violet separator business'}
MS={'name':'Independent violet monitor','report_languages':['en']}
R={'mode':'host','data_mode':'synthetic','budget':{'max_tasks':30,'max_source_calls':8,'max_cycles':8,'max_total_tasks':100}}
Q=[{'query_id':'qpat','source':'synthetic-patent','query':'violet separator','input_refs':[],'parent_query_id':None}]
def doc(name,version='v1',published='2026-01-03'):
 return {'document_id':name,'version':version,'source':'synthetic-patent','publication_number':name,'family_id':'family-'+name,'published_at':published,'title':'SYNTHETIC '+name,'text':'SYNTHETIC violet separator support '+name+' '+version+'.'}
def scenario(key,start,end,docs,error=None):
 page={'source':'synthetic-patent','query_id':'qpat','cursor':None,'next_cursor':None,'candidates':copy.deepcopy(docs)}
 if error:page['error']=error
 return {'cycle_key':key,'window_start':start,'window_end':end,'sources':copy.deepcopy(docs),'references':[],'transport_pages':[page]}
def respond(t,judgment):
 role=t['role'];p=t['payload']
 if role=='business_judgment':return {'judgments':[{'document_id':d,'relevance':judgment[0],'human_review_required':judgment[1],'reason':'SYNTHETIC declared business comparison'} for d in sorted({x['document_id'] for x in p['documents']})]}
 if role=='writing':return {'sections':[{'deliverable_type':'patent_monitor_digest','language':'en','section_id':'observations','title':'Synthetic monitoring observations','body':'SYNTHETIC supplied patent records describe violet separator support. Business relevance and human review require separate decisions.','claim_ids':[c['claim_id'] for c in p['claims']]}]}
 return answer(t,Q)
def drive(s,run,judgment=('uncertain',False),stop_before_judgment=False):
 roles=[]
 for _ in range(20):
  ts=s.get_pending_tasks(run)
  if stop_before_judgment and any(t['role']=='business_judgment' for t in ts):return roles
  for t in ts:
   roles.append(t['role']);s.submit_model_result(run,t['task_id'],respond(t,judgment),t['task_version'])
  s.advance_investigation(run)
  if not s.get_pending_tasks(run) and s.status(run)['outcome'] in ('completed','partial'):return roles
 raise AssertionError('Monitor run did not stop within bounded replay')
def cycle_state(s,m,key):return next(c for c in s.monitor_status(m)['cycles'] if c['cycle_key']==key)
def multi():
 with tempfile.TemporaryDirectory() as tmp:
  s=InvestigationService(tmp)
  try:
   assert s.validate_monitor(P,MS,R)['valid'] is True
   m=s.create_monitor(P,MS,R)['monitor_id'];a=doc('ZZ8642A1');first=scenario('w1','2026-01-01','2026-01-08',[a])
   run=s.run_monitor_once(m,first)['run_id'];roles=drive(s,run)
   assert 'business_judgment' in roles
   frozen=s.build_report_data(run);assert 'monitor' in frozen and 'rule1' in json.dumps(frozen['monitor']) and '2026-01-01' in json.dumps(frozen['monitor']),'Frozen report lacks monitoring context'
   assert 'human_review_required' in json.dumps(frozen) and 'uncertain' in json.dumps(frozen),'Effective judgment not frozen'
   first_export=s.export_report(run);md=next(x for x in first_export['artifacts'] if x['format']=='markdown')
   body=(Path(tmp)/md['path']).read_text(encoding='utf-8');assert 'rule1' in body and '2026-01-01' in body and 'uncertain' in body,'Digest omits decision/rule/window facts'
   html_art=next(x for x in first_export['artifacts'] if x['format']=='html');html_body=(Path(tmp)/html_art['path']).read_text(encoding='utf-8')
   assert all(value in html_body for value in ('rule1','2026-01-01','uncertain')),'HTML omits frozen monitor facts'
   assert '```json' not in body and '<pre>' not in html_body,'Monitor report contains raw implementation JSON rather than readable facts'
   review_art=next(x for x in first_export['artifacts'] if x['format']=='review_csv')
   rows=list(csv.DictReader((Path(tmp)/review_art['path']).read_text(encoding='utf-8-sig').splitlines()))
   selected=next((x for x in rows if x.get('document_id')==a['document_id']),None)
   assert selected and selected.get('relevance')=='uncertain' and str(selected.get('human_review_required')).lower() in ('true','1'),'Review CSV omits effective company judgment'
   c1=cycle_state(s,m,'w1');assert c1['complete'] and c1['watermark'] and not c1['judgment_backlog']
   items=s.review_list(m);assert len(items)==1 and items[0]['status']=='open' and items[0]['effective_judgment']['human_review_required'] is True,'uncertain false was not upgraded'
   issue=items[0]['issue_id'];budget=s.monitor_status(m)['budget']
   assert s.run_monitor_once(m,first)['run_id']==run and s.monitor_status(m)['budget']==budget,'Replay created work'
   run2=s.run_monitor_once(m,scenario('w2','2026-01-08','2026-01-15',[a]))['run_id'];roles2=drive(s,run2,('irrelevant',False))
   assert 'business_judgment' not in roles2,'Unchanged already-judged content was judged again'
   assert s.review_list(m)[0]['status']=='open','No-change cycle silently closed human issue'
   changed=doc('ZZ8642A1','v2');late=doc('ZZ8642L1',published='2022-04-01')
   run3=s.run_monitor_once(m,scenario('w3','2026-01-15','2026-01-22',[changed,late]))['run_id'];drive(s,run3,('relevant',False))
   c3=cycle_state(s,m,'w3');assert c3['complete'] and not c3['judgment_backlog']
   assert len(c3['documents'])==2 and not any(x['is_new_publication'] for x in c3['documents'])
   existing=next(x for x in s.review_list(m) if x['document_id']==a['document_id']);assert existing['issue_id']==issue and existing['status']=='open','Model false closed existing human issue'
   s.review_decide(issue,'irrelevant','Independent explicit human decision');assert next(x for x in s.review_list(m) if x['issue_id']==issue)['status']=='resolved'
   state=s.monitor_status(m);history=s.review_list(m);s.close();s=InvestigationService(tmp);assert s.monitor_status(m)==state and s.review_list(m)==history
   s.update_monitor_profile(m,dict(P,rule_version='rule2',scope='SYNTHETIC revised business scope'))
   run4=s.run_monitor_once(m,scenario('w4','2026-01-22','2026-01-29',[changed]))['run_id'];roles4=drive(s,run4,('uncertain',False));assert 'business_judgment' in roles4
   item=next(x for x in s.review_list(m) if x['issue_id']==issue);assert item['status']=='open' and any(e['kind']=='human' for e in item['events'])
   assert cycle_state(s,m,'w1')['rule_version']=='rule1' and cycle_state(s,m,'w4')['rule_version']=='rule2'
   exported=s.export_report(run4);assert any(a['type']=='patent_monitor_digest' for a in exported['artifacts'])
   s.pause_monitor(m)
   try:s.run_monitor_once(m,scenario('w5','2026-01-29','2026-02-05',[]))
   except HarnessError:pass
   else:raise AssertionError('Paused monitor collected new window')
   s.resume_monitor(m)
   return {'cycles':4,'unchanged_rejudgment':False,'rule_history':'retained','human_history':'retained'}
  finally:s.close()
def backlog_and_failure():
 with tempfile.TemporaryDirectory() as tmp:
  s=InvestigationService(tmp)
  try:
   m=s.create_monitor(P,MS,R)['monitor_id'];r=s.run_monitor_once(m,scenario('a','2026-01-01','2026-01-08',[doc('ZZ8642A1')]))['run_id'];drive(s,r,stop_before_judgment=True)
   c=cycle_state(s,m,'a');assert c['complete'] and c['judgment_backlog'],'Collection waits for judgment completion'
   second=s.run_monitor_once(m,scenario('b','2026-01-08','2026-01-15',[],error='forbidden'))['run_id'];drive(s,second)
   failed=cycle_state(s,m,'b');assert not failed['complete'] and failed['watermark'] is None,'Failed source advanced complete watermark'
   assert cycle_state(s,m,'a')['judgment_backlog'],'New cycle erased previous backlog'
   before=s.monitor_status(m)['budget'];s.run_monitor_once(m,scenario('b','2026-01-08','2026-01-15',[],error='forbidden'));assert s.monitor_status(m)['budget']==before
   return 'New collection is independent of old judgment backlog; failures retain uncovered windows'
  finally:s.close()

def cumulative_budget():
 with tempfile.TemporaryDirectory() as tmp:
  s=InvestigationService(tmp)
  try:
   runtime=copy.deepcopy(R);runtime['budget'].update(max_total_tasks=8,max_cycles=2)
   m=s.create_monitor(P,MS,runtime)['monitor_id']
   first=s.run_monitor_once(m,scenario('cap1','2026-01-01','2026-01-08',[doc('ZZ8642A1')]))['run_id'];drive(s,first)
   before=s.monitor_status(m)['budget'];assert 0<before['task_reserved']<=8
   second=s.run_monitor_once(m,scenario('cap2','2026-01-08','2026-01-15',[doc('ZZ8642B1')]))['run_id'];drive(s,second)
   state=s.monitor_status(m);assert state['budget']['task_reserved']<=8 and s.get_result(second)['outcome']=='partial'
   s.close();s=InvestigationService(tmp);assert s.monitor_status(m)==state
   s.resume_investigation(second);assert s.monitor_status(m)['budget']==state['budget']
   try:s.run_monitor_once(m,scenario('cap3','2026-01-15','2026-01-22',[]))
   except HarnessError:pass
   else:raise AssertionError('Cross-cycle cap admitted another cycle')
   return 'Per-task cumulative budget survives restart and limits new cycles'
  finally:s.close()


def actual_collection():
 with tempfile.TemporaryDirectory() as tmp:
  s=InvestigationService(tmp)
  try:
   m=s.create_monitor(P,MS,R)['monitor_id'];a=doc('ZZ8642A1');extra=doc('ZZ8642UNQUERIED')
   sc=scenario('observed','2026-01-01','2026-01-08',[a]);sc['sources'].append(extra)
   run=s.run_monitor_once(m,sc)['run_id'];initial=cycle_state(s,m,'observed')
   assert not initial['complete'] and initial['watermark'] is None and not initial['documents'],'Collection completed before any actual query'
   changed=copy.deepcopy(sc);changed['sources'][0]['text']='Changed facts under same cycle key'
   try:s.run_monitor_once(m,changed)
   except HarnessError:pass
   else:raise AssertionError('Existing cycle accepted different scenario facts')
   drive(s,run,stop_before_judgment=True);collected=cycle_state(s,m,'observed')
   assert {d['document_id'] for d in collected['documents']}=={a['document_id']},'Unqueried scenario corpus was treated as search results'
   retry=scenario('retry','2026-01-08','2026-01-15',[doc('ZZ8642B1')]);success=retry['transport_pages'][0];success['attempt']=2
   retry['transport_pages'].insert(0,dict(success,attempt=1,error='rate_limit',candidates=[]))
   rr=s.run_monitor_once(m,retry)['run_id'];drive(s,rr,stop_before_judgment=True)
   assert cycle_state(s,m,'retry')['complete'],'Recovered retry was mistaken for final failed collection'
   missing=scenario('missing','2026-01-15','2026-01-22',[doc('ZZ8642C1')]);missing['transport_pages']=[]
   mr=s.run_monitor_once(m,missing)['run_id'];drive(s,mr)
   assert not cycle_state(s,m,'missing')['complete'] and not cycle_state(s,m,'missing')['documents'],'Unqueried/missing response advanced watermark'
   return 'Collection follows executed queries, exact scenario replay, and actual retry outcome'
  finally:s.close()


def updated_profile_policy():
 with tempfile.TemporaryDirectory() as tmp:
  s=InvestigationService(tmp)
  try:
   m=s.create_monitor(P,MS,R)['monitor_id'];private=dict(P,rule_version='private-rule',visibility='confidential',scope='PRIVATE_PROFILE_8642')
   try:s.update_monitor_profile(m,private)
   except HarnessError:return 'Unauthorized profile update was rejected before activation'
   try:r=s.run_monitor_once(m,scenario('private','2026-01-01','2026-01-08',[doc('ZZ8642A1')]))
   except HarnessError:return 'Updated confidential profile blocked before model task creation'
   pending=s.get_pending_tasks(r['run_id']);assert not pending and 'PRIVATE_PROFILE_8642' not in json.dumps(pending),'Updated private profile bypassed executor policy'
   assert s.status(r['run_id'])['budget']['reserved_source_calls']==0
   return 'Updated profile produces policy-blocked run without secret task payload'
  finally:s.close()


def saved_baseline():
 with tempfile.TemporaryDirectory() as tmp:
  s=InvestigationService(tmp)
  try:
   baseline=doc('COMPANY-PUBLIC-BASE','baseline-v1',published='2020-01-01');baseline['text']='SYNTHETIC company baseline for violet scope.'
   m=s.create_monitor(P,MS,R,{'references':[baseline]})['monitor_id'];baseline['text']='Mutated caller object after create'
   sc=scenario('baseline-cycle','2026-01-01','2026-01-08',[doc('ZZ8642A1')]);del sc['references']
   run=s.run_monitor_once(m,sc)['run_id'];planning=s.get_pending_tasks(run)[0]
   ev=planning['payload']['baseline_evidence'];assert len(ev)==1 and ev[0]['version_id']=='baseline-v1' and ev[0]['text']=='SYNTHETIC company baseline for violet scope.','Configured baseline was dropped or changed'
   before=s.get_pending_tasks(run);s.close();s=InvestigationService(tmp);assert s.get_pending_tasks(run)==before
   return 'Configured company baseline persists across new-source cycles and restart'
  finally:s.close()

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--source-root',type=Path);p.add_argument('--checkpoint',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 if a.source_root:sys.path.insert(0,str(a.source_root.resolve()/'src'))
 socket.socket.connect=lambda *_a,**_k:(_ for _ in ()).throw(AssertionError('No external network'))
 from research_harness.investigation import InvestigationService
 from research_harness.errors import HarnessError
 checks=[]
 for name,fn in [('C3-public-monitor-review',multi),('C3-backlog-and-source-gap',backlog_and_failure),('C3-cumulative-budget',cumulative_budget),('C3-actual-collection',actual_collection),('M01-updated-profile-policy',updated_profile_policy),('M02-saved-baseline',saved_baseline)]:
  try:checks.append({'id':name,'status':'passed','detail':fn()})
  except Exception as e:
   import traceback
   checks.append({'id':name,'status':'failed','type':type(e).__name__,'detail':str(e),'trace':traceback.format_exc()})
 result={'checkpoint':a.checkpoint,'synthetic':True,'scope':'Public service monitoring and review through real graph; offline deterministic host','checks':checks};a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False));sys.exit(0 if all(x['status']=='passed' for x in checks) else 1)
