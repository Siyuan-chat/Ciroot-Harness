"""Bounded D2 budget, source failure and one human-decision acceptance check."""
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
for mode, count, expected in [('at_limit', 1, 'completed'), ('over_limit', 2, 'partial'), ('source_failure', 2, 'failed')]:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        h = Harness(root / 'workspace')
        spec = json.loads((source / 'examples/polymer-design.draft.json').read_text(encoding='utf-8'))
        spec.update(status='ready', unresolved_questions=[])
        spec['execution']['budget']['max_candidates'] = 1
        sp = root / 'spec.json'
        sp.write_text(json.dumps(spec), encoding='utf-8')
        fp = root / 'fixture.json'
        fp.write_text(json.dumps({'candidates': [
            {'id': f'synthetic-{i}', 'quote': f'Synthetic route {i}.', 'locator': 'line:1'} for i in range(count)
        ]}), encoding='utf-8')
        calls = []
        events = []

        def model(spec, candidate, ce, re):
            calls.append(candidate['id'])
            return {'disposition': 'watch', 'comparison_result': 'insufficient_evidence',
                    'rationale': 'Synthetic missing support.', 'candidate_citations': [], 'reference_citations': []}

        def failing_source(candidates):
            raise RuntimeError('synthetic-secret-marker')

        out = h.run_fixture(sp, fp, model_adapter=model,
                            source_adapter=failing_source if mode == 'source_failure' else None,
                            on_progress=events.append)
        report_file = Path(out['artifacts']['report']) / 'report.json'
        report_bytes = report_file.read_bytes()
        report = json.loads(report_bytes)
        h.store.close()
        h = Harness(root / 'workspace')
        row = next(r for r in h.status() if r.get('run_id', r.get('id')) == out['run_id'])
        checks = {
            'returned_outcome': out['outcome'] == expected,
            'persisted_outcome': row.get('outcome', row.get('status')) == expected,
            'report_outcome': report['status'] == expected,
            'terminal_event': events[-1]['status'] == expected,
            'model_call_count': len(calls) == (0 if mode == 'source_failure' else 1),
            'retained_candidates': len(report.get('candidates', [])) == (0 if mode == 'source_failure' else 1),
        }
        if mode == 'over_limit':
            checks['budget_reason_saved'] = any(x.get('code') == 'max_candidates' for x in report.get('limits', []))
            issue = h.review_list()[0]
            h.review_decide(issue['id'], 'exclude', 'Synthetic human decision.')
            h.store.close()
            h = Harness(root / 'workspace')
            resolved = next(i for i in h.review_list() if i['id'] == issue['id'])
            checks['human_decision_reloaded'] = resolved['human_decision'] == 'exclude' and resolved['status'] == 'resolved'
            checks['frozen_report_unchanged'] = report_file.read_bytes() == report_bytes
            checks['spec_unchanged'] = json.loads(sp.read_text(encoding='utf-8')) == spec
        if mode == 'source_failure':
            checks['structured_error'] = out.get('error', {}).get('code') == 'source_failed' and out.get('stage') == 'search'
            checks['no_skipped_stage_activity'] = not any(e['stage'] in ('retrieve', 'analyze', 'verify') and e['status'] == 'running' for e in events)
            exposed = json.dumps(out) + json.dumps(events) + json.dumps(row)
            exposed += ''.join(f.read_text(encoding='utf-8') for f in report_file.parent.iterdir() if f.is_file())
            checks['exception_secret_absent'] = 'synthetic-secret-marker' not in exposed
        results[mode] = checks
        h.store.close()
output = Path(a.output)
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(results, indent=2), encoding='utf-8')
print(json.dumps(results, indent=2))
raise SystemExit(0 if all(all(checks.values()) for checks in results.values()) else 1)
