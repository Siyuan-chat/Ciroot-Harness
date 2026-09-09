"""Independent XML and persistence acceptance. Use a committed source snapshot."""
import argparse, json, sqlite3, sys, tempfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--output',required=True);a=p.parse_args()
source=Path(a.source).resolve();sys.path.insert(0,str(source/'src'))
from research_harness.ingestion import parse
from research_harness.service import Harness
from research_harness.storage import Store
checks={}
for name,xml,expected in [
    ('sibling_blocks','<article><p id="a">First</p><p id="b">Second</p></article>',['First','Second']),
    ('nested_semantic_blocks','<article><abstract><p>First</p><p>Second</p></abstract></article>',['First','Second']),
    ('mixed_content','<article><p id="a">Before <b>bold</b> after</p></article>',['Before bold after']),
    ('inline_no_added_spaces','<article><p id="a">alpha<i>beta</i>gamma</p></article>',['alphabetagamma']),
]:
    text,evidence,errors=parse('synthetic.xml',xml.encode())
    quotes=[x['quote'] for x in evidence]
    checks[name]={'passed':quotes==expected and not errors,'quotes':quotes,'errors':errors}
with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp);bad=root/'bad.xml';bad.write_text('<article><p>broken',encoding='utf-8')
    h=Harness(root/'ws');out=h.import_document(bad,'discovery','paper');h.store.close()
    s=Store(root/'ws');row=s.documents()[0];s.close()
    checks['failure_after_reopen']={'passed':row.get('parse_status')=='failed' and bool(json.loads(row.get('parse_errors','[]'))) and not row.get('content'),'status':row.get('parse_status'),'errors':row.get('parse_errors'),'content':row.get('content')}
    legacy=root/'legacy';legacy.mkdir()
    db=sqlite3.connect(legacy/'research.sqlite')
    db.execute('CREATE TABLE documents (id TEXT PRIMARY KEY, sha256 TEXT UNIQUE, kind TEXT, collection_name TEXT, filename TEXT, raw_path TEXT, content TEXT, created REAL)')
    db.execute('INSERT INTO documents VALUES (?,?,?,?,?,?,?,?)',('legacy-id','legacy-hash','paper','baseline','legacy.txt','raw/legacy','frozen old evidence',0))
    db.commit();db.close()
    good=root/'good.xml';good.write_text('<article><p>New text</p></article>',encoding='utf-8')
    h=Harness(legacy);out=h.import_document(good,'discovery','paper');rows=h.store.documents();h.store.close()
    old=next(x for x in rows if x['id']=='legacy-id');new=next(x for x in rows if x['id']!='legacy-id')
    checks['legacy_migration']={'passed':old['content']=='frozen old evidence' and new.get('parse_status')=='parsed' and new['content']=='New text','old_content_preserved':old['content']=='frozen old evidence','new_status':new.get('parse_status'),'new_content':new['content']}
result={'source_snapshot':str(source),'network_used':False,'synthetic':True,'checks':checks}
out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
raise SystemExit(0 if all(x['passed'] for x in checks.values()) else 1)
