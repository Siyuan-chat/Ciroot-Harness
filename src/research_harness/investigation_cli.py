"""Machine-readable CLI adapter for the offline InvestigationService."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _json(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        pass
    path = Path(value)
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return json.loads(value)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="rh investigate")
    p.add_argument("--workspace", required=True)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    x = sub.add_parser("plan-validate"); x.add_argument("--plan", required=True)
    x = sub.add_parser("start"); x.add_argument("--spec", required=True); x.add_argument("--runtime", required=True); x.add_argument("--scenario")
    x = sub.add_parser("tasks"); x.add_argument("run_id")
    x = sub.add_parser("submit"); x.add_argument("run_id"); x.add_argument("task_id"); x.add_argument("--result", required=True); x.add_argument("--task-version", required=True, type=int)
    for name in ("work", "resume", "status", "result", "report"):
        x = sub.add_parser(name)
        if name not in ("status",): x.add_argument("run_id")
        elif name == "status": x.add_argument("run_id", nargs="?")
        if name == "report": x.add_argument("--languages")
    return p


def _monitor_parser(p: argparse.ArgumentParser) -> None:
    p.add_argument("--workspace", required=True)
    sub = p.add_subparsers(dest="command", required=True)
    x=sub.add_parser("validate"); x.add_argument("--profile",required=True);x.add_argument("--spec",required=True);x.add_argument("--runtime",required=True)
    x=sub.add_parser("create"); x.add_argument("--profile",required=True);x.add_argument("--spec",required=True);x.add_argument("--runtime",required=True);x.add_argument("--scenario")
    x=sub.add_parser("run-once");x.add_argument("monitor_id");x.add_argument("--scenario")
    for name in ("status", "pause", "resume"):
        x=sub.add_parser(name);x.add_argument("monitor_id")
    x=sub.add_parser("review");x.add_argument("--monitor-id")
    x=sub.add_parser("decide");x.add_argument("issue_id");x.add_argument("--decision",required=True);x.add_argument("--note",default="")


def _emit(value: Any) -> int:
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "monitor":
        parser = argparse.ArgumentParser(prog="rh monitor"); _monitor_parser(parser)
        args = parser.parse_args(argv[1:]); family = "monitor"
    else:
        parser = _parser(); args = parser.parse_args(argv); family = "investigate"
    try:
        from research_harness.investigation import InvestigationService
        service = InvestigationService(args.workspace)
    except Exception as exc:
        print(json.dumps({"error": {"code": getattr(exc, "code", "RH_INVESTIGATION_INTERNAL"), "message": "service initialization failed"}}, ensure_ascii=False), file=sys.stderr)
        return 1
    try:
        if family == "investigate":
            c=args.command
            if c == "doctor": result=service.doctor()
            elif c == "plan-validate": result=service.validate_plan(_json(args.plan))
            elif c == "start": result=service.create_investigation(_json(args.spec), _json(args.runtime), _json(args.scenario) if args.scenario else None)
            elif c == "tasks": result=service.get_pending_tasks(args.run_id)
            elif c == "submit": result=service.submit_model_result(args.run_id,args.task_id,_json(args.result),args.task_version)
            elif c == "work": result=service.advance_investigation(args.run_id)
            elif c == "resume": result=service.resume_investigation(args.run_id)
            elif c == "status": result=service.status(args.run_id) if args.run_id else service.status()
            elif c == "result": result=service.get_result(args.run_id)
            else: result=service.export_report(args.run_id,args.languages.split(",") if args.languages else None)
        else:
            c=args.command
            if c == "validate": result=service.validate_monitor(_json(args.profile),_json(args.spec),_json(args.runtime))
            elif c == "create": result=service.create_monitor(_json(args.profile),_json(args.spec),_json(args.runtime),_json(args.scenario) if args.scenario else None)
            elif c == "run-once": result=service.run_monitor_once(args.monitor_id,_json(args.scenario) if args.scenario else None)
            elif c == "status": result=service.monitor_status(args.monitor_id)
            elif c == "pause": result=service.pause_monitor(args.monitor_id)
            elif c == "resume": result=service.resume_monitor(args.monitor_id)
            elif c == "review": result=service.review_list(args.monitor_id)
            else: result=service.review_decide(args.issue_id,args.decision,args.note)
        return _emit(result)
    except Exception as exc:
        code=getattr(exc,"code","RH_INVESTIGATION_INTERNAL")
        print(json.dumps({"error":{"code":code if isinstance(code,str) else "RH_INVESTIGATION_INTERNAL","message":"operation failed"}},ensure_ascii=False),file=sys.stderr)
        return 2
    finally:
        service.close()


if __name__ == "__main__": raise SystemExit(main())
