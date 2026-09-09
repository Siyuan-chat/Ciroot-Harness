"""Final D2 installed-wheel acceptance; run with a fresh venv Python, no src path."""
import argparse
import contextlib
import io
import json
import os
import socket
import subprocess
import sys
from importlib import metadata, resources
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('--output', required=True)
a = p.parse_args()
out = Path(a.output).resolve()
out.mkdir(parents=True, exist_ok=True)
os.chdir(out)
import research_harness
from research_harness.service import Harness
from research_harness.cli import main

checks = {}
module_path = Path(research_harness.__file__).resolve()
checks['installed_site_packages'] = module_path.is_relative_to(Path(sys.prefix).resolve() / 'Lib/site-packages')
checks['isolated_venv'] = sys.prefix != sys.base_prefix and 'include-system-site-packages = false' in (Path(sys.prefix) / 'pyvenv.cfg').read_text()
base = resources.files('research_harness').joinpath('fixtures')
checks['packaged_baseline'] = 'Synthetic' in base.joinpath('baseline.txt').read_text(encoding='utf-8')
for source, target in [('demo-spec.json', 'research.json'), ('demo.json', 'candidates.json')]:
    Path(target).write_text(base.joinpath(source).read_text(encoding='utf-8'), encoding='utf-8')
cli = Path(sys.executable).with_name('rh.exe')
log = []
def command(*args):
    cp = subprocess.run([str(cli), *map(str, args)], capture_output=True, text=True, encoding='utf-8', env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
    log.append({'args': list(map(str, args)), 'exit': cp.returncode, 'stdout': cp.stdout, 'stderr': cp.stderr})
    return cp.returncode, json.loads(cp.stdout or cp.stderr)

ws = out / 'demo'
code, run = command('demo', '--workspace', ws)
checks['documented_demo_completed'] = code == 0 and run['outcome'] == 'completed'
code, status = command('status', '--workspace', ws)
checks['cli_status'] = code == 0 and status[0]['run_id'] == run['run_id']
h = Harness(ws)
result = h.get_result(run['run_id'])
artifacts = h.get_artifacts(run['run_id'])['files']
checks['eight_real_report_artifacts'] = len(artifacts) == 8 and all(Path(f['path']).is_file() and Path(f['path']).stat().st_size > 0 for f in artifacts)
checks['three_report_languages'] = {f['language'] for f in artifacts} == {None, 'zh', 'en', 'ja'}
checks['two_findings_one_issue'] = len(result['findings']) == 2 and len(h.review_list()) == 1
h.close()
code, issues = command('review', 'list', '--workspace', ws)
issue_id = issues[0]['id']
code, _ = command('review', 'decide', issue_id, '--decision', 'watch', '--note', 'Synthetic installed acceptance.', '--workspace', ws)
code2, issues = command('review', 'list', '--workspace', ws)
checks['documented_review_persists'] = code == code2 == 0 and issues[0]['human_decision'] == 'watch'
before = {f['path']: Path(f['path']).read_bytes() for f in artifacts}
code, _ = command('report', run['run_id'], '--workspace', ws, '--languages', 'zh,en,ja')
checks['documented_reexport_frozen'] = code == 0 and all(Path(path).read_bytes() == data for path, data in before.items())
code, _ = command('validate', '--spec', 'research.json')
checks['documented_validate'] = code == 0
spec = json.loads(Path('research.json').read_text())
spec['execution']['budget']['max_candidates'] = 1
Path('limited.json').write_text(json.dumps(spec), encoding='utf-8')
original = Path('limited.json').read_bytes()
code, limited = command('demo', '--workspace', out / 'custom', '--spec', 'limited.json', '--fixture', 'candidates.json')
checks['custom_spec_budget_partial'] = code == 4 and limited['outcome'] == 'partial' and Path('limited.json').read_bytes() == original
spec['status'] = 'draft'
Path('draft.json').write_text(json.dumps(spec), encoding='utf-8')
code, error = command('demo', '--workspace', out / 'draft', '--spec', 'draft.json')
checks['draft_refused'] = code == 3 and error['code'] == 'RH_PRECONDITION'
code, error = command('chat', '--workspace', out / 'chat', '--runtime', 'unused.json', '--message', 'Synthetic text')
checks['chat_truthfully_unsupported'] = code == 3 and error['code'] == 'RH_UNSUPPORTED'

network_attempts = []
def deny(*args, **kwargs):
    network_attempts.append(True)
    raise AssertionError('Offline demo attempted network')
socket.socket.connect = deny
socket.create_connection = deny
captured = io.StringIO()
with contextlib.redirect_stdout(captured):
    offline_code = main(['demo', '--workspace', str(out / 'offline')])
checks['default_demo_no_network'] = offline_code == 0 and not network_attempts
report = {'checks': checks, 'python': sys.version, 'module': str(module_path), 'versions': {name: metadata.version(name) for name in ('research-harness', 'langgraph', 'jsonschema', 'requests')}, 'cli_commands': log}
(out / 'installed-result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(checks, indent=2))
raise SystemExit(0 if all(checks.values()) else 1)
