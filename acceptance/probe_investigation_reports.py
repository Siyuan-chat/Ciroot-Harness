"""Independent report acceptance using synthetic facts, with no model/network use."""
import argparse, copy, hashlib, json, sys, tempfile
from pathlib import Path

p=argparse.ArgumentParser(); p.add_argument('--source-root',type=Path,required=True); p.add_argument('--checkpoint',required=True); p.add_argument('--output',type=Path,required=True)
a=p.parse_args();sys.path.insert(0,str(a.source_root.resolve()/'src'))
from research_harness.investigation_reporting import export_reports
from research_harness.errors import HarnessError
D={'synthetic':True,'report_version':'v1','research_question':'SYNTHETIC Meridian separators',
   'report_targets':['technical_report','literature_review'],'findings':[],
   'evidence':[{'evidence_id':'ev-8642','document_id':'doc-8642','version_id':'rev-1','locator':{'kind':'physical_page','value':3},'text':'SYNTHETIC Indigo separator operates at 20 C.'}],
   'claims':[{'claim_id':'c-8642','verification':'verified','quote':'Indigo separator operates at 20 C.','evidence_refs':['ev-8642']}],
   'sections':[],'bibliography':[{'type':'article','citation_key':'meridian8642','title':'SYNTHETIC Meridian record','year':'2026'}],'coverage':{},'issues':[]}
for kind in D['report_targets']:
 for lang,body in [('en','SYNTHETIC Indigo separator operates at 20 C.'),('zh-CN','合成示例：Indigo 隔膜的条件为 20 C。'),('ja','合成例：Indigo セパレータの条件は 20 C です。')]:
  for n in (1,2):D['sections'].append({'deliverable_type':kind,'language':lang,'section_id':f's{n}','title':f'Meridian {n}','body':body,'claim_ids':['c-8642']})
checks=[]
def test(name,fn):
 try:detail=fn();checks.append({'id':name,'status':'passed','detail':detail})
 except Exception as e:checks.append({'id':name,'status':'failed','type':type(e).__name__,'detail':str(e)[:800]})
def basic():
 with tempfile.TemporaryDirectory() as t:
  r=export_reports(t,'ind-report',copy.deepcopy(D),['en']);assert r['status']=='completed',r['issues']
  reports=[x for x in r['artifacts'] if x['format']=='markdown'];assert len(reports)==2,'Expected two assembled report files'
  for x in reports:
   text=(Path(t)/x['path']).read_text(encoding='utf-8');assert all(s in text for s in ('SYNTHETIC','ev-8642','doc-8642','rev-1','20 C','Meridian 1','Meridian 2')),'Missing synthetic label, source locator or assembled sections'
  return {'reports':len(reports)}
def unsupported():
 d=copy.deepcopy(D);d['sections'][0]['claim_ids']=[];d['sections'][0]['body']='UNSUPPORTED_MARKER_8642: conductivity is 100 times better.'
 with tempfile.TemporaryDirectory() as t:
  r=export_reports(t,'unbacked',d,['en']);assert r['status']=='partial'
  texts=''.join((Path(t)/x['path']).read_text(encoding='utf-8') for x in r['artifacts'] if x['format'] in ('markdown','html'))
  assert 'UNSUPPORTED_MARKER_8642' not in texts,'Unsupported body was exported as final report'
def duplicate():
 d=copy.deepcopy(D);d['evidence'].append(dict(d['evidence'][0],document_id='another-document'))
 with tempfile.TemporaryDirectory() as t:
  try:export_reports(t,'duplicate',d,['en'])
  except HarnessError:return 'duplicate identity rejected'
  raise AssertionError('Duplicate evidence identity was silently accepted')
def language():
 d=copy.deepcopy(D);bad='../escape';d['sections'][0]['language']=bad
 with tempfile.TemporaryDirectory() as t:
  try:export_reports(t,'unsafe-language',d,[bad])
  except HarnessError:return 'unsafe language rejected'
  raise AssertionError('Unsafe language not rejected with structured error')
def retry():
 with tempfile.TemporaryDirectory() as t:
  r=export_reports(t,'retry',copy.deepcopy(D),['en']);x=next(x for x in r['artifacts'] if x['format']=='markdown');f=Path(t)/x['path'];f.unlink()
  r2=export_reports(t,'retry',copy.deepcopy(D),['en']);assert f.exists(),'Repeat export falsely succeeded with missing artifact'
  assert hashlib.sha256(f.read_bytes()).hexdigest()==x['sha256']
  return r2['status']
def frozen():
 with tempfile.TemporaryDirectory() as t:
  r=export_reports(t,'frozen',copy.deepcopy(D),['en']);before={x['path']:hashlib.sha256((Path(t)/x['path']).read_bytes()).hexdigest() for x in r['artifacts']}
  export_reports(t,'frozen',copy.deepcopy(D),['zh-CN','ja'])
  assert all(hashlib.sha256((Path(t)/path).read_bytes()).hexdigest()==sha for path,sha in before.items()),'Adding languages mutated previous artifacts'
  d=copy.deepcopy(D);d['sections'][0]['body']='Changed frozen content'
  try:export_reports(t,'frozen',d,['en'])
  except HarnessError:return 'frozen artifact hashes preserved'
  raise AssertionError('Changed facts accepted under same version')
for name,fn in [('O-dual-reports',basic),('O-unsupported-body',unsupported),('O-duplicate-identity',duplicate),('O-safe-language',language),('O-export-retry',retry),('O-frozen-language-extension',frozen)]:test(name,fn)
out={'checkpoint':a.checkpoint,'synthetic':True,'checks':checks};a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(out,ensure_ascii=False));raise SystemExit(0 if all(c['status']=='passed' for c in checks) else 1)
