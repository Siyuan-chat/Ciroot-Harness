from pathlib import Path
import contextlib, io, json, zipfile, copy
root = Path.cwd()
base = root / '.local/acceptance/ceb6aff'
old = root / 'acceptance/probe_bc0df21.py'
code = old.read_text(encoding='utf-8').replace('base=root/".local/acceptance/bc0df21"', 'base=root/".local/acceptance/ceb6aff"')
code = code.replace('sys.path.insert(0,str(source/"src"))', '')
code = code.replace('env["PYTHONPATH"]=str(source/"src")', 'env.pop("PYTHONPATH",None)')
ns = {'__file__': str(old), '__name__': '__main__'}
with contextlib.redirect_stdout(io.StringIO()):
    try:
        exec(compile(code, str(old), 'exec'), ns)
    except SystemExit as exc:
        regression_exit = exc.code
results = ns['results']
results['previous_regression_exit'] = regression_exit
results['chat_actual_behavior'] = {}
for lang, message in [('zh', '我想调查聚合物设计，请帮我整理需求'), ('en', 'Help me define a polymer design investigation'), ('ja', 'ポリマー設計の調査要件を整理してください')]:
    results['chat_actual_behavior'][lang] = ns['cli'](['chat','--runtime',str(ns['rp']),'--workspace',str(ns['case']/('chat-'+lang)),'--lang',lang,'--message',message])
s = copy.deepcopy(ns['s'])
criterion = {'id':'duplicate_id','description':'synthetic criterion','mode':'qualitative','target':None,'required_conditions':{},'required':True,'minimum_evidence':'fulltext'}
s['criteria'] = [criterion, dict(criterion)]
try:
    ns['validate_spec'](s)
    results['duplicate_criterion_ids'] = 'ACCEPTED_INVALID'
except Exception as exc:
    results['duplicate_criterion_ids'] = type(exc).__name__
r = copy.deepcopy(ns['runtime'])
r['llm'].update(model='synthetic-local',local=True)
r['retrieval']['embedding']['model'] = 'SYNTHETIC_UNAVAILABLE_MODEL'
for cfg in r['sources'].values(): cfg['enabled'] = False
ns['rp'].write_text(json.dumps(r),encoding='utf-8')
results['doctor_unavailable_hybrid'] = ns['cli'](['doctor','--runtime',str(ns['rp']),'--workspace',str(ns['case']/'doctor')])
with zipfile.ZipFile(base/'dist/research_harness-0.1.0-py3-none-any.whl') as z:
    results['wheel_schema_members'] = [p for p in z.namelist() if p.endswith('.schema.json')]
import research_harness
results['tested_import_path'] = str(Path(research_harness.__file__).resolve())
(base/'acceptance-probes.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(results,ensure_ascii=False,indent=2))

# Exit nonzero while any observed acceptance violation remains.
violations = [
    regression_exit != 0,
    results['duplicate_criterion_ids'] == 'ACCEPTED_INVALID',
    results['doctor_unavailable_hybrid']['returncode'] == 0,
    any('not implemented' in item['stdout'] for item in results['chat_actual_behavior'].values()),
    len(results['wheel_schema_members']) != 2,
]
raise SystemExit(1 if any(violations) else 0)
