"""Independent lifecycle checks; all records are synthetic, never scientific evidence."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path
from research_harness.rag import RagLibrary, RagError

p=argparse.ArgumentParser()
p.add_argument('--root',required=True)
a=p.parse_args()
root=Path(a.root).resolve(); root.mkdir(parents=True,exist_ok=True)
if (root/'workspace').exists(): raise SystemExit('Use a fresh output directory')
source=root/'source.txt'; catalog=root/'catalog.json'
source.write_text('Synthetic fixture. Alpha membrane crosslinking controls swelling. No scientific measurements.\n',encoding='utf-8')
catalog.write_text(json.dumps({'records':[{'file':source.name,'title':'Synthetic lifecycle fixture','doi':'fixture:lifecycle','year':2026,'type':'synthetic'}]}),encoding='utf-8')
checks={}; detail={}
def check(name,value):
    checks[name]=bool(value); print(name,bool(value),flush=True)
def invalid(name,fn,code='RH_RAG_INVALID_INPUT'):
    try: fn(); check(name,False)
    except RagError as e: check(name,e.code==code)
    except Exception as e: detail[name]=type(e).__name__;check(name,False)

with RagLibrary(root/'workspace') as lib:
    first=lib.import_library(catalog); detail['first']=first
    check('first_import',first['imported']==1 and first['failed']==0)
    hit=lib.search_evidence('crosslinking swelling')['items'][0]
    old_id=hit['evidence_id']; old_version=hit['version_id']; old_source=Path(hit['source_path']); old_hash=hashlib.sha256(old_source.read_bytes()).hexdigest()
    before=lib.get_library_status()
    repeat=lib.import_library(catalog);detail['repeat']=repeat
    check('repeat_reuses',repeat['reused']==1 and repeat['failed']==0 and repeat['imported']==0)
    after=lib.get_library_status()
    check('repeat_no_growth',all(before[k]==after[k] for k in ('document_count','version_count','evidence_count')))
    check('status_ready',after['indexed_document_count']==1 and after['failed_document_count']==0 and after['index_status']=='ready')
    invalid('bad_year',lambda:lib.search_evidence('membrane',filters={'year_min':{}}))
    invalid('unknown_filter',lambda:lib.search_evidence('membrane',filters={'unknown':True}))
    invalid('bad_top_k',lambda:lib.search_evidence('membrane',top_k=0))
    invalid('unknown_context',lambda:lib.get_evidence_context('missing'),'RH_RAG_NOT_FOUND')
    check('doi_string_filter',bool(lib.search_evidence('membrane',filters={'doi':'fixture:lifecycle'})['items']))
    check('scope_filter_excludes',not lib.search_evidence('membrane',filters={'document_ids':['missing']})['items'])
    source.write_text('Synthetic revision. Beta membrane reinforcement controls swelling. No scientific measurements.\n',encoding='utf-8')
    revised=lib.import_library(catalog);detail['revised']=revised
    check('revision_import',revised['imported']==1 and revised['failed']==0)
    status=lib.get_library_status(); detail['status']=status
    check('revision_counts',status['document_count']==1 and status['version_count']==2)
    latest=lib.search_evidence('membrane')['items']
    check('latest_default',bool(latest) and all(x['version_id']!=old_version for x in latest))
    old=lib.search_evidence('membrane',filters={'version_ids':[old_version]})['items']
    check('old_version_filter',bool(old) and all(x['version_id']==old_version for x in old))
    ctx=lib.get_evidence_context(old_id)['items']
    check('old_context_preserved',any(x['evidence_id']==old_id and 'Alpha' in x['text'] for x in ctx))
    check('old_source_preserved',hashlib.sha256(old_source.read_bytes()).hexdigest()==old_hash)

with RagLibrary(root/'workspace',embedding_model='not-a-real-model') as lib:
    invalid('config_mismatch_search',lambda:lib.search_evidence('membrane'),'RH_RAG_CONFIG_MISMATCH')
    try:
        result=lib.import_library(catalog);detail['mismatch_import']=result
        check('config_mismatch_import',result['reused']==0 and result['imported']==0 and any(e.get('code')=='RH_RAG_CONFIG_MISMATCH' for e in result['errors']))
    except RagError as e: check('config_mismatch_import',e.code=='RH_RAG_CONFIG_MISMATCH')
    except Exception as e:detail['mismatch_import']=type(e).__name__;check('config_mismatch_import',False)

from qdrant_client import QdrantClient
corrupt=root/'index-fault-fixture'
shutil.copytree(root/'workspace',corrupt)
owner=QdrantClient(path=str(corrupt/'qdrant'))
try:
    with RagLibrary(corrupt) as lib:
        invalid('busy_status',lib.get_library_status,'RH_RAG_BUSY')
        invalid('busy_search',lambda:lib.search_evidence('membrane'),'RH_RAG_BUSY')
    owner.delete_collection('evidence')
finally:
    owner.close()
with RagLibrary(corrupt) as lib:
    invalid('missing_vector_index',lambda:lib.search_evidence('membrane'),'RH_RAG_INDEX_INCOMPLETE')

(root/'results.json').write_text(json.dumps({'checks':checks,'details':detail},ensure_ascii=False,indent=2),encoding='utf-8')
print('PASS' if all(checks.values()) else 'FAIL',sum(checks.values()),len(checks),flush=True)
raise SystemExit(0 if all(checks.values()) else 1)
