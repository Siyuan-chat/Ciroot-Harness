"""Independent full public-service replay, with synthetic content and no network."""
import argparse,base64,copy,hashlib,json,socket,sys,tempfile
from io import BytesIO
from pathlib import Path

def fixture():
    spec={'status':'ready','project_id':'independent-service','revision':1,'research_question':'SYNTHETIC compare violet separator evidence','report_targets':[{'deliverable_type':kind,'languages':['zh','en','ja']} for kind in ('technical_report','literature_review')],'references':[]}
    runtime={'mode':'host','data_mode':'synthetic','budget':{'max_tasks':20,'max_source_calls':8}}
    baseline={'document_id':'violet-paper','source':'synthetic-paper','version':'v1','text':'SYNTHETIC archived baseline at 10 C.','title':'SYNTHETIC baseline'}
    docs=[{'document_id':'violet-paper','source':'synthetic-paper','version':'v2','text':'SYNTHETIC violet separator conductivity is 13 mS/cm at 20 C.','title':'SYNTHETIC Violet observation','doi':'10.8642/violet'}, {'document_id':'ZZ8642A1','source':'synthetic-patent','version':'v1','text':'SYNTHETIC patent describes a violet separator support.','title':'SYNTHETIC Violet support','publication_number':'ZZ8642A1','family_id':'violet-family'}]
    from reportlab.pdfgen import canvas
    pdf=BytesIO();c=canvas.Canvas(pdf)
    c.drawString(30,760,docs[0]['text']);c.showPage();c.drawString(30,760,'SYNTHETIC second physical page retains its own locator.');c.save()
    docs[0].update(content_type='application/pdf',base64_bytes=base64.b64encode(pdf.getvalue()).decode())
    docs[1].update(content_type='application/xml',text='<patent><claim id="claim-1">SYNTHETIC patent describes a violet separator support.</claim><p id="description-2">SYNTHETIC description gives no conductivity measurement.</p></patent>')
    queries=[{'query_id':'qp','source':'synthetic-paper','query':'violet separator','input_refs':[],'parent_query_id':None},{'query_id':'qpat','source':'synthetic-patent','query':'violet separator support','input_refs':[],'parent_query_id':None}]
    pages=[dict(source=q['source'],query_id=q['query_id'],cursor=None,next_cursor=None,candidates=[d]) for q,d in zip(queries,docs)]
    return spec,runtime,{'references':[baseline],'sources':docs,'transport_pages':pages},queries

def answer(task,queries):
    role=task['role'];p=task['payload']
    if role=='planning':return {'search_plan':{'queries':queries}}
    if role in ('paper_search','patent_search'):return {'candidates':[{'document_id':d['document_id'],'relevance':'relevant','reason':'SYNTHETIC matches supplied scope'} for d in p['candidates']]}
    if role=='evidence_analysis':return {'findings':[{'finding_id':'f'+str(i),'finding':e['text'],'evidence_ids':[e['evidence_id']],'value':None,'unit':None,'conditions':None} for i,e in enumerate(p['evidence'])]}
    if role=='business_judgment':return {'judgments':[{'document_id':d,'relevance':'uncertain','human_review_required':True,'reason':'SYNTHETIC requires company assessment'} for d in sorted({x['document_id'] for x in p['documents']})]}
    if role=='synthesis':
        e=p['evidence'][0]
        return {'claims':[{'claim_id':'c0','claim':e['text'],'finding_refs':[0],'evidence_refs':[e['evidence_id']],'quote':e['text'],'document_id':e['document_id'],'version_id':e['version_id']}]}
    if role=='writing':
        assert p['evidence'] and p['findings'] and p['claims'],'Writer cannot inspect supporting evidence'
        return {'sections':[{'deliverable_type':kind,'language':lang,'section_id':'findings','title':title,'body':body,'claim_ids':['c0']} for kind in ('technical_report','literature_review') for lang,title,body in [('zh','合成资料结果','合成紫色隔膜资料记录了 20 C 条件下 13 mS/cm；该观察用于框架验证，不能推广到未测条件。'),('en','Synthetic findings','The SYNTHETIC violet separator record gives 13 mS/cm at 20 C. This observation validates the workflow and does not establish behavior under untested conditions.'),('ja','合成資料の結果','合成の紫色セパレータ資料は、20 C で 13 mS/cm を記録しています。この観察は処理手順の検証用であり、未測定条件への一般化はできません。')]]}
    if role=='verification':
        assert p['evidence'] and p['claims'] and p['sections'],'Verifier lacks evidence/body'
        return {'verification':{'status':'supported','conclusion':'SYNTHETIC quoted record supports the bounded observation','supported_claim_refs':[0]}}
    raise AssertionError(role)

