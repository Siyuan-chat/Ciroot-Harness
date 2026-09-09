"""Independent 9b5d6ea behavior probes. Inputs are synthetic, no network calls."""
import copy, json, os, subprocess, sys, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'.local/acceptance/9b5d6ea'
SOURCE=BASE/'source'
sys.path.insert(0,str(SOURCE/'src'))
from research_harness.service import Harness
from research_harness.contracts import validate_spec
from research_harness.intake import respond
from research_harness.ingestion import parse
results={}
with tempfile.TemporaryDirectory(dir=BASE) as temp:
    work=Path(temp)
    spec=json.loads((SOURCE/'examples/polymer-design.draft.json').read_text(encoding='utf-8'))
    spec.update(status='ready',unresolved_questions=[])
    spec['topic']='polymer design'
    runtime=json.loads((SOURCE/'examples/runtime.example.json').read_text(encoding='utf-8'))
    runtime['llm'].update(model='synthetic-local',local=True)
    runtime['retrieval']['embedding']['model']='SYNTHETIC_UNAVAILABLE_MODEL'
    for cfg in runtime['sources'].values(): cfg['enabled']=False
    rp=work/'runtime.json'; rp.write_text(json.dumps(runtime),encoding='utf-8')
    sp=work/'research.json'; sp.write_text(json.dumps(spec),encoding='utf-8')
    c={'id':'same','description':'synthetic','mode':'qualitative','target':None,'required_conditions':{},'required':False,'minimum_evidence':'abstract'}
    duplicate=copy.deepcopy(spec); duplicate['criteria']=[c,dict(c)]
    try: validate_spec(duplicate); results['F08_duplicate_rejected']=False
    except Exception: results['F08_duplicate_rejected']=True
    results['doctor']=Harness.doctor(rp)
    h=Harness(work/'run-workspace')
    try:
        rid=h.run(sp,rp)
        report=json.loads((h.workspace/'reports'/rid/'report.json').read_text(encoding='utf-8'))
        results['hybrid_run']={k:report[k] for k in ('status','execution_mode','synthetic','retrieval')}
    except Exception as exc: results['hybrid_run']={'blocked':type(exc).__name__}
    finally: h.store.close()
    results['intake']={}
    conversations={
        'zh':['调查聚合物设计，只要论文，不要专利；只描述，不设数值门槛。','聚合物设计','开始调查'],
        'en':['Investigate polymer design, papers only; exclude patents and use qualitative criteria.','polymer design','start investigation'],
        'ja':['ポリマー設計を調査。論文のみ、特許を除外。定性的に比較。','ポリマー設計','調査を開始']}
    for lang,messages in conversations.items():
        ws=work/('intake-'+lang)
        replies=[respond(ws,message,lang) for message in messages]
        results['intake'][lang]={'first_question':replies[0]['reply'],'final_intent':replies[-1]['intent'],'final_spec':{k:replies[-1]['spec'][k] for k in ('topic','revision','status','scope','criteria','exclusion_rules')},'runs_created':(ws/'research.sqlite').exists()}
    ws=work/'manual-edit'
    respond(ws,'Investigate polymer design','en'); respond(ws,'polymer design','en')
    session=ws/'sessions/intake.json'
    saved=json.loads(session.read_text(encoding='utf-8')); saved['spec']['topic']='USER_EDITED_TOPIC'
    session.write_text(json.dumps(saved),encoding='utf-8')
    results['intake_no_revision_update']=respond(ws,'Change the report language to Japanese only','en')['spec']['revision']
    xml=b'<article><p id="p1">First</p><p id="p2">Second</p></article>'
    text,ev,errors=parse('synthetic.xml',xml)
    results['xml_sibling_join']={'content':text,'root_quote':ev[0]['quote'],'error_count':len(errors)}
    h=Harness(work/'parse-workspace')
    bad=work/'bad.xml';bad.write_text('<article><p>broken',encoding='utf-8')
    imported=h.import_document(bad,'discovery','paper');doc=h.store.documents()[0]
    results['parse_failure_persistence']={'import_result':imported,'stored_document_keys':list(doc),'stored_content':doc['content'],'evidence_count':len(h.store.evidence(imported['document_id']))}
    h.store.close()
BASE.mkdir(exist_ok=True)
(BASE/'acceptance-probes.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(results,ensure_ascii=False,indent=2))
violations=[not results['F08_duplicate_rejected'],results['doctor']['ok'],'blocked' not in results['hybrid_run'],any(x['final_intent']!='run' or x['final_spec']['scope']['document_types']!=['paper'] for x in results['intake'].values()),results['xml_sibling_join']['root_quote']=='FirstSecond']
raise SystemExit(1 if any(violations) else 0)
