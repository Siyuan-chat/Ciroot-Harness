"""Independent synthetic monitor persistence and multi-cycle probes."""
import argparse, copy, json, sys, tempfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--source-root',required=True,type=Path);p.add_argument('--checkpoint',required=True);p.add_argument('--output',required=True,type=Path)
a=p.parse_args();sys.path.insert(0,str(a.source_root.resolve()/'src'))
from research_harness.investigation_monitoring import MonitorStore
from research_harness.errors import HarnessError
checks=[]
P={'company_id':'meridian','rule_version':'r1','scope':'SYNTHETIC indigo separator'}
R={'mode':'host','data_mode':'synthetic','budget':{'max_cycles':10,'max_total_tasks':8}}
D=[{'document_id':'old','version':'v1','content_sha256':'old-content','published_at':'2020-01-01'}, {'document_id':'new','version':'v1','content_sha256':'new-content','published_at':'2026-01-03'}, {'document_id':'unknown','version':'v1','content_sha256':'unknown-content','published_at':None}]
def check(name,fn):
 try:r=fn();checks.append({'id':name,'status':'passed','detail':r})
 except Exception as e:checks.append({'id':name,'status':'failed','type':type(e).__name__,'detail':str(e)[:900]})
def cycle(s,m,key,start,end):return s.begin_cycle(m,key,start,end)['cycle_id']
def state(s,m,c):return next(x for x in s.status(m)['cycles'] if x['cycle_id']==c)
def create(s,r=None):return s.create(copy.deepcopy(P),{'name':'Independent synthetic monitoring'},copy.deepcopy(r or R))['monitor_id']
def multi():
 with tempfile.TemporaryDirectory() as t:
  s=MonitorStore(t)
  try:
   m=create(s);c1=cycle(s,m,'week1','2026-01-01','2026-01-08');s.record_collection(c1,copy.deepcopy(D),True,{'source_complete':True})
   st=state(s,m,c1);assert len(st['judgment_backlog'])==3
   flags={d['document_id']:d for d in st['documents']};assert not flags['old']['is_new_publication'] and flags['new']['is_new_publication'];assert flags['unknown']['published_at']=='unknown'
   for d in D:s.mark_judged(c1,d['document_id'],d['version'],'judgment-'+d['document_id'])
   c2=cycle(s,m,'week2','2026-01-08','2026-01-15');s.record_collection(c2,copy.deepcopy(D),True,{'source_complete':True});assert state(s,m,c2)['judgment_backlog']==[]
   c3=cycle(s,m,'week3','2026-01-15','2026-01-22');changed=[dict(D[0],version='v2',content_sha256='changed-old-content'),{'document_id':'late','version':'v1','content_sha256':'late-content','published_at':'2024-01-01'}]
   s.record_collection(c3,changed,True,{'source_complete':True});assert len(state(s,m,c3)['judgment_backlog'])==2
   assert not any(x['is_new_publication'] for x in state(s,m,c3)['documents'])
   before=s.status(m);s.close();s=MonitorStore(t);assert s.status(m)==before
   return {'cycles':3,'new_content_and_late_backlog':2,'restart':True}
  finally:s.close()
def frozen_rule():
 with tempfile.TemporaryDirectory() as t:
  s=MonitorStore(t)
  try:
   m=create(s);c1=cycle(s,m,'first','2026-01-01','2026-01-08');s.record_collection(c1,D[:1],True,{})
   s.update_profile(m,dict(P,rule_version='r2',scope='SYNTHETIC changed rule'))
   s.mark_judged(c1,'old','v1','decision-under-r1');assert state(s,m,c1)['judgment_backlog']==[],'Old cycle was judged under current rule instead of frozen rule'
   c2=cycle(s,m,'second','2026-01-08','2026-01-15');s.record_collection(c2,D[:1],True,{});assert len(state(s,m,c2)['judgment_backlog'])==1,'Rule change reused previous rule judgment'
   old=s.get_configuration(m,revision=1);assert 'r1' in json.dumps(old),'Old profile revision lost'
   return 'Frozen old rule and new-rule rejudgment preserved'
  finally:s.close()
def partial_and_replay():
 with tempfile.TemporaryDirectory() as t:
  s=MonitorStore(t)
  try:
   m=create(s);c=cycle(s,m,'partial','2026-01-01','2026-01-08');s.record_collection(c,D[:1],False,{'failed':['query-b']});assert state(s,m,c)['watermark'] is None
   assert cycle(s,m,'partial','2026-01-01','2026-01-08')==c
   s.record_collection(c,D,True,{'source_complete':True});before=s.status(m);s.record_collection(c,D,True,{'source_complete':True});assert s.status(m)==before,'Completed collection replay changed facts'
   for fn in [lambda:cycle(s,m,'partial','2026-01-01','2026-01-09'),lambda:s.record_collection(c,[dict(D[0],content_sha256='tampered')],True,{})]:
    try:fn()
    except HarnessError:pass
    else:raise AssertionError('Frozen cycle accepted changed facts')
   return 'Failed window remains incomplete; successful replay is stable'
  finally:s.close()
def budget_pause():
 with tempfile.TemporaryDirectory() as t:
  s=MonitorStore(t)
  try:
   r=copy.deepcopy(R);r['budget']={'max_cycles':1,'max_total_tasks':3};m=create(s,r);s.reserve_tasks(m,2);before=s.status(m)['budget'];s.close();s=MonitorStore(t);assert s.status(m)['budget']==before
   try:s.reserve_tasks(m,2)
   except HarnessError:pass
   else:raise AssertionError('Cross-cycle task budget exceeded')
   s.pause(m)
   try:cycle(s,m,'paused','2026-01-01','2026-01-08')
   except HarnessError:pass
   else:raise AssertionError('Paused monitor created new cycle')
   s.resume(m);c=cycle(s,m,'first','2026-01-01','2026-01-08');s.record_collection(c,[],True,{})
   try:cycle(s,m,'second','2026-01-08','2026-01-15')
   except HarnessError:pass
   else:raise AssertionError('Cross-cycle max_cycles exceeded')
   assert s.status(m)['budget']==before
   return 'Persistent task and cycle caps; explicit pause/resume'
  finally:s.close()
for name,fn in [('M03-three-cycles',multi),('M06-frozen-rule',frozen_rule),('M03-partial-replay',partial_and_replay),('F07-monitor-budget-pause',budget_pause)]:check(name,fn)
r={'checkpoint':a.checkpoint,'synthetic':True,'scope':'Monitor store only; actual graph/host integration remains separate','checks':checks};a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(r,ensure_ascii=False));raise SystemExit(0 if all(x['status']=='passed' for x in checks) else 1)
