"""Independent frozen-data to renderer checks; synthetic only."""
import argparse, copy, csv, json, sys, tempfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--source-root',required=True,type=Path);p.add_argument('--checkpoint',required=True);p.add_argument('--output',required=True,type=Path)
a=p.parse_args();sys.path.insert(0,str(a.source_root.resolve()/'src'))
from research_harness.investigation_report_data import build_report_data,validate_claims
from research_harness.investigation_reporting import export_reports
from research_harness.errors import HarnessError
S={'research_question':'SYNTHETIC compare supplied indigo separator records','report_targets':['technical_report','literature_review']}
E=[{'evidence_id':'EA8642','document_id':'docA','version_id':'v1','locator':{'kind':'paragraph','value':'1'},'text':'SYNTHETIC A conductivity is 12 mS/cm at 20 C.'},{'evidence_id':'EB8642','document_id':'docB','version_id':'v1','locator':{'kind':'paragraph','value':'2'},'text':'SYNTHETIC B conductivity is 12 mS/cm at 80 C.'}]
F=[{'finding_id':'fA','finding':E[0]['text'],'evidence_ids':['EA8642'],'value':12,'unit':'mS/cm','conditions':'20 C'},{'finding_id':'fB','finding':E[1]['text'],'evidence_ids':['EB8642'],'value':12,'unit':'mS/cm','conditions':'80 C'}]
C=[{'claim_id':'claimA','claim':E[0]['text'],'finding_refs':[0],'evidence_refs':['EA8642'],'quote':'A conductivity is 12 mS/cm at 20 C.','document_id':'docA','version_id':'v1'}]
SEC=[{'deliverable_type':kind,'language':lang,'section_id':'results','title':title,'body':body,'claim_ids':['claimA']} for kind in S['report_targets'] for lang,title,body in [('en','Synthetic findings','SYNTHETIC A reports 12 mS/cm at 20 C; conclusions are limited to supplied evidence.'),('zh','合成资料分析','合成资料 A 记录了 20 C 条件下 12 mS/cm；本结果仅用于框架验证。'),('ja','合成資料の分析','合成資料 A は 20 C における 12 mS/cm を記載しています。これは枠組みの検証用です。')]]
V={'status':'supported','conclusion':'SYNTHETIC provided record A is supported','supported_claim_refs':[0]}
def build(e=None,f=None,c=None,sections=None,v=None,issues=None):return build_report_data('independent-builder',copy.deepcopy(S),copy.deepcopy(E if e is None else e),copy.deepcopy(F if f is None else f),copy.deepcopy(C if c is None else c),copy.deepcopy(SEC if sections is None else sections),copy.deepcopy(V if v is None else v),[{'title':'SYNTHETIC record A','citation_key':'syntheticA','type':'article'}],{'complete':True},issues or [])
checks=[]
def check(name,fn):
 try:r=fn();checks.append({'id':name,'status':'passed','detail':r})
 except Exception as e:checks.append({'id':name,'status':'failed','type':type(e).__name__,'detail':str(e)[:850]})
def normal():
 d=build();assert d['validation']['outcome']=='completed' and d['claims'][0]['verification']=='verified','supported public result was rejected'
 assert d['synthetic'] is True,'P1 synthetic marker lost because spec has no runtime mode'
 with tempfile.TemporaryDirectory() as t:
  r=export_reports(t,'independent-builder',d);assert r['status']=='completed'
  md=[x for x in r['artifacts'] if x['format']=='markdown'];assert len(md)==6
  comparison=next(x for x in r['artifacts'] if x['format']=='comparison_csv');text=(Path(t)/comparison['path']).read_text(encoding='utf-8');assert 'EA8642' in text and 'EB8642' in text,'CSV dropped evidence mapping'
  return {'reports':6,'languages':sorted({x['language'] for x in md})}
def evidence_binding():
 c=copy.deepcopy(C);c[0].update(evidence_refs=['EB8642'],quote='B conductivity is 12 mS/cm at 80 C.',document_id='docB')
 d=build(c=c);assert d['validation']['outcome']=='partial' and not d['sections'],'Claim mixed finding A with unrelated evidence B'
 return 'Cross-finding/evidence binding rejected'
def unsupported():
 v=dict(V,supported_claim_refs=[]);d=build(v=v);assert d['validation']['outcome']=='partial' and not d['sections']
 with tempfile.TemporaryDirectory() as t:
  r=export_reports(t,'unsupported',d);assert r['status']=='partial'
  assert not [x for x in r['artifacts'] if x['format'] in ('markdown','html')]
 return 'Unsupported content remains draft and can export diagnostics'
def empty_and_unknown_sections():
 for refs in ([],['unknown-claim']):
  ss=copy.deepcopy(SEC);ss[0]['claim_ids']=refs;ss[0]['body']='UNSUPPORTED_BODY_8642'
  d=build(sections=ss);assert d['validation']['outcome']=='partial'
  assert not any('UNSUPPORTED_BODY_8642' in x['body'] for x in d['sections'])
 return 'Unknown or empty claim support cannot produce completed body'
def conditions():
 for unknown in (False,True):
  fs=copy.deepcopy(F);c=copy.deepcopy(C);c[0]['finding_refs']=[0,1]
  if unknown:
   for f in fs:f['conditions']=None
  d=build(f=fs,c=c);assert d['validation']['outcome']=='partial' and not d['sections'],'Conflicting/missing conditions permitted deterministic comparison'
 return 'Different and unknown conditions remain unresolved'
def prior_issue():
 d=build(issues=[{'code':'RH_SOURCE_FORBIDDEN','status':'open','message':'One source failed'}]);assert d['validation']['outcome']=='partial','Source failure lost in report outcome'
 return 'Upstream incompleteness remains visible'
def invalid_quote():
 for update in ({'quote':'Paraphrased invented quotation'},{'version_id':'another-version'},{'finding_refs':[]}):
  c=copy.deepcopy(C);c[0].update(update)
  try:d=build(c=c)
  except HarnessError:continue
  assert d['validation']['outcome']=='partial' and not d['sections']
 return 'Invalid quotation, version and empty finding refs are withheld'
for name,fn in [('O02-builder-renderer',normal),('F10-evidence-binding',evidence_binding),('O03-unsupported-export',unsupported),('O03-section-support',empty_and_unknown_sections),('F10-condition-boundary',conditions),('F06-upstream-partial',prior_issue),('F10-quote-version',invalid_quote)]:check(name,fn)
r={'checkpoint':a.checkpoint,'synthetic':True,'scope':'Frozen data and renderer combination; service integration remains separate','checks':checks};a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(r,ensure_ascii=False));raise SystemExit(0 if all(x['status']=='passed' for x in checks) else 1)
