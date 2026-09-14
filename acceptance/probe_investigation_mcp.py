"""Independent real STDIO probe against the D19 service, not a fake facade."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


async def exercise(args, workspace, spec, runtime, scenario):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    env = dict(os.environ)
    env.update(PYTHONIOENCODING='utf-8', LANGCHAIN_TRACING_V2='false', LANGSMITH_TRACING='false')
    env.pop('PYTHONPATH', None)
    if args.source_root:
        env['PYTHONPATH'] = str(args.source_root.resolve() / 'src')
    guard = (
        "import sys,socket,runpy\n"
        "def audit(event,values):\n"
        " if event == 'socket.connect':\n"
        "  addr=values[1]\n"
        "  if isinstance(addr,tuple) and addr[0] not in ('127.0.0.1','::1','localhost'):\n"
        "   raise RuntimeError('P1 external network forbidden')\n"
        "sys.addaudithook(audit)\n"
        "runpy.run_module('research_harness.investigation_mcp',run_name='__main__')\n"
    )
    params = StdioServerParameters(command=sys.executable,
                                  args=['-c', guard, '--workspace', str(workspace)], env=env)
    observations = []

    def payload(result):
        value = getattr(result, 'structured_content', None)
        if value is None:
            chunks = [c.text for c in result.content if getattr(c, 'type', None) == 'text']
            value = json.loads(chunks[0])
        return value

    async def call(session, name, parameters):
        result = await session.call_tool(name, parameters)
        assert not getattr(result, 'is_error', False), f'MCP tool failed: {name}'
        return payload(result)

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            names = {t.name for t in listed.tools}
            assert {'doctor', 'create_investigation', 'get_pending_tasks', 'submit_model_result',
                    'resume_investigation', 'get_result', 'create_monitor', 'review_decide'} <= names
            observations.append('real SDK initialize and tool discovery')
            doctor = await call(session, 'doctor', {})
            assert not doctor.get('error'), 'Doctor returned a service error'
            created = await call(session, 'create_investigation',
                                 {'spec': spec, 'runtime': runtime, 'scenario': scenario})
            run_id = created['run_id']
            raw = await call(session, 'get_pending_tasks', {'run_id': run_id})
            tasks = raw.get('result', raw.get('tasks')) if isinstance(raw, dict) else raw
            assert isinstance(tasks, list) and tasks
            task = tasks[0]
            invalid = await call(session, 'submit_model_result',
                                 {'run_id': run_id, 'task_id': task['task_id'],
                                  'task_version': task['task_version'], 'result': {}})
            assert invalid.get('error', {}).get('code', '').startswith('RH_')
            again = await call(session, 'get_pending_tasks', {'run_id': run_id})
            assert again == raw, 'Rejected MCP submission consumed pending task'
            observations.append('real service create/task/rejected result through STDIO')

    # A second process must restore the same persisted task, without creating it again.
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await call(session, 'resume_investigation', {'run_id': run_id})
            resumed = await call(session, 'get_pending_tasks', {'run_id': run_id})
            assert resumed == raw, 'STDIO restart changed waiting task identity'
            observations.append('second STDIO process resumes identical pending task')
    return observations


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--source-root', type=Path)
    p.add_argument('--spec', required=True, type=Path)
    p.add_argument('--runtime', required=True, type=Path)
    p.add_argument('--scenario', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--checkpoint', required=True)
    args = p.parse_args()
    inputs = [json.loads(path.read_text(encoding='utf-8-sig')) for path in
              (args.spec, args.runtime, args.scenario)]
    try:
        with tempfile.TemporaryDirectory(prefix='d19-mcp-independent-') as tmp:
            observations = asyncio.run(exercise(args, Path(tmp), *inputs))
        result = {'status': 'passed', 'checkpoint': args.checkpoint, 'synthetic': True,
                  'transport': 'actual child-process STDIO', 'observations': observations,
                  'scope': 'service and protocol; not host model reasoning'}
    except Exception as exc:
        result = {'status': 'failed', 'checkpoint': args.checkpoint,
                  'type': type(exc).__name__, 'detail': str(exc)[:1200]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
