"""Independent D19 contract resource checks using full task result envelopes."""
import argparse,copy,json,sys
from pathlib import Path
from jsonschema import Draft202012Validator
p=argparse.ArgumentParser();p.add_argument('--source-root',required=True,type=Path);p.add_argument('--checkpoint',required=True);p.add_argument('--output',required=True,type=Path)
a=p.parse_args();sys.path.insert(0,str(a.source_root.resolve()/'src'))
from research_harness.investigation_contracts import get_task_schema,validate_spec,validate_runtime
from research_harness.errors import HarnessError
S={'status':'ready','project_id':'synthetic-contract','revision':1,'research_question':'SYNTHETIC compare separator records','report_targets':['technical_report','literature_review'],'references':[]}
R={'mode':'host','data_mode':'synthetic','budget':{'max_tasks':8,'max_source_calls':6}}
f={'finding_id':'F','finding':'SYNTHETIC direct source observation','evidence_ids':['E'],'value':12,'unit':'mS/cm','conditions':'20 C'}
c={'claim_id':'C','claim':'SYNTHETIC source observation','finding_refs':[0],'evidence_refs':['E'],'quote':'SYNTHETIC original','document_id':'D','version_id':'v1'}
section={'deliverable_type':'technical_report','language':'en','section_id':'results','title':'Synthetic results','body':'SYNTHETIC source observation.','claim_ids':['C']}
results={'planning':{'search_plan':{'queries':[{'query_id':'Q','source':'synthetic-paper','query':'indigo separator','input_refs':[],'parent_query_id':None}]}},'paper_search':{'candidates':[{'document_id':'D','relevance':'relevant','reason':'SYNTHETIC scope'}]},'patent_search':{'candidates':[]},'evidence_analysis':{'findings':[f]},'business_judgment':{'judgments':[{'document_id':'D','relevance':'uncertain','human_review_required':True,'reason':'SYNTHETIC evidence incomplete'}]},'synthesis':{'claims':[c]},'writing':{'sections':[section]},'verification':{'verification':{'status':'supported','conclusion':'SYNTHETIC supported record','supported_claim_refs':[0]}}}
checks=[]
def check(name,fn):
 try:r=fn();checks.append({'id':name,'status':'passed','detail':r})
 except Exception as e:checks.append({'id':name,'status':'failed','type':type(e).__name__,'detail':str(e)[:900]})
def task_shapes():
 for role,value in results.items():
  schema=get_task_schema(role);Draft202012Validator.check_schema(schema);v=Draft202012Validator(schema);v.validate(value)
  for bad in ({},[],{'summary':'A nonempty generic object'}):assert not v.is_valid(bad),role+' accepted wrong envelope'
  extra=dict(value,unrecognized='unexpected');assert not v.is_valid(extra),role+' accepted extra output field'
 return {'roles':list(results)}
def numeric_types():
 for role,value in [('synthesis',{'claims':[dict(c,finding_refs=[True])]}),('verification',{'verification':dict(results['verification']['verification'],supported_claim_refs=[True])}),('evidence_analysis',{'findings':[dict(f,value=True)]})]:
  assert not Draft202012Validator(get_task_schema(role)).is_valid(value),'Boolean was accepted as numeric/index'
 return 'JSON numeric semantics preserved'

def nested_fields():
 for role,original in results.items():
  value=copy.deepcopy(original)
  if role=='patent_search':value=copy.deepcopy(results['paper_search'])
  inner=next(iter(value.values()))
  if role=='planning':inner=inner['queries'][0]
  elif isinstance(inner,list):inner=inner[0]
  validator=Draft202012Validator(get_task_schema(role))
  for field in list(inner):
   saved=inner.pop(field)
   assert not validator.is_valid(value),role+' accepted missing inner '+field
   inner[field]=saved
  inner['unexpected_inner']='ignored constraint'
  assert not validator.is_valid(value),role+' accepted extra inner field'
 return 'All role item fields are required and constrained'
def spec_fields():
 validate_spec(copy.deepcopy(S));validate_spec(dict(S,status='draft'))
 for value in [dict(S,report_targets=[None,123]),dict(S,report_targets=['unsupported-target']),dict(S,criteria=[{'value':12}]),dict(S,research_question='   ')]:
  try:validate_spec(value)
  except HarnessError:pass
  else:raise AssertionError('Invalid ready/spec field was accepted: '+json.dumps(value))
 good=dict(S,criteria=[{'value':12,'unit':'mS/cm','conditions':'20 C'}],user_notes='Preserve this supplied context');before=copy.deepcopy(good);validate_spec(good);assert good==before
 return 'Targets, quantitative units and context preservation checked'
def runtime_fields():
 validate_runtime(copy.deepcopy(R))
 bads=[dict(R,data_policy={'allowed_models':'approved'}),dict(R,data_policy={'allow_query_egress':'false'}),dict(R,budget={'max_tasks':True}),dict(R,budget={'max_tasks':0}),dict(R,budget={'max_tasks':8,'silently_ignored_limit':2})]
 for value in bads:
  try:validate_runtime(value)
  except HarnessError:pass
  else:raise AssertionError('Unsafe/ignored runtime field was accepted: '+json.dumps(value))
 return 'Policy types and supported budget fields enforced'
def copies():
 root=a.source_root/'schemas';pack=a.source_root/'src/research_harness/schemas';files=list(root.glob('investigation-*.json'));assert len(files)>=3
 for x in files:assert x.read_bytes()==(pack/x.name).read_bytes(),x.name+' differs in package'
 return {'resources':len(files)}
for name,fn in [('C2-eight-task-envelopes',task_shapes),('C2-nested-fields',nested_fields),('C2-numeric-types',numeric_types),('F01-spec-contract',spec_fields),('M01-runtime-policy-contract',runtime_fields),('F12-schema-resources',copies)]:check(name,fn)
r={'checkpoint':a.checkpoint,'synthetic':True,'checks':checks};a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(r,ensure_ascii=False));raise SystemExit(0 if all(x['status']=='passed' for x in checks) else 1)