def drive(service,run,queries,invalid=False):
    seen=[];rejected=[]
    for _ in range(16):
        tasks=service.get_pending_tasks(run)
        for task in tasks:
            seen.append(task['role']);result=answer(task,queries)
            if task['role'] in ('evidence_analysis','business_judgment'):
                assert task['payload']['baseline_evidence'][0]['version_id']=='v1','Frozen baseline missing from analysis'
            if invalid and task['role']=='synthesis':
                for field,value in [('quote','INVENTED_QUOTE_8642'),('version_id','wrong-version'),('evidence_refs',['unknown-evidence'])]:
                    bad=copy.deepcopy(result);bad['claims'][0][field]=value
                    try:service.submit_model_result(run,task['task_id'],bad,task['task_version'])
                    except HarnessError:rejected.append(field)
                    else:raise AssertionError('Invalid claim consumed task: '+field)
                    assert any(t['task_id']==task['task_id'] for t in service.get_pending_tasks(run))
            service.submit_model_result(run,task['task_id'],result,task['task_version'])
            before=service.status(run)['budget']
            assert service.submit_model_result(run,task['task_id'],result,task['task_version'])['status']=='reused'
            assert service.status(run)['budget']==before
        service.advance_investigation(run)
        if not service.get_pending_tasks(run) and service.status(run)['outcome'] in ('completed','partial'):
            return service.get_result(run),seen,rejected
    raise AssertionError('Bounded driver did not terminate')

def full():
    spec,runtime,scenario,queries=fixture()
    with tempfile.TemporaryDirectory() as tmp:
        s=InvestigationService(tmp)
        try:
            run=s.create_investigation(spec,runtime,scenario)['run_id'];result,roles,rejected=drive(s,run,queries,invalid=True)
            assert len(set(roles))==8 and len(rejected)==3
            assert result['outcome']=='completed',json.dumps(result.get('issues'))
            assert result['baseline_evidence'][0]['version_id']=='v1'
            evidence=result['evidence'];assert any(e['document_id']=='violet-paper' and e['version_id']=='v2' for e in evidence)
            assert {e['locator']['value'] for e in evidence if e['locator']['kind']=='pdf_page'}=={'1','2'}
            assert {e['locator']['value'] for e in evidence if e['document_id']=='ZZ8642A1'}=={'claim-1','description-2'}
            for e in evidence:assert s.get_discovery_evidence(e['evidence_id'])==e
            frozen=s.build_report_data(run);assert frozen['baseline_evidence'][0]['version_id']=='v1','Frozen report dropped baseline'
            assert frozen['bibliography'] and 'Violet observation' in json.dumps(frozen['bibliography'])
            before=s.status(run)['budget'];export=s.export_report(run);artifacts=export['artifacts']
            md=[x for x in artifacts if x['format']=='markdown'];assert len(md)==6,'Missing complete dual trilingual report'
            hashes={x['path']:hashlib.sha256((Path(tmp)/x['path']).read_bytes()).hexdigest() for x in artifacts}
            for x in md:
                body=(Path(tmp)/x['path']).read_text(encoding='utf-8');assert len(body)>200 and ('SYNTHETIC' in body or 'synthetic' in body)
            s.close();s=InvestigationService(tmp);assert s.build_report_data(run)==frozen
            s.resume_investigation(run);s.export_report(run);assert s.status(run)['budget']==before
            assert all(hashlib.sha256((Path(tmp)/path).read_bytes()).hexdigest()==digest for path,digest in hashes.items())
            assert s.get_artifacts(run),'Artifact registry not connected'
            for e in evidence:assert s.get_discovery_evidence(e['evidence_id'])==e
            return {'roles':roles,'reports':6,'claim_rejections':rejected,'source_calls':before['reserved_source_calls'],'restart':'preserved'}
        finally:s.close()

