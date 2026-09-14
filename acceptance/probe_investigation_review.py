"""Independent synthetic checks of relatedness, human routing and decision history."""
import argparse, copy, json, sys, tempfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--source-root',required=True,type=Path);p.add_argument('--checkpoint',required=True);p.add_argument('--output',required=True,type=Path)
a=p.parse_args();sys.path.insert(0,str(a.source_root.resolve()/'src'))
from research_harness.investigation_review import ReviewStore
from research_harness.errors import HarnessError
checks=[]
def check(name,fn):
 try:r=fn();checks.append({'id':name,'status':'passed','detail':r})
 except Exception as e:checks.append({'id':name,'status':'failed','type':type(e).__name__,'detail':str(e)[:800]})
def judgment(relevance='relevant',human=True,reason='SYNTHETIC Meridian scope evidence'):
 return {'relevance':relevance,'human_review_required':human,'reason':reason}
def record(s,j=None,company='meridian',doc='patent-8642',version='v1',forced=None):
 return s.record_judgment('monitor-8642',company,doc,version,'rule1',j or judgment(),['evidence-8642'],forced)
def namespace():
 with tempfile.TemporaryDirectory() as t:
  s=ReviewStore(t)
  try:
   ids=[record(s,company=c,doc=d)['issue_id'] for c,d in [('meridian','patent-8642'),('other-company','patent-8642'),('meridian','patent-8643')]]
   rows=s.review_list();assert len(set(ids))==3 and len(rows)==3
   assert all(any(e['kind']=='model' for e in r['events']) for r in rows),'Identical results lost another document/company history'
   return {'distinct_issues':len(ids)}
  finally:s.close()
def routing():
 with tempfile.TemporaryDirectory() as t:
  s=ReviewStore(t)
  try:
   r=record(s,judgment('uncertain',False));assert r['human_review_required'] is True
   r=record(s,judgment('irrelevant',False,'Changed model opinion'));assert r['status']=='open' and r['human_review_required'] is True,'Open issue was reported as requiring no human'
   f=record(s,judgment('irrelevant',False),doc='forced-patent',forced=['Missing independent claim evidence']);assert f['human_review_required'] is True
   clear=record(s,judgment('relevant',False),doc='clear-patent');assert clear['human_review_required'] is False
   return 'Independent relevance and effective human routing'
  finally:s.close()
def human_authority():
 with tempfile.TemporaryDirectory() as t:
  s=ReviewStore(t)
  try:
   r=record(s);issue=r['issue_id'];s.review_decide(issue,'irrelevant','SYNTHETIC human scope decision')
   r=record(s,judgment(reason='Same version, different model wording'))
   assert r['status']!='open' and r['relevance']=='irrelevant' and r['human_review_required'] is False,'Same-version model overwrote human decision'
   before=s.review_list();s.close();s=ReviewStore(t);assert s.review_list()==before
   r=record(s,judgment(reason='New source text requires review'),version='v2');assert r['status']=='open' and r['human_review_required'] is True
   assert any(e['kind']=='human' for e in s.review_list()[0]['events']),'Reopen erased human history'
   return 'Human authority survives restart; new version can reopen'
  finally:s.close()
def events():
 with tempfile.TemporaryDirectory() as t:
  s=ReviewStore(t)
  try:
   record(s);before=s.review_list();record(s);after=s.review_list();assert before==after,'Duplicate submission changed history'
   models=[e for e in before[0]['events'] if e['kind']=='model'];assert len(models)==1,'One model judgment produced duplicate events'
   assert 'judgment' in models[0] or 'original_judgment' in models[0],'History omits original model judgment'
   return 'One persistent model event per unique judgment'
  finally:s.close()
def errors():
 with tempfile.TemporaryDirectory() as t:
  s=ReviewStore(t)
  try:
   for fn in [lambda:record(s,{'relevance':'PRIVATE_8642','human_review_required':False,'reason':'bad'}),lambda:s.review_decide('absent','relevant')]:
    try:fn()
    except HarnessError as e:assert 'PRIVATE_8642' not in json.dumps(e.to_dict())
    else:raise AssertionError('Invalid input accepted')
   assert s.review_list()==[],'Invalid operations created issue state'
   return 'Safe structured errors, unchanged state'
  finally:s.close()
for name,fn in [('M01-review-namespace',namespace),('M05-effective-routing',routing),('M05-human-authority',human_authority),('M05-event-idempotence',events),('M05-safe-errors',errors)]:check(name,fn)
r={'checkpoint':a.checkpoint,'synthetic':True,'scope':'Review store; integrated monitoring remains separate','checks':checks};a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(r,ensure_ascii=False));raise SystemExit(0 if all(x['status']=='passed' for x in checks) else 1)
