"""Independent D18 retrieval probe. Frozen private questions are supplied separately."""
import argparse
import json
from collections import Counter
from pathlib import Path
from time import perf_counter

from research_harness.rag import RagLibrary


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--workspace',required=True)
    ap.add_argument('--evaluation',required=True)
    ap.add_argument('--output',required=True)
    ap.add_argument('--query-plans',help='Frozen host-generated plans; omit to test the original questions directly')
    args=ap.parse_args()
    evaluation=json.loads(Path(args.evaluation).read_text(encoding='utf-8-sig'))
    plans={}
    if args.query_plans:
        entries=json.loads(Path(args.query_plans).read_text(encoding='utf-8-sig'))['queries']
        plans={entry['id']:entry for entry in entries}
        assert len(plans)==len(entries), 'duplicate query plan IDs'
        expected={case['id']+'-'+lang for case in evaluation['cases'] for lang in case['queries']}
        assert expected <= plans.keys(), 'missing query plans'
    results=[]
    checks={}
    with RagLibrary(args.workspace) as lib:
        status=lib.get_library_status()
        checks['23_indexed_documents']=status['document_count']==23 and status['indexed_document_count']==23
        for case in evaluation['cases']:
            for lang,query in case['queries'].items():
                started=perf_counter()
                plan=plans.get(case['id']+'-'+lang)
                actual_query=plan['search_query'] if plan else query
                filters={'doi':plan['doi']} if plan and plan.get('doi') else None
                reply=lib.search_evidence(actual_query,top_k=evaluation['top_k'],filters=filters)
                hits=[]
                for item in reply['items']:
                    locator=item['locator']
                    pages=set(locator.get('pages',[])) if all(isinstance(v,int) for v in locator.get('pages',[])) else set()
                    pages.add(locator.get('page'))
                    anchors=case.get('required_anchors',[case['anchor']])
                    support=all(anchor.casefold() in item['text'].casefold() for anchor in anchors)
                    role_matches='role' not in case or item['role']==case['role']
                    if item.get('doi')==case['doi'] and case['page'] in pages and support and role_matches:
                        hits.append(item['evidence_id'])
                results.append({'id':case['id'],'language':lang,'query':query,'search_query':actual_query,'filters':filters,'hit':bool(hits),'hit_ids':hits,'seconds':round(perf_counter()-started,3),'response':reply})
                print(json.dumps({'case':case['id'],'language':lang,'hit':bool(hits),'seconds':results[-1]['seconds']},ensure_ascii=False),flush=True)
        sample=next((r['response']['items'][0] for r in results if r['response']['items']),None)
        if sample:
            context=lib.get_evidence_context(sample['evidence_id'])
            checks['context_contains_target']=any(x['evidence_id']==sample['evidence_id'] for x in context['items'])
            checks['context_stays_same_version']=all(x['version_id']==sample['version_id'] and x['document_id']==sample['document_id'] for x in context['items'])
            narrowed=lib.search_evidence('membrane conductivity',filters={'document_ids':[sample['document_id']],'version_ids':[sample['version_id']]})
            checks['document_version_filter']=bool(narrowed['items']) and all(x['document_id']==sample['document_id'] and x['version_id']==sample['version_id'] for x in narrowed['items'])
            exact=lib.search_evidence(sample['doi'],filters={'doi':sample['doi']})
            checks['doi_filter']=bool(exact['items']) and all(x['doi']==sample['doi'] for x in exact['items'])
        for name,call in [
            ('unknown_filter_rejected',lambda:lib.search_evidence('membrane',filters={'unexpected':True})),
            ('empty_query_rejected',lambda:lib.search_evidence('')),
            ('zero_top_k_rejected',lambda:lib.search_evidence('membrane',top_k=0)),
            ('missing_evidence_rejected',lambda:lib.get_evidence_context('not-an-evidence-id')),
        ]:
            try: call(); checks[name]=False
            except Exception as exc: checks[name]=hasattr(exc,'to_dict') and bool(exc.to_dict().get('code'))
    language_hits=Counter(r['language'] for r in results if r['hit'])
    threshold=evaluation['threshold']
    checks['recall_threshold']=sum(r['hit'] for r in results)>=threshold['overall_hits_min'] and all(language_hits[k]>=threshold['per_language_hits_min'] for k in ['zh','en','ja'])
    report={'execution_mode':'real_local_rag','query_mode':'host_planned' if plans else 'direct','query_plans':args.query_plans,'evaluation_version':evaluation['version'],'status':status,'checks':checks,'hits':sum(r['hit'] for r in results),'total':len(results),'hits_by_language':dict(language_hits),'queries':results}
    Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'checks':checks,'hits':report['hits'],'total':report['total'],'hits_by_language':dict(language_hits)},ensure_ascii=False))
    return 0 if all(checks.values()) else 1

if __name__=='__main__': raise SystemExit(main())