def acquisition_failure():
    spec,runtime,scenario,queries=fixture()
    broken=scenario['sources'][1];broken.update(content_type='application/pdf',base64_bytes='bm90IGEgcGRm')
    with tempfile.TemporaryDirectory() as tmp:
        s=InvestigationService(tmp)
        try:
            run=s.create_investigation(spec,runtime,scenario)['run_id'];result,_,_=drive(s,run,queries)
            assert result['outcome']=='partial' and result['issues'],'Failed body acquisition was promoted to completed'
            assert any(e['document_id']=='violet-paper' for e in result['evidence'])
            assert 'NORMALIZE' in json.dumps(result['issues']).upper(),'Acquisition failure missing from result'
            return 'Valid evidence retained; failed PDF remains visible and partial'
        finally:s.close()

def discovery_policy():
    spec,runtime,scenario,queries=fixture()
    runtime.update(model_id='approved',data_policy={'company_id':'violet','allowed_models':['approved'],'allow_query_egress':True})
    scenario['sources'][0].update(visibility='confidential',company_id='violet')
    with tempfile.TemporaryDirectory() as tmp:
        s=InvestigationService(tmp)
        try:
            run=s.create_investigation(spec,runtime,scenario)['run_id'];result,_,_=drive(s,run,queries)
            e=next(e for e in result['evidence'] if e['document_id']=='violet-paper')
            assert s.get_discovery_evidence(e['evidence_id'],runtime)==e
            other=copy.deepcopy(runtime);other['data_policy']['company_id']='another-company'
            for rt in (None,other):
                try:s.get_discovery_evidence(e['evidence_id'],rt)
                except HarnessError:pass
                else:raise AssertionError('Discovery read bypassed company/model policy')
            return 'Discovery reads enforce the owning company and model policy'
        finally:s.close()


def task_budget():
    for limit in (2,7):
        spec,runtime,scenario,queries=fixture();runtime['budget']['max_tasks']=limit
        with tempfile.TemporaryDirectory() as tmp:
            s=InvestigationService(tmp)
            try:
                run=s.create_investigation(spec,runtime,scenario)['run_id'];result,_,_=drive(s,run,queries)
                assert result['outcome']=='partial' and not s.get_pending_tasks(run)
                before=s.status(run)['budget'];assert before['reserved_tasks']<=limit
                if limit==7:assert result['evidence'] and result['findings'],'Task cap discarded retained findings'
                s.close();s=InvestigationService(tmp)
                for _ in range(3):s.resume_investigation(run)
                assert s.status(run)['budget']==before
            finally:s.close()
    return 'Task caps stop with retained state and cannot reset on resume'

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source-root',type=Path);parser.add_argument('--checkpoint',required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    if args.source_root:sys.path.insert(0,str(args.source_root.resolve()/'src'))
    socket.socket.connect=lambda *_a,**_k:(_ for _ in ()).throw(AssertionError('No P1 external network'))
    from research_harness.investigation import InvestigationService
    from research_harness.errors import HarnessError
    checks=[]
    for name,fn in [('C2-public-service',full),('F06-acquisition-failure',acquisition_failure),('M02-discovery-policy',discovery_policy),('F07-task-budget',task_budget)]:
        try:checks.append({'id':name,'status':'passed','detail':fn()})
        except Exception as exc:
            import traceback
            checks.append({'id':name,'status':'failed','type':type(exc).__name__,'detail':str(exc),'trace':traceback.format_exc()})
    result={'checkpoint':args.checkpoint,'synthetic':True,'scope':'Public service through source parsing, frozen reports and restart; deterministic host replay','checks':checks};args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False));sys.exit(0 if all(x['status']=='passed' for x in checks) else 1)
