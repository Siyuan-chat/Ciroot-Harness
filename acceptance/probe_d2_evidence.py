"""Independent D2 evidence plumbing check; all input text is synthetic."""
import argparse
import json
import sys
import tempfile
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--source', required=True)
parser.add_argument('--output', required=True)
args = parser.parse_args()
source = Path(args.source).resolve()
sys.path.insert(0, str(source / 'src'))
from research_harness.service import Harness

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    harness = Harness(root / 'workspace')
    baseline_text = 'Synthetic baseline: route alpha is described.'
    candidate_text = 'Synthetic candidate: route beta is described.'
    baseline_file = root / 'baseline.txt'
    baseline_file.write_text(baseline_text, encoding='utf-8')
    imported = harness.import_document(baseline_file, 'baseline', 'paper')
    baseline_id = imported['document_id']
    spec = json.loads((source / 'examples/polymer-design.draft.json').read_text(encoding='utf-8'))
    spec.update(status='ready', unresolved_questions=[])
    spec['reference_library']['document_ids'] = [baseline_id]
    spec_file = root / 'spec.json'
    spec_file.write_text(json.dumps(spec), encoding='utf-8')
    fixture_file = root / 'fixture.json'
    fixture_file.write_text(json.dumps({'candidates': [
        {'id': 'synthetic-candidate', 'quote': candidate_text, 'locator': 'line:1'}
    ]}), encoding='utf-8')
    calls = []
    marker = 'synthetic-finding-marker'

    def model(received_spec, candidate, candidate_evidence, reference_evidence):
        calls.append((received_spec, candidate_evidence, reference_evidence))
        return {'id': marker, 'disposition': 'watch', 'rationale': marker}

    result = harness.run_fixture(spec_file, fixture_file, model_adapter=model)
    harness.store.close()
    harness = Harness(root / 'workspace')
    documents = harness.store.documents()
    evidence = [e for doc in documents for e in harness.store.evidence(doc['id'])]
    evidence_by_id = {e['id']: e for e in evidence}
    report = json.loads((Path(result['artifacts']['report']) / 'report.json').read_text(encoding='utf-8'))
    received_spec, candidate_evidence, reference_evidence = calls[0]
    checks = {
        'spec_passed': received_spec == spec,
        'baseline_evidence_passed': any(e.get('document_id') == baseline_id and e.get('quote') == baseline_text for e in reference_evidence),
        'candidate_evidence_is_persisted': bool(candidate_evidence) and all(
            e.get('id') in evidence_by_id and evidence_by_id[e['id']]['quote'] == e.get('quote')
            and evidence_by_id[e['id']]['document_id'] != baseline_id for e in candidate_evidence),
        'candidate_original_persisted': any(d['content'] == candidate_text for d in documents),
        'finding_persisted_in_report': marker in json.dumps(report.get('findings', [])),
        'baseline_frozen_in_report': baseline_id in report.get('baseline_document_ids', []),
    }
    harness.store.close()
output = Path(args.output)
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(checks, indent=2), encoding='utf-8')
print(json.dumps(checks, indent=2))
raise SystemExit(0 if all(checks.values()) else 1)
