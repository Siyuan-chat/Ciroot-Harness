"""D2 application client: use public Harness methods without Store/CLI access."""
import argparse
import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

p = argparse.ArgumentParser(); p.add_argument('--source', required=True); p.add_argument('--output', required=True)
a = p.parse_args(); source = Path(a.source).resolve(); sys.path.insert(0, str(source / 'src'))
from research_harness.service import Harness

checks = {}; captured = io.StringIO()
with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(captured):
    root = Path(tmp); workspace = root / 'workspace'; h = Harness(workspace)
    baseline = root / 'baseline.txt'; baseline.write_text('Synthetic service baseline.', encoding='utf-8')
    imported = h.import_document(baseline, 'baseline', 'paper')
    spec = json.loads((source / 'examples/polymer-design.draft.json').read_text(encoding='utf-8'))
    spec.update(status='ready', unresolved_questions=[])
    sp = root / 'spec.json'; sp.write_text(json.dumps(spec), encoding='utf-8')
    saved = h.save_spec(sp)
    fp = root / 'fixture.json'; fp.write_text(json.dumps({'candidates': [
        {'id': 'synthetic-service', 'quote': 'Synthetic service evidence gap.', 'locator': 'line:1', 'missing': True}]}), encoding='utf-8')
    events = []; out = h.run_fixture(sp, fp, on_progress=events.append)
    result = h.get_result(out['run_id']); summaries = h.status(); artifacts = h.get_artifacts(out['run_id'])
    files = artifacts.get('files', [])
    checks['public_summary_fields'] = all(set(('run_id', 'project_id', 'revision', 'outcome', 'stage', 'error', 'limits', 'artifacts')) <= set(r) for r in summaries)
    checks['results_are_structured'] = isinstance(result['report_data'], dict) and isinstance(result['findings'], list) and bool(result['findings'])
    checks['summary_has_no_database_json'] = all('manifest' not in r and 'report_data' not in r for r in summaries)
    checks['artifact_records_complete'] = len(files) == 8 and all(set(('language', 'format', 'path')) <= set(f) for f in files)
    checks['artifact_paths_exist_in_workspace'] = all(Path(f['path']).is_absolute() and Path(f['path']).is_file() and Path(f['path']).resolve().is_relative_to(workspace.resolve()) for f in files)
    checks['artifact_languages'] = {f['language'] for f in files} == {None, 'zh', 'en', 'ja'}
    checks['artifact_result_consistency'] = result['artifacts'] == artifacts
    issue = h.review_list()[0]
    updated = h.review_decide(issue['id'], 'watch', 'Synthetic public decision.')
    checks['decision_returns_updated_issue'] = updated['status'] == 'resolved' and updated['human_decision'] == 'watch' and isinstance(updated['events'], list)
    h.close(); h = Harness(workspace)
    checks['public_reopen_preserves_decision'] = h.review_list()[0]['human_decision'] == 'watch'
    checks['frozen_result_distinct_from_current_review'] = h.get_result(out['run_id'])['issues'][0]['human_decision'] is None
    def failing_source(candidates): raise RuntimeError('synthetic-service-secret')
    failed = h.run_fixture(sp, fp, source_adapter=failing_source)
    failure_summary = next(r for r in h.status() if r['run_id'] == failed['run_id'])
    checks['failure_summary_exposes_safe_error'] = failure_summary.get('error', {}).get('code') == 'source_failed' and failure_summary['stage'] == 'search'
    json.dumps([imported, saved, out, result, summaries, artifacts, updated, events, failure_summary])
    checks['public_payloads_json_serializable'] = True
    h.close()
checks['no_stdout_dependency'] = captured.getvalue() == ''
output = Path(a.output); output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(checks, indent=2), encoding='utf-8'); print(json.dumps(checks, indent=2))
raise SystemExit(0 if all(checks.values()) else 1)
