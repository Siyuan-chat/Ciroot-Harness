"""D2 manual revision and frozen history check using only synthetic material."""
import argparse
import copy
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
from research_harness.contracts import fingerprint

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    h = Harness(root / 'workspace')
    baseline = root / 'baseline.txt'
    baseline.write_text('Synthetic original baseline.', encoding='utf-8')
    first_baseline = h.import_document(baseline, 'baseline', 'paper')['document_id']
    spec = json.loads((source / 'examples/polymer-design.draft.json').read_text(encoding='utf-8'))
    spec.update(status='ready', unresolved_questions=[])
    sp = root / 'spec.json'
    sp.write_text(json.dumps(spec), encoding='utf-8')
    fp = root / 'fixture.json'
    fp.write_text(json.dumps({'candidates': [{'id': 'synthetic-candidate', 'quote': 'Synthetic candidate text.', 'locator': 'line:1'}]}), encoding='utf-8')
    calls = []

    def model(spec, candidate, ce, re):
        calls.append(copy.deepcopy(spec))
        return {'disposition': 'include', 'comparison_result': 'not_comparable',
                'rationale': spec['topic'] + ' | ' + ' | '.join(e['quote'] for e in re),
                'candidate_citations': [{'evidence_id': ce[0]['id'], 'quote': ce[0]['quote']}], 'reference_citations': []}

    saved1 = h.save_spec(sp)
    run1 = h.run_fixture(sp, fp, model_adapter=model)
    report1 = Path(run1['artifacts']['report'])
    frozen_files = {f.name: f.read_bytes() for f in report1.iterdir() if f.is_file()}
    frozen_run = h.store.run(run1['run_id'])
    frozen_data = json.loads(frozen_files['report.json'])
    original_spec_row = dict(h.store.db.execute('SELECT * FROM specs WHERE project_id=? AND revision=1', (spec['project_id'],)).fetchone())
    manual = copy.deepcopy(spec)
    manual['topic'] = 'Synthetic manual change / 手改 / 手動変更'
    manual['objectives'].append('Preserve this explicit synthetic requirement.')
    sp.write_text(json.dumps(manual), encoding='utf-8')
    manual_bytes = sp.read_bytes()
    saved2 = h.save_spec(sp)
    saved_again = h.save_spec(sp)
    baseline.write_text('Synthetic added baseline.', encoding='utf-8')
    second_baseline = h.import_document(baseline, 'baseline', 'paper')['document_id']
    run2 = h.run_fixture(sp, fp, model_adapter=model)
    h.store.close()
    h = Harness(root / 'workspace')
    h.report(run1['run_id'], ['zh', 'en', 'ja'])
    second_row = h.store.run(run2['run_id'])
    second_data = json.loads(second_row['report_data'])
    expected_manual = {**manual, 'revision': 2}
    specs = [dict(r) for r in h.store.db.execute('SELECT * FROM specs ORDER BY revision')]
    checks = {
        'revision_sequence_1_2_2': [saved1['revision'], saved2['revision'], saved_again['revision']] == [1, 2, 2],
        'all_manual_fields_preserved': saved2 == expected_manual and calls[-1] == expected_manual,
        'input_file_unchanged': sp.read_bytes() == manual_bytes,
        'run_bound_to_revision_2': second_row['revision'] == 2,
        'old_spec_row_unchanged': specs[0] == original_spec_row,
        'only_two_versions': len(specs) == 2,
        'stored_fingerprints_match': all(r['fingerprint'] == fingerprint(json.loads(r['content'])) for r in specs),
        'old_run_unchanged': h.store.run(run1['run_id']) == frozen_run,
        'old_report_rerender_unchanged': all((report1 / name).read_bytes() == content for name, content in frozen_files.items()),
        'old_baseline_frozen': frozen_data['baseline_document_ids'] == [first_baseline],
        'next_run_sees_selected_baseline_change': second_baseline in second_data['baseline_document_ids'],
        'discovery_not_auto_promoted': all(c['document_id'] not in second_data['baseline_document_ids'] for c in second_data['candidates']),
        'input_and_reference_affect_finding': second_data['findings'][0]['rationale'] != frozen_data['findings'][0]['rationale'],
    }
    h.store.close()
out = Path(a.output)
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(checks, indent=2), encoding='utf-8')
print(json.dumps(checks, indent=2))
raise SystemExit(0 if all(checks.values()) else 1)
