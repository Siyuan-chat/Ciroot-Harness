"""10592ca independent tests; all API traffic replaced with synthetic protocol fixtures."""
import json, os, sys, tempfile
from pathlib import Path
from unittest.mock import Mock, patch
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'.local/acceptance/10592ca'; SOURCE=BASE/'source'
sys.path.insert(0,str(SOURCE/'src'))
from research_harness.service import Harness
from research_harness.providers import openalex_search, epo_search, SourceError
import requests
results={}
with tempfile.TemporaryDirectory(dir=BASE) as temp:
    ws=Path(temp)
    s=json.loads((SOURCE/'examples/polymer-design.draft.json').read_text(encoding='utf-8'));s.update(status='ready',unresolved_questions=[])
    r=json.loads((SOURCE/'examples/runtime.example.json').read_text(encoding='utf-8'));r['llm'].update(model='synthetic-local',local=True);r['retrieval']['embedding']['model']='SYNTHETIC_UNAVAILABLE'
    for cfg in r['sources'].values():cfg['enabled']=False
    sp=ws/'spec.json';rp=ws/'runtime.json';sp.write_text(json.dumps(s),encoding='utf-8');rp.write_text(json.dumps(r),encoding='utf-8')
    h=Harness(ws/'workspace')
    try:h.run(sp,rp);results['F09_missing_components_blocked']=False
    except Exception as exc:results['F09_missing_components_blocked']=type(exc).__name__=='PreflightError'
    results['F09_runs_created']=len(h.store.runs());h.store.close()
with patch.dict(os.environ,{'PROBE_OA':'synthetic-sentinel','PROBE_EPO_K':'synthetic-key','PROBE_EPO_S':'synthetic-secret'}):
    response=Mock(ok=True,status_code=200)
    response.json.return_value={'meta':{'count':3,'page':1,'per_page':2},'results':[{'id':'W1'},{'id':'W2'}]}
    with patch('research_harness.providers.requests.request',return_value=response) as call:
        out=openalex_search('synthetic', 'PROBE_OA',2,1)
        results['openalex_truncated_page']={'completeness':out['completeness'],'continuation':out['continuation'],'cursor_requested':call.call_args.kwargs['params'].get('cursor'),'candidate_count':len(out['candidates'])}
    response=Mock(ok=True,status_code=200,text='<synthetic/>')
    with patch('research_harness.providers.requests.request',return_value=response) as call:
        out=epo_search('ti=synthetic','PROBE_EPO_K','PROBE_EPO_S',2,1)
        results['epo_auth']={'request_count':call.call_count,'methods':[x.args[0] for x in call.call_args_list],'authorization_sent':any('Authorization' in (x.kwargs.get('headers') or {}) for x in call.call_args_list),'candidate_field_present':'candidates' in out}
    cases={'list':[], 'nonlist_results':{'results':'bad'}}
    results['invalid_payloads']={}
    for name,payload in cases.items():
        response=Mock(ok=True,status_code=200);response.json.return_value=payload
        with patch('research_harness.providers.requests.request',return_value=response):
            try:openalex_search('synthetic','PROBE_OA',2,1);results['invalid_payloads'][name]='ACCEPTED'
            except Exception as exc:results['invalid_payloads'][name]={'type':type(exc).__name__,'kind':getattr(exc,'kind',None)}
    response=Mock(ok=True,status_code=200);response.json.side_effect=requests.exceptions.JSONDecodeError('invalid','not json',0)
    with patch('research_harness.providers.requests.request',return_value=response):
        try:openalex_search('synthetic','PROBE_OA',2,1);results['invalid_payloads']['bad_json']='ACCEPTED'
        except Exception as exc:results['invalid_payloads']['bad_json']={'type':type(exc).__name__,'kind':getattr(exc,'kind',None)}
    with patch('research_harness.providers.requests.request',side_effect=requests.ConnectionError('request failed https://api.openalex.org/works?api_key=synthetic-sentinel')):
        try:openalex_search('synthetic','PROBE_OA',2,1)
        except Exception as exc:results['credential_in_public_error']='synthetic-sentinel' in str(exc)
(BASE/'acceptance-probes.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(results,ensure_ascii=False,indent=2))
violations=[not results['F09_missing_components_blocked'],results['F09_runs_created']!=0,results['openalex_truncated_page']['completeness']=='complete',not results['epo_auth']['authorization_sent'],results['credential_in_public_error'],any(isinstance(v,dict) and v.get('kind')!='invalid_response' for v in results['invalid_payloads'].values())]
raise SystemExit(1 if any(violations) else 0)
