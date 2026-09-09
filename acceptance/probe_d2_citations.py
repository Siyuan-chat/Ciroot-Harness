"""D2 structural citation verification; synthetic text and injected local model."""
import argparse
import json
import sys
import tempfile
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('--source', required=True)
p.add_argument('--output', required=True)
a = p.parse_args()
source = Path(a.source).resolve()
sys.path.insert(0, str(source / 'src'))
from research_harness.service import Harness

results = {}
for mode in ('valid', 'unknown_id', 'wrong_quote', 'wrong_owner'):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        h = Harness(root / 'workspace')
        baseline = root / 'baseline.txt'
        baseline.write_text('Synthetic baseline route alpha.', encoding='utf-8')
        imported = h.import_document(baseline, 'baseline', 'paper')
        spec = json.loads((source / 'examples/polymer-design.draft.json').read_text(encoding='utf-8'))
        spec.update(status='ready', unresolved_questions=[])
        spec['reference_library']['document_ids'] = [imported['document_id']]
        sp = root / 'spec.json'
        sp.write_text(json.dumps(spec), encoding='utf-8')
        fp = root / 'fixture.json'
        fp.write_text(json.dumps({'candidates': [{'id': 'synthetic-candidate', 'quote': 'Synthetic candidate route beta.', 'locator': 'line:1'}]}), encoding='utf-8')

        def model(spec, candidate, candidate_evidence, reference_evidence):
            e = candidate_evidence[0]
            citation = {'evidence_id': e['id'], 'quote': e['quote']}
            if mode == 'unknown_id':
                citation['evidence_id'] = 'nonexistent-synthetic-evidence'
            if mode == 'wrong_quote':
                citation['quote'] = 'This synthetic quote is absent from the original.'
            if mode == 'wrong_owner':
                citation = {'evidence_id': reference_evidence[0]['id'], 'quote': reference_evidence[0]['quote']}
            return {'id': 'synthetic-finding', 'disposition': 'include', 'comparison_result': 'not_comparable',
                    'rationale': 'Synthetic plumbing check.', 'candidate_citations': [citation], 'reference_citations': []}

        out = h.run_fixture(sp, fp, model_adapter=model)
        h.store.close()
        h = Harness(root / 'workspace')
        report = json.loads((Path(out['artifacts']['report']) / 'report.json').read_text(encoding='utf-8'))
        finding = report['findings'][0]
        verification = finding.get('verification', {})
        issues = h.review_list()
        if mode == 'valid':
            passed = verification.get('status') == 'valid' and finding['disposition'] == 'include' and not issues
        else:
            passed = (verification.get('status') == 'invalid' and bool(verification.get('errors'))
                      and finding['disposition'] == 'watch' and finding['comparison_result'] == 'insufficient_evidence'
                      and any(i.get('document_id') == report['candidates'][0]['document_id'] for i in issues))
        results[mode] = {'passed': passed, 'disposition': finding['disposition'], 'verification': verification, 'persisted_issues': len(issues)}
        h.store.close()
output = Path(a.output)
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(results, indent=2), encoding='utf-8')
print(json.dumps(results, indent=2))
raise SystemExit(0 if all(r['passed'] for r in results.values()) else 1)
