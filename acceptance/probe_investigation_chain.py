"""Independent synthetic C1 data-flow and budget probe (no scientific claims)."""
from __future__ import annotations
import argparse
import copy
import json
from pathlib import Path
import socket
import sys
import tempfile


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--source-root', required=True, type=Path)
    p.add_argument('--checkpoint', required=True)
    p.add_argument('--output', required=True, type=Path)
    args = p.parse_args()
    sys.path.insert(0, str(args.source_root.resolve()/'src'))
    socket.socket.connect = lambda *_a, **_k: (_ for _ in ()).throw(AssertionError('P1 network forbidden'))
    from research_harness.investigation import InvestigationService
    from research_harness.errors import HarnessError
    spec = {'status':'ready','project_id':'independent-meridian','revision':1,
            'research_question':'SYNTHETIC compare indigo separator evidence; amber packaging is excluded.',
            'report_targets':['technical_report','literature_review'],'references':[]}
    runtime = {'mode':'host','data_mode':'synthetic','budget':{'max_tasks':8}}
    scenario = {'sources':[
        {'source':'synthetic-paper','document_id':'ind-paper','title':'SYNTHETIC Indigo',
         'text':'SYNTHETIC indigo separator: marker INDIGO_8642 at 20 C.',
         'version':'v1','locator':{'kind':'paragraph','value':'1'}},
        {'source':'synthetic-paper','document_id':'ind-excluded','title':'SYNTHETIC Amber packaging',
         'text':'SYNTHETIC amber packaging is outside the selected scope.',
         'version':'v1','locator':{'kind':'paragraph','value':'1'}},
        {'source':'synthetic-patent','document_id':'ind-patent','title':'SYNTHETIC Indigo patent',
         'text':'SYNTHETIC claim: indigo separator. No measurement reported.',
         'version':'v1','locator':{'kind':'claim','value':'c1'}}]}
    plan = {'search_plan':{'queries':[{'source':'synthetic-paper','query':'indigo separator'},
                                    {'source':'synthetic-patent','query':'indigo separator'}]}}
    checks=[]

    def test(name, fn):
        try:
            detail=fn()
            checks.append({'id':name,'status':'passed','detail':detail})
        except Exception as exc:
            checks.append({'id':name,'status':'failed','type':type(exc).__name__,'detail':str(exc)[:900]})

    def chain(max_tasks=8):
        with tempfile.TemporaryDirectory(prefix='d19-chain-') as tmp:
            service=InvestigationService(tmp)
            try:
                rt=copy.deepcopy(runtime);rt['budget']['max_tasks']=max_tasks
                run=service.create_investigation(spec,rt,scenario)['run_id']
                roles=[]; normalized=[]; submitted=0; restarted=False
                for turn in range(30):
                    tasks=service.get_pending_tasks(run)
                    for task in tasks:
                        role,payload=task['role'],task['payload'];roles.append(role)
                        if role=='planning': result=copy.deepcopy(plan)
                        elif role in ('paper_search','patent_search'):
                            assert payload['query']=='indigo separator'
                            result={'candidates':[{'document_id':c['document_id'],
                                'relevance':'irrelevant' if c['document_id']=='ind-excluded' else 'relevant',
                                'reason':'Independent synthetic scope decision'} for c in payload['candidates']]}
                        elif role=='evidence_analysis':
                            normalized=payload['evidence']
                            assert {e['document_id'] for e in normalized}=={'ind-paper','ind-patent'}
                            assert any('INDIGO_8642' in e.get('quote',e.get('text','')) for e in normalized)
                            assert all(e['locator'] for e in normalized)
                            result={'findings':[{'finding':'SYNTHETIC indigo evidence is present; no scientific conclusion.',
                                                'evidence_ids':[e['evidence_id'] for e in normalized]}]}
                        elif role=='business_judgment':
                            result={'judgments':[{'document_id':d['document_id'],'relevance':'relevant',
                                                 'human_review_required':True,'reason':'Synthetic review request'}
                                                for d in payload['documents']]}
                        elif role=='synthesis':
                            assert 'SYNTHETIC indigo evidence' in payload['findings'][0]['finding']
                            result={'claims':[{'claim':'Synthetic input-dependent synthesis','finding_refs':[0]}]}
                        elif role=='writing':
                            assert payload['claims'][0]['claim']=='Synthetic input-dependent synthesis'
                            result={'sections':[{'title':'Synthetic analysis','text':'Synthetic input-dependent synthesis.',
                                                 'claim_refs':[0]}]}
                        elif role=='verification':
                            assert payload['sections'][0]['text']=='Synthetic input-dependent synthesis.'
                            result={'verification':{'status':'supported','conclusion':'Independent synthetic chain finished.',
                                                    'supported_claim_refs':[0]}}
                        else:raise AssertionError('Unexpected role '+role)
                        service.submit_model_result(run,task['task_id'],result,task['task_version'])
                        budget_before=service.status(run)['budget']
                        replay=service.submit_model_result(run,task['task_id'],result,task['task_version'])
                        assert replay['status']=='reused' and service.status(run)['budget']==budget_before
                        submitted+=1
                    service.advance_investigation(run)
                    if not restarted and any(x in roles for x in ('paper_search','patent_search')):
                        before=service.get_pending_tasks(run)
                        service.close();service=InvestigationService(tmp)
                        assert service.get_pending_tasks(run)==before;restarted=True
                    state=service.status(run)
                    if state['status'] in ('completed','partial') and not service.get_pending_tasks(run):break
                if max_tasks<8:
                    result=service.get_result(run)
                    assert result['outcome']=='partial'
                    assert result['evidence'] and result['findings'], 'Budget exhaustion discarded successful evidence/findings'
                    return {'tasks':submitted,'outcome':result['outcome'],'retained_evidence':len(result['evidence'])}
                assert set(roles)=={'planning','paper_search','patent_search','evidence_analysis',
                                    'business_judgment','synthesis','writing','verification'}
                result=service.get_result(run)
                assert result['conclusion']=='Independent synthetic chain finished.'
                trace=service.status(run)['stage_trace']
                assert {x['node'] for x in trace}>={'planning_gate','source_task','acquire_normalize',
                                                 'analysis_task','verification_gate'}
                return {'tasks':submitted,'selected_documents':len(normalized),'restart':restarted,'trace':trace}
            finally:service.close()

    def budget_boundary():
        rt=copy.deepcopy(runtime);rt['budget']['max_tasks']=2
        with tempfile.TemporaryDirectory(prefix='d19-budget-') as tmp:
            service=InvestigationService(tmp)
            try:
                run=service.create_investigation(spec,rt,scenario)['run_id']
                task=service.get_pending_tasks(run)[0]
                service.submit_model_result(run,task['task_id'],plan,task['task_version'])
                for _ in range(3):
                    try:service.advance_investigation(run)
                    except HarnessError:pass
                    assert service.status(run)['budget']['reserved_tasks']<=2
                    pending=service.get_pending_tasks(run)
                    for t in pending:
                        if t['role'] in ('paper_search','patent_search'):
                            service.submit_model_result(run,t['task_id'],{'candidates':[]},t['task_version'])
                before=service.status(run)['budget'];service.close();service=InvestigationService(tmp)
                try:service.resume_investigation(run)
                except HarnessError:pass
                assert service.status(run)['budget']==before
                end=service.status(run)
                assert end['outcome']=='partial', 'Exhausted budget must preserve an explicit partial outcome'
                assert end.get('waiting_reason')!='model_task', 'No pending task must not be reported as awaiting a model'
                return {'budget':before,'status':end}
            finally:service.close()
    test('C1-real-data-flow',chain)
    test('C1-budget-reentry',budget_boundary)
    test('C1-partial-preserves-evidence',lambda:chain(7))
    result={'checkpoint':args.checkpoint,'synthetic':True,'checks':checks,
            'scope':'C1 plumbing and budget, not scientific or complete P1 acceptance'}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
    return 0 if all(x['status']=='passed' for x in checks) else 1


if __name__=='__main__':raise SystemExit(main())
