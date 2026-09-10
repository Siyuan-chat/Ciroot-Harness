import argparse,json,hashlib,sqlite3
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--workspace',required=True);p.add_argument('--catalog',required=True);p.add_argument('--output',required=True);a=p.parse_args()
workspace=Path(a.workspace).resolve();catalog=Path(a.catalog).resolve()
db=sqlite3.connect((workspace/'rag.sqlite').as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
records=json.loads(catalog.read_text(encoding='utf-8'))['records']
versions=[dict(x) for x in db.execute('SELECT d.doi,d.document_id,d.parse_status,v.* FROM rag_documents d JOIN rag_versions v ON v.version_id=d.current_version_id')]
by_doi={x['doi']:x for x in versions};files=[];bad=[]
for record in records:
    row=by_doi.get(record['doi']);source=catalog.parent/record['file']
    source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
    ok=row is not None and row['parse_status']=='completed' and row['content_sha256']==source_hash and Path(row['source_path']).is_file() and hashlib.sha256(Path(row['source_path']).read_bytes()).hexdigest()==source_hash
    files.append({'doi':record['doi'],'source_and_stored_hash_match':ok,'page_count':row['page_count'] if row else None,'coverage':row['coverage'] if row else None,'errors':json.loads(row['errors']) if row else []})
for row in db.execute('SELECT e.*,v.page_count FROM rag_evidence e JOIN rag_versions v ON v.version_id=e.version_id'):
    loc=json.loads(row['locator']);pages=loc.get('pages',[loc.get('page')])
    if not pages or not all(isinstance(v,int) and 1<=v<=row['page_count'] for v in pages):bad.append({'evidence_id':row['evidence_id'],'problem':'page_range'})
    for prov in loc.get('provenance',[]):
        box=prov.get('bbox')
        if box and (box['l']>=box['r'] or box['t']==box['b']):bad.append({'evidence_id':row['evidence_id'],'problem':'nonpositive_bbox'})
checks={'23_current_documents':len(versions)==23,'all_originals_match_stored_sources':all(x['source_and_stored_hash_match'] for x in files),'584_physical_pages':sum(x['page_count'] or 0 for x in files)==584,'valid_physical_locators':not bad}
report={'checks':checks,'documents':files,'evidence_count':db.execute('SELECT COUNT(*) FROM rag_evidence').fetchone()[0],'locator_problems':bad}
Path(a.output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'checks':checks,'evidence_count':report['evidence_count'],'partial_documents':sum(x['coverage']=='partial' for x in files)}))
raise SystemExit(0 if all(checks.values()) else 1)
