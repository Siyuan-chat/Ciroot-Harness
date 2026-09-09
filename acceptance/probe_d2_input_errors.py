"""D2 safe public validation errors; no Store or CLI access."""
import argparse
import json
import sys
import tempfile
from pathlib import Path

p = argparse.ArgumentParser(); p.add_argument('--source', required=True); p.add_argument('--output', required=True)
a = p.parse_args(); source = Path(a.source).resolve(); sys.path.insert(0, str(source / 'src'))
from research_harness.service import Harness
from research_harness.errors import HarnessError

results = {}
for mode in ('invalid_spec', 'draft_spec', 'broken_fixture_json', 'invalid_fixture_shape'):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); h = Harness(root / 'workspace')
        spec = json.loads((source / 'examples/polymer-design.draft.json').read_text(encoding='utf-8'))
        spec.update(status='ready', unresolved_questions=[])
        if mode == 'invalid_spec': spec['status'] = 'synthetic-error-secret'
        if mode == 'draft_spec': spec.update(status='draft', unresolved_questions=['Synthetic unresolved question.'])
        sp = root / 'spec.json'; sp.write_text(json.dumps(spec), encoding='utf-8')
        fp = root / 'fixture.json'
        fixture = {'candidates': [{'id': 'synthetic-candidate', 'quote': 'Synthetic input.', 'locator': 'line:1'}]}
        if mode == 'invalid_fixture_shape': fixture = {'candidates': [{'id': 'synthetic-bad', 'quote': None}]}
        fp.write_text('{' if mode == 'broken_fixture_json' else json.dumps(fixture), encoding='utf-8')
        checks = {'typed_error': False, 'safe_serializable_error': False, 'no_run_created': False}
        try:
            h.run_fixture(sp, fp)
        except Exception as exc:
            checks['typed_error'] = isinstance(exc, HarnessError)
            if callable(getattr(exc, 'to_dict', None)):
                payload = exc.to_dict(); serialized = json.dumps(payload)
                checks['safe_serializable_error'] = (payload.get('code') in ('RH_INVALID_INPUT', 'RH_PRECONDITION')
                    and isinstance(payload.get('message'), str) and bool(payload['message'])
                    and 'synthetic-error-secret' not in serialized and 'Traceback' not in serialized)
        try: checks['no_run_created'] = h.status() == []
        except Exception: pass
        h.close(); results[mode] = checks
output = Path(a.output); output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(results, indent=2), encoding='utf-8'); print(json.dumps(results, indent=2))
raise SystemExit(0 if all(all(c.values()) for c in results.values()) else 1)
