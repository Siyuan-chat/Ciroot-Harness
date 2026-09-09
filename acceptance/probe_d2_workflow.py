"""D2 checkpoint probes; no real API or scientific data."""
import argparse,json,sys,tempfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--output',required=True);a=p.parse_args()
source=Path(a.source).resolve();sys.path.insert(0,str(source/'src'))
from research_harness.service import Harness
results={}
with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp);sp=root/'spec.json';fp=root/'fixture.json'
    spec=json.loads((source/'examples/polymer-design.draft.json').read_text(encoding='utf-8'));spec.update(status='ready',unresolved_questions=[])
    sp.write_text(json.dumps(spec),encoding='utf-8')
    fp.write_text(json.dumps({'candidates':[{'id':'synthetic-a','quote':'Synthetic text only.','locator':'line:1'},{'id':'synthetic-b','quote':'Unknown evidence.','locator':'line:1','missing':True}]}),encoding='utf-8')
    calls=[];events=[]
    def model(*args,**kwargs):calls.append(True);return {'disposition':'watch'}
    h=Harness(root/'workspace')
    out=h.run_fixture(sp,fp,model_adapter=model,on_progress=events.append)
    results['stages_observed']=[e.get('stage') for e in events]
    results['model_adapter_called']=bool(calls)
    results['run_result']=out
    results['persisted_run_count']=len(h.status())
    results['persisted_issue_count']=len(h.review_list())
    results['progress_has_run_and_status']=all('run_id' in e and 'status' in e for e in events)
    spec.update(revision=2,status='draft',unresolved_questions=['synthetic unresolved requirement']);sp.write_text(json.dumps(spec),encoding='utf-8')
    try:
        draft=h.run_fixture(sp,fp)
        results['draft_run_rejected']=False;results['draft_run_outcome']=draft['outcome']
    except Exception as exc:results['draft_run_rejected']=True;results['draft_error_type']=type(exc).__name__
    h.store.close()
output=Path(a.output);output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(results,ensure_ascii=False,indent=2))
passed=results['model_adapter_called'] and results['persisted_run_count']>0 and results['persisted_issue_count']>0 and results['progress_has_run_and_status'] and results['draft_run_rejected']
raise SystemExit(0 if passed else 1)
