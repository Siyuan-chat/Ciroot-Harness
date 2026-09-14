"""Independent synthetic public monitor/review lifecycle; no scheduler or live API."""
import argparse,copy,json,socket,sys,tempfile
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
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--source-root',type=Path);p.add_argument('--checkpoint',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 if a.source_root:sys.path.insert(0,str(a.source_root.resolve()/'src'))
 socket.socket.connect=lambda *_a,**_k:(_ for _ in ()).throw(AssertionError('No external network'))
 from research_harness.investigation import InvestigationService
 from research_harness.errors import HarnessError
 checks=[]
 for name,fn in [('C3-public-monitor-review',multi),('C3-backlog-and-source-gap',backlog_and_failure)]:
  try:checks.append({'id':name,'status':'passed','detail':fn()})
  except Exception as e:
   import traceback
   checks.append({'id':name,'status':'failed','type':type(e).__name__,'detail':str(e),'trace':traceback.format_exc()})
 result={'checkpoint':a.checkpoint,'synthetic':True,'scope':'Public service monitoring and review through real graph; offline deterministic host','checks':checks};a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False));sys.exit(0 if all(x['status']=='passed' for x in checks) else 1)
