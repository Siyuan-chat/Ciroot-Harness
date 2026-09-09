"""Offline source-protocol acceptance against a committed snapshot."""
import argparse,json,os,sys,traceback
from pathlib import Path
from unittest.mock import Mock,patch
p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--output',required=True);a=p.parse_args()
sys.path.insert(0,str(Path(a.source).resolve()/'src'))
from research_harness.providers import openalex_search,epo_search
import requests
checks={}
def response(payload=None,text=''):
    r=Mock(ok=True,status_code=200,text=text);r.json.return_value=payload;return r
with patch.dict(os.environ,{'PROBE_OA':'synthetic-sentinel','PROBE_EK':'synthetic-key','PROBE_ES':'synthetic-secret'}):
    pages=[response({'meta':{'count':2,'next_cursor':'NEXT'},'results':[{'id':'W1'}]}),response({'meta':{'count':2,'next_cursor':None},'results':[{'id':'W2'}]})]
    with patch('research_harness.providers.requests.request',side_effect=pages) as call:
        first=openalex_search('synthetic','PROBE_OA',1,1);second=openalex_search('synthetic','PROBE_OA',1,1,cursor=first['continuation'])
        cursors=[x.kwargs['params'].get('cursor') for x in call.call_args_list]
        checks['openalex_two_pages']={'passed':cursors==['*','NEXT'] and first['completeness']=='partial' and second['completeness']=='complete' and second['candidates'][0]['source_id']=='W2','requested_cursors':cursors}
    malformed={'missing_cursor_on_truncated_page':{'meta':{'count':3,'page':1,'per_page':2},'results':[{'id':'W1'},{'id':'W2'}]},'null_meta':{'meta':None,'results':[]},'invalid_candidate':{'meta':{'next_cursor':None},'results':[None]},'list_root':[]}
    for name,payload in malformed.items():
        with patch('research_harness.providers.requests.request',return_value=response(payload)):
            try:
                out=openalex_search('synthetic','PROBE_OA',2,1)
                checks[name]={'passed':False,'outcome':out.get('completeness')}
            except Exception as exc:checks[name]={'passed':getattr(exc,'kind',None)=='invalid_response','error_type':type(exc).__name__,'error_kind':getattr(exc,'kind',None)}
    xml='''<ops:world-patent-data xmlns:ops="http://ops.epo.org" xmlns:ex="http://www.epo.org/exchange"><ops:biblio-search total-result-count="1"><ops:search-result><ex:exchange-documents><ex:exchange-document country="EP" doc-number="1234567" kind="A1"><ex:bibliographic-data><ex:publication-reference><ex:document-id document-id-type="docdb"><ex:country>EP</ex:country><ex:doc-number>1234567</ex:doc-number><ex:kind>A1</ex:kind></ex:document-id></ex:publication-reference></ex:bibliographic-data></ex:exchange-document></ex:exchange-documents></ops:search-result></ops:biblio-search></ops:world-patent-data>'''
    with patch('research_harness.providers.requests.request',side_effect=[response({'access_token':'synthetic-token','expires_in':1199}),response(text=xml)]) as call:
        out=epo_search('ti=synthetic','PROBE_EK','PROBE_ES',2,1)
        calls=call.call_args_list
        checks['epo_auth']={'passed':len(calls)==2 and calls[0].args[0]=='POST' and calls[0].kwargs.get('data')=={'grant_type':'client_credentials'} and calls[0].kwargs.get('auth')==('synthetic-key','synthetic-secret') and calls[1].kwargs['headers'].get('Authorization')=='Bearer synthetic-token'}
        candidates=out['candidates'];serialized=json.dumps(candidates)
        checks['epo_publication_identity']={'passed':len(candidates)==1 and all(t in serialized for t in ('EP','1234567','A1')),'candidates':candidates}
        checks['epo_exhausted_page']={'passed':out['completeness']=='complete','completeness':out['completeness'],'continuation':out.get('continuation')}
    with patch('research_harness.providers.requests.request',side_effect=requests.ConnectionError('URL=https://api.openalex.org/works?api_key=synthetic-sentinel')):
        try:openalex_search('synthetic','PROBE_OA',2,1)
        except Exception as exc:
            rendered=''.join(traceback.format_exception(exc))
            checks['secret_safe_exception']={'passed':'synthetic-sentinel' not in rendered,'secret_in_public_message':'synthetic-sentinel' in str(exc),'secret_in_formatted_traceback':'synthetic-sentinel' in rendered}
result={'source_snapshot':str(Path(a.source).resolve()),'network_used':False,'synthetic':True,'checks':checks}
out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
raise SystemExit(0 if all(v['passed'] for v in checks.values()) else 1)
