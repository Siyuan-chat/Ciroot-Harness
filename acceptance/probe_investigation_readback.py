"""Compare one persisted live run through installed CLI and real MCP STDIO."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys


GUARD = """import sys,runpy
def audit(event,values):
 if event == 'socket.connect':
  addr=values[1]
  if isinstance(addr,tuple) and addr[0] not in ('127.0.0.1','::1','localhost'):
   raise RuntimeError('Readback must not request external sources')
sys.addaudithook(audit)
runpy.run_module(sys.argv.pop(1),run_name='__main__')
"""


async def read_mcp(workspace, run_id, env):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=sys.executable, args=[
        '-c', GUARD, 'research_harness.investigation_mcp', '--workspace', str(workspace)], env=env)
    results = {}
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            for name in ('investigation_status', 'get_result', 'get_artifacts'):
                response = await session.call_tool(name, {'run_id': run_id})
                assert not getattr(response, 'is_error', False), name
                value = getattr(response, 'structured_content', None)
                if value is None:
                    value = json.loads(next(x.text for x in response.content if x.type == 'text'))
                assert 'error' not in value, value
                results[name] = value
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--probe-dir', type=Path, required=True)
    args = parser.parse_args()
    directory = args.probe_dir.resolve()
    accepted = json.loads((directory / 'acceptance.json').read_text(encoding='utf-8'))
    assert accepted['status'] == 'passed'
    workspace, run_id = directory / 'workspace', accepted['run_id']
    env = dict(os.environ)
    env.pop('PYTHONPATH', None)
    env.update(PYTHONIOENCODING='utf-8', LANGCHAIN_TRACING_V2='false', LANGSMITH_TRACING='false')
    cli = {}
    for command in ('status', 'result'):
        completed = subprocess.run([sys.executable, '-c', GUARD,
            'research_harness.investigation_cli', '--workspace', str(workspace), command, run_id],
            env=env, capture_output=True, encoding='utf-8', timeout=60)
        assert completed.returncode == 0, completed.stderr
        cli[command] = json.loads(completed.stdout)
    mcp = asyncio.run(read_mcp(workspace, run_id, env))
    assert cli['status'] == mcp['investigation_status']
    assert cli['result'] == mcp['get_result']
    assert cli['result']['synthetic'] is False
    assert cli['status']['budget'] == accepted['budget']
    assert cli['status']['coverage'] == accepted['source_state']
    assert cli['result']['coverage'] == accepted['source_state']
    assert cli['result']['evidence'] == accepted['result']['evidence']
    report = {'status': 'passed', 'run_id': run_id, 'transport': 'installed CLI and real SDK child-process STDIO',
              'checks': ['same full status', 'same full result', 'same source state and budget as service',
                         'same real evidence', 'readback with external network forbidden'],
              'cli': cli, 'mcp': mcp}
    (directory / 'readback.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('status', 'run_id', 'transport', 'checks')}))


if __name__ == '__main__':
    main()
