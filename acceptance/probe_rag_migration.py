"""Independent model migration check using an explicitly synthetic legacy library."""
import argparse,hashlib,json,os,shutil
from pathlib import Path
from research_harness.rag import RagLibrary,RagError,DEFAULT_EMBEDDING_MODEL

p=argparse.ArgumentParser()
p.add_argument('--source-workspace',required=True)
p.add_argument('--root',required=True)
p.add_argument('--legacy-cache',required=True)
p.add_argument('--new-cache',required=True)
a=p.parse_args();root=Path(a.root).resolve();root.mkdir(parents=True,exist_ok=True)
workspace=root/'workspace'
if workspace.exists():raise SystemExit('Use a fresh output directory')
shutil.copytree(a.source_workspace,workspace)
checks={};detail={}
def check(name,value):
    checks[name]=bool(value);print(name,bool(value),flush=True)
def snapshot(lib):
    return {table:[tuple(row) for row in lib._db.execute(f'SELECT * FROM {table} ORDER BY 1')] for table in ['rag_documents','rag_versions','rag_evidence']}
def config(lib):return dict(lib._db.execute('SELECT key,value FROM rag_config'))
def denied(name,call,code):
    try:call();check(name,False)
    except RagError as exc:check(name,exc.code==code and 'PRIVATE_SENTINEL' not in json.dumps(exc.to_dict()))
    except Exception as exc:detail[name]=type(exc).__name__;check(name,False)

os.environ['RAG_MODEL_CACHE']=str(Path(a.new_cache).resolve())
with RagLibrary(workspace) as lib:
    before=snapshot(lib);old_config=config(lib)
    evidence=before['rag_evidence'];old_id=evidence[0][0]
    check('fixture_has_versions',len(before['rag_versions'])==2 and len(evidence)>=2)
    old_model=json.loads(old_config['index_fingerprint'])['embedding_model']
    check('status_reports_legacy',lib.get_library_status()['embedding_model']==old_model and old_model!=DEFAULT_EMBEDDING_MODEL)
    denied('ordinary_search_rejects_mismatch',lambda:lib.search_evidence('membrane'),'RH_RAG_CONFIG_MISMATCH')
    original_components=lib._components
    def broken_components(**kwargs):raise ValueError('PRIVATE_SENTINEL model initialization')
    lib._components=broken_components
    denied('initialization_error_safe',lib.rebuild_index,'RH_RAG_REBUILD_FAILED')
    lib._components=original_components
    check('initialization_failure_preserves_config',config(lib)==old_config)
    embedder,qdrant,_=lib._components(enforce_config=False)
    old_collections={x.name for x in qdrant.get_collections().collections}
    original_index=lib._index
    def fail_after_write(*args,**kwargs):
        original_index(*args,**kwargs)
        raise RagError('RH_RAG_REBUILD_FAILED','injected synthetic write failure')
    lib._index=fail_after_write
    denied('post_write_failure_safe',lib.rebuild_index,'RH_RAG_REBUILD_FAILED')
    check('failure_preserves_old_config',config(lib)==old_config)
    check('failed_temporary_collection_removed',{x.name for x in qdrant.get_collections().collections}==old_collections)
    check('failure_preserves_evidence',snapshot(lib)==before)

os.environ['RAG_MODEL_CACHE']=str(Path(a.legacy_cache).resolve())
with RagLibrary(workspace,embedding_model=old_model) as lib:
    check('legacy_still_searchable_after_failure',bool(lib.search_evidence('membrane')['items']))

os.environ['RAG_MODEL_CACHE']=str(Path(a.new_cache).resolve())
with RagLibrary(workspace) as lib:
    before=snapshot(lib)
    raw_hashes={row['source_path']:hashlib.sha256(Path(row['source_path']).read_bytes()).hexdigest() for row in lib._db.execute('SELECT source_path FROM rag_versions')}
    def forbidden(*args,**kwargs):raise AssertionError('migration attempted parsing')
    lib._parse=forbidden;lib._parse_with_cache=forbidden
    embedder,qdrant,_=lib._components(enforce_config=False)
    seen=[]
    class ObservedEmbedder:
        def embed(self,texts,**kwargs):
            values=list(texts);seen.append(values)
            return embedder.embed(values,**kwargs)
    lib._embedder=ObservedEmbedder()
    migrated=lib.rebuild_index();detail['migration']=migrated
    check('all_versions_rebuilt',migrated['indexed']==len(before['rag_evidence']))
    check('passage_prefix_used',bool(seen) and all(value.startswith('passage: ') for batch in seen for value in batch))
    check('metadata_and_evidence_unchanged',snapshot(lib)==before)
    check('raw_sources_unchanged',all(hashlib.sha256(Path(path).read_bytes()).hexdigest()==digest for path,digest in raw_hashes.items()))
    check('old_collection_retained',old_collections<={x.name for x in qdrant.get_collections().collections})
    check('active_collection_switched',lib._active_collection()==migrated['collection'] and migrated['collection'] not in old_collections)
    check('status_reports_new_model',lib.get_library_status()['embedding_model']==DEFAULT_EMBEDDING_MODEL)
    seen.clear();found=lib.search_evidence('membrane')['items']
    check('query_prefix_used',seen==[['query: membrane']] and bool(found))
    check('old_context_still_accessible',any(x['evidence_id']==old_id for x in lib.get_evidence_context(old_id)['items']))

with RagLibrary(workspace,embedding_model=old_model) as lib:
    denied('legacy_request_rejected_after_migration',lambda:lib.search_evidence('membrane'),'RH_RAG_CONFIG_MISMATCH')
with RagLibrary(workspace) as lib:
    check('reopened_index_ready',lib.get_library_status()['index_status']=='ready')
report={'execution_mode':'synthetic_migration','checks':checks,'detail':detail}
(root/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
raise SystemExit(0 if all(checks.values()) else 1)
