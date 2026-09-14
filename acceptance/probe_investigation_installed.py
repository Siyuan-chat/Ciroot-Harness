"""Installed wheel acceptance through real CLI, PowerShell, and packaged fixtures."""
import argparse,hashlib,importlib.util,json,os,shutil,subprocess,sys
from importlib import resources
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--source-artifacts',type=Path,required=True);p.add_argument('--expected-site',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--checkpoint',required=True);p.add_argument('--wheel',type=Path,required=True);a=p.parse_args()
a.output_dir=a.output_dir.resolve();a.output_dir.mkdir(parents=True,exist_ok=True)
env=dict(os.environ);env.pop('PYTHONPATH',None);env.update(PYTHONIOENCODING='utf-8',PYTHONUTF8='1',LANGCHAIN_TRACING_V2='false',LANGSMITH_TRACING='false')
import research_harness
from research_harness.investigation import InvestigationService
assert Path(research_harness.__file__).resolve().is_relative_to(a.expected_site.resolve()),'Project imported from checkout instead of installed wheel'
pack=resources.files('research_harness');counts={name:len(list(pack.joinpath(name).iterdir())) for name in ('schemas','prompts/investigation','examples/investigation')};assert counts['schemas']>=5 and counts['prompts/investigation']>=9 and counts['examples/investigation']>=7
inputs=a.output_dir/'inputs';inputs.mkdir(exist_ok=True)
for name in ('synthetic-spec','synthetic-runtime','synthetic-scenario','synthetic-profile','synthetic-monitor-spec'):
 (inputs/(name+'.json')).write_text(pack.joinpath('examples','investigation',name+'.json').read_text(encoding='utf-8'),encoding='utf-8')
def call(argv):
 cp=subprocess.run([str(x) for x in argv],capture_output=True,text=True,encoding='utf-8',env=env,cwd=a.output_dir,timeout=45)
 assert cp.returncode==0,{'argv':list(map(str,argv)),'code':cp.returncode,'stdout':cp.stdout,'stderr':cp.stderr}
 return json.loads(cp.stdout.lstrip('\ufeff'))
checks=[];ws=a.output_dir/'investigation-workspace';base=[sys.executable,'-m','research_harness.cli','investigate','--workspace',ws]
assert call(base+['doctor'])['ok'] is True
native=Path(sys.executable).with_name('rh.exe');assert native.exists() and call([native,'investigate','--workspace',ws,'doctor'])['ok']
run=call(base+['start','--spec',inputs/'synthetic-spec.json','--runtime',inputs/'synthetic-runtime.json','--scenario',inputs/'synthetic-scenario.json'])['run_id'];assert call(base+['tasks',run])[0]['role']=='planning'
ps=shutil.which('pwsh') or shutil.which('powershell');assert ps
psbase=[ps,'-NoProfile','-File',a.source_artifacts.resolve()/'scripts/investigation.ps1','-Workspace',ws,'-PythonExecutable',sys.executable]
assert call(psbase+['-Command','doctor'])['ok']
assert call(psbase+['-Command','status','-RunId',run])['run_id']==run
checks.append('installed native rh, module CLI, PowerShell doctor and run-specific status')
module_spec=importlib.util.spec_from_file_location('packaged_replay_helper',a.source_artifacts.resolve()/'scripts/investigation_replay.py');driver=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(driver)
roles=[]
with InvestigationService(ws) as service:
 for _ in range(16):
  for task in service.get_pending_tasks(run):
   roles.append(task['role']);service.submit_model_result(run,task['task_id'],driver.result_for(task),task['task_version'])
  service.advance_investigation(run)
  if not service.get_pending_tasks(run) and service.status(run)['outcome'] in ('completed','partial'):break
 assert service.get_result(run)['outcome']=='completed' and len(set(roles))==8
 exported=service.export_report(run);md=[x for x in exported['artifacts'] if x['format']=='markdown'];assert len(md)==6
 before=service.status(run)['budget'];hashes={x['path']:hashlib.sha256((ws/x['path']).read_bytes()).hexdigest() for x in exported['artifacts']}
ps_export=call(psbase+['-Command','report','-RunId',run]);assert len([x for x in ps_export['artifacts'] if x['format']=='markdown'])==6
assert call(base+['status',run])['budget']==before
assert all(hashlib.sha256((ws/path).read_bytes()).hexdigest()==digest for path,digest in hashes.items())
checks.append('installed eight-role replay with packaged fixtures, six reports, and PowerShell frozen export')
mon_ws=a.output_dir/'monitor-workspace';monbase=[native,'monitor','--workspace',mon_ws]
m=call(monbase+['create','--profile',inputs/'synthetic-profile.json','--spec',inputs/'synthetic-monitor-spec.json','--runtime',inputs/'synthetic-runtime.json','--scenario',inputs/'synthetic-scenario.json'])['monitor_id']
profile=json.loads((inputs/'synthetic-profile.json').read_text(encoding='utf-8'));profile['rule_version']='independent-rule-2';(inputs/'profile-v2.json').write_text(json.dumps(profile),encoding='utf-8')
update=call([ps,'-NoProfile','-File',a.source_artifacts.resolve()/'scripts/investigation.ps1','-Monitor','-Command','profile-update','-Workspace',mon_ws,'-RunId',m,'-Profile',inputs/'profile-v2.json','-PythonExecutable',sys.executable]);assert update['profile_revision']==2
assert call(monbase+['status',m])['rule_version']=='independent-rule-2'
checks.append('installed monitor CLI create and actual PowerShell profile update')
record={'checkpoint':a.checkpoint,'status':'passed','synthetic':True,'project_import':research_harness.__file__,'wheel_sha256':hashlib.sha256(a.wheel.read_bytes()).hexdigest(),'shared_dependencies':True,'PYTHONPATH':False,'resources':counts,'checks':checks,'run_id':run,'monitor_id':m,'demo_reports':[{'type':x['type'],'language':x['language'],'path':str(ws/x['path'])} for x in md]}
(a.output_dir/'acceptance.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(record,ensure_ascii=False))
