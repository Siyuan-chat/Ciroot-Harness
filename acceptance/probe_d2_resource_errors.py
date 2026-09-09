"""D2 representative missing resource and export failure through public services."""
import argparse
import json
import sys
import tempfile
from pathlib import Path

p = argparse.ArgumentParser(); p.add_argument('--source', required=True); p.add_argument('--output', required=True)
a = p.parse_args(); source = Path(a.source).resolve(); sys.path.insert(0, str(source / 'src'))
from research_harness.service import Harness
from research_harness.errors import HarnessError

checks = {}
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp); workspace = root / 'workspace'; h = Harness(workspace)
    for name, operation, expected in (
        ('missing_run', lambda: h.get_result('missing-synthetic-run'), 'RH_NOT_FOUND'),
        ('missing_import', lambda: h.import_document(root / 'missing.txt', 'baseline', 'paper'), 'RH_INVALID_INPUT'),
    ):
        checks[name] = False
        try: operation()
        except HarnessError as exc:
            payload = exc.to_dict(); checks[name] = payload.get('code') == expected and bool(payload.get('message'))
        except Exception: pass
    spec = json.loads((source / 'examples/polymer-design.draft.json').read_text(encoding='utf-8'))
    spec.update(status='ready', unresolved_questions=[])
    sp = root / 'spec.json'; sp.write_text(json.dumps(spec), encoding='utf-8')
    fp = root / 'fixture.json'; fp.write_text(json.dumps({'candidates': [
        {'id': 'synthetic-export', 'quote': 'Synthetic export source.', 'locator': 'line:1'}]}), encoding='utf-8')
    events = []
    def block_export(event):
        events.append(event)
        if event['stage'] == 'report' and event['status'] == 'running':
            (workspace / 'reports' / event['run_id']).write_text('synthetic-export-blocker', encoding='utf-8')
    checks['export_failure_structured'] = False
    try:
        result = h.run_fixture(sp, fp, on_progress=block_export)
        checks['export_failure_structured'] = result.get('outcome') == 'partial' and result.get('error', {}).get('code') == 'RH_EXPORT_FAILED'
        h.close(); h = Harness(workspace)
        persisted = h.get_result(result['run_id'])
        checks['export_failure_preserves_facts'] = persisted['outcome'] == 'partial' and bool(persisted['findings'])
        checks['export_failure_artifacts_empty'] = h.get_artifacts(result['run_id'])['files'] == []
        checks['export_failure_terminal_event'] = events[-1]['status'] == 'partial' and events[-1]['stage'] == 'report'
        checks['export_blocker_not_overwritten'] = (workspace / 'reports' / result['run_id']).read_text(encoding='utf-8') == 'synthetic-export-blocker'
    except Exception:
        checks['export_failure_preserves_facts'] = False
    h.close()
output = Path(a.output); output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(checks, indent=2), encoding='utf-8'); print(json.dumps(checks, indent=2))
raise SystemExit(0 if all(checks.values()) else 1)
