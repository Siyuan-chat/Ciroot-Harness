"""Independent D19 contract probes. Synthetic inputs; all network blocked.

Run from an installed wheel or select an immutable source checkout explicitly.
This probe does not generate model answers or claim scientific validation.
"""
from __future__ import annotations

import argparse
import copy
import json
import socket
import sys
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-root', type=Path)
    parser.add_argument('--spec', type=Path, required=True)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--scenario', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--checkpoint', required=True)
    args = parser.parse_args()
    if args.source_root:
        sys.path.insert(0, str(args.source_root.resolve() / 'src'))

    network_attempts = []

    def deny_network(*_args, **_kwargs):
        network_attempts.append('blocked')
        raise AssertionError('External network is forbidden in P1 acceptance')

    socket.socket.connect = deny_network
    socket.create_connection = deny_network
    from research_harness.investigation import InvestigationService
    from research_harness.errors import HarnessError

    spec, runtime, scenario = [json.loads(p.read_text(encoding='utf-8-sig'))
                               for p in (args.spec, args.runtime, args.scenario)]
    checks = []

    def require(condition, message):
        if not condition:
            raise AssertionError(message)

    def rejects(call):
        try:
            call()
        except HarnessError as exc:
            require(isinstance(exc.to_dict(), dict), 'Error must have public JSON projection')
            return exc.to_dict().get('code')
        raise AssertionError('Invalid operation was accepted')

    def case(name, test):
        with tempfile.TemporaryDirectory(prefix='d19-independent-') as tmp:
            service = InvestigationService(tmp)
            try:
                test(service, Path(tmp))
                checks.append({'id': name, 'status': 'passed'})
            except Exception as exc:
                checks.append({'id': name, 'status': 'failed', 'type': type(exc).__name__,
                               'detail': str(exc)[:700]})
            finally:
                try:
                    service.close()
                except Exception:
                    pass

    def create(service):
        return service.create_investigation(copy.deepcopy(spec), copy.deepcopy(runtime),
                                            copy.deepcopy(scenario))['run_id']

    def draft(service, _):
        value = copy.deepcopy(spec)
        value['status'] = 'draft'
        before = service.status()
        rejects(lambda: service.create_investigation(value, runtime, scenario))
        require(service.status() == before, 'Rejected draft created or modified a run')

    def unknown_execution(service, _):
        value = copy.deepcopy(runtime)
        value['mode'] = 'unimplemented-provider'
        before = service.status()
        rejects(lambda: service.create_investigation(spec, value, scenario))
        require(service.status() == before, 'Unsupported execution created a run')

    def tasks_json(service, _):
        run = create(service)
        tasks = service.get_pending_tasks(run)
        require(bool(tasks), 'Ready host run must expose a pending model task')
        first = tasks[0]
        required = {'task_id', 'task_version', 'role', 'task_type', 'payload',
                    'input_refs', 'allowed_operations', 'output_schema'}
        require(required <= first.keys(), 'Task projection is missing contract fields')
        require(isinstance(first['payload'], dict), 'Task payload is serialized twice')
        require(isinstance(first['output_schema'], dict), 'Schema is serialized twice')
        require(first['role'] == 'planning', 'Initial model role must plan the investigation')
        json.dumps(tasks, ensure_ascii=False, allow_nan=False)

    def invalid_result(service, _):
        run = create(service)
        tasks = service.get_pending_tasks(run)
        task = tasks[0]
        before = service.status(run)
        for result in ({}, {'not_a_valid_role_result': True}, [], 'invalid'):
            rejects(lambda: service.submit_model_result(run, task['task_id'], result,
                                                        task['task_version']))
            require(service.get_pending_tasks(run) == tasks, 'Invalid result consumed a task')
            require(service.status(run) == before, 'Invalid result changed persistent progress')

    def stale_result(service, _):
        run = create(service)
        tasks = service.get_pending_tasks(run)
        task = tasks[0]
        rejects(lambda: service.submit_model_result(run, task['task_id'], {},
                                                    task['task_version'] + 1))
        require(service.get_pending_tasks(run) == tasks, 'Stale version changed task state')

    def cross_run(service, _):
        first, second = create(service), create(service)
        first_tasks, second_tasks = service.get_pending_tasks(first), service.get_pending_tasks(second)
        task = first_tasks[0]
        rejects(lambda: service.submit_model_result(second, task['task_id'], {}, task['task_version']))
        require(service.get_pending_tasks(first) == first_tasks, 'Foreign run consumed the owner task')
        require(service.get_pending_tasks(second) == second_tasks, 'Foreign task altered second run')

    def waiting_reentry(service, _):
        run = create(service)
        tasks = service.get_pending_tasks(run)
        for _ in range(3):
            result = service.advance_investigation(run)
            require(result.get('outcome') != 'completed', 'Waiting model task became completed')
            require(service.get_pending_tasks(run) == tasks, 'Waiting advance duplicated/replaced task')

    def restart(service, workspace):
        run = create(service)
        tasks, before = service.get_pending_tasks(run), service.status(run)
        service.close()
        other = InvestigationService(workspace)
        try:
            require(other.get_pending_tasks(run) == tasks, 'Task lost or changed after restart')
            require(other.status(run) == before, 'Run state/budget changed after restart')
            other.resume_investigation(run)
            require(other.get_pending_tasks(run) == tasks, 'Resume recreated waiting task')
        finally:
            other.close()

    def missing_run(service, _):
        rejects(lambda: service.status('inv-does-not-exist'))
        rejects(lambda: service.get_pending_tasks('inv-does-not-exist'))

    for name, test in [('C1-draft', draft), ('C1-execution-mode', unknown_execution),
                       ('C1-task-json', tasks_json), ('C1-role-validation', invalid_result),
                       ('C1-stale-result', stale_result), ('C1-ownership', cross_run),
                       ('C1-wait-idempotence', waiting_reentry), ('C1-restart', restart),
                       ('C1-missing-run', missing_run)]:
        case(name, test)
    checks.append({'id': 'P1-network-boundary',
                   'status': 'passed' if not network_attempts else 'failed',
                   'attempts': len(network_attempts)})
    result = {'checkpoint': args.checkpoint, 'synthetic': True,
              'scope': 'C1 boundary probes only; not full P1 acceptance', 'checks': checks,
              'passed': sum(x['status'] == 'passed' for x in checks), 'total': len(checks)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['passed'] == result['total'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
