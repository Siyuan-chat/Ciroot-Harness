from __future__ import annotations
import argparse,json,sys
from importlib import resources
from pathlib import Path
from .contracts import load_json, validate_spec
from .errors import HarnessError, PreflightError, UnsupportedError
from .service import Harness
from .intake import respond

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "patent-source-diagnose":
        parser = argparse.ArgumentParser(prog="rh patent-source-diagnose")
        parser.add_argument("--workspace", required=True)
        parser.add_argument("--run-id", required=True)
        args = parser.parse_args(argv[1:])
        from .investigation import InvestigationService
        from .patent_source_gateway import PatentSourceGateway
        try:
            service = InvestigationService(args.workspace)
            result = PatentSourceGateway(service).diagnose(args.run_id)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result.get("status") == "diagnosed" else 4
        except HarnessError as error:
            print(json.dumps(error.to_dict(), ensure_ascii=False), file=sys.stderr)
            return 3
        finally:
            if "service" in locals():
                service.close()
    if argv and argv[0] == "patent-source-execute":
        parser = argparse.ArgumentParser(prog="rh patent-source-execute")
        parser.add_argument("--workspace", required=True)
        parser.add_argument("--run-id", required=True)
        parser.add_argument("--task-id", required=True)
        parser.add_argument("--task-version", required=True, type=int)
        parser.add_argument("--request-id", required=True)
        parser.add_argument("--source", required=True)
        parser.add_argument("--operation", required=True)
        params_group=parser.add_mutually_exclusive_group(required=True)
        params_group.add_argument("--params-json", help="JSON object containing only operation parameters")
        params_group.add_argument("--params-file", help="absolute local UTF-8 JSON file containing operation parameters")
        refs_group=parser.add_mutually_exclusive_group(required=True)
        refs_group.add_argument("--input-refs-json", help="JSON array exactly matching the task's frozen input_refs")
        refs_group.add_argument("--input-refs-file", help="absolute local UTF-8 JSON file containing the task's frozen input_refs")
        args = parser.parse_args(argv[1:])
        service = None
        try:
            def read_arg(inline,path,label):
                if path is None: return json.loads(inline)
                target=Path(path)
                if (not target.is_absolute() or path.startswith(("\\\\","//")) or target.suffix.casefold()!=".json"
                        or "\n" in path or "\r" in path):
                    raise ValueError(f"{label} file must be an absolute local path")
                try:
                    resolved=target.resolve(strict=True)
                    resolved_text=str(resolved)
                    if (not resolved.is_file() or resolved_text.startswith(("\\\\","//"))
                            or resolved_text.startswith("\\\\?\\UNC\\") or resolved_text.startswith("//?/UNC/")):
                        raise ValueError(f"{label} file must resolve to an absolute local file")
                    return json.loads(resolved.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError, RuntimeError) as error:
                    raise ValueError(f"{label} file could not be read as valid UTF-8 JSON") from error
            params = read_arg(args.params_json,args.params_file,"params")
            input_refs = read_arg(args.input_refs_json,args.input_refs_file,"input refs")
            if not isinstance(params, dict) or not isinstance(input_refs, list):
                raise ValueError("params-json must be an object and input-refs-json an array")
            from .investigation import InvestigationService
            service = InvestigationService(args.workspace)
            result = service.execute_patent_source(args.run_id, args.task_id, args.task_version,
                args.request_id, args.source, args.operation, params, input_refs=input_refs)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result.get("status") in {"complete", "no_match"} else 4
        except (ValueError, json.JSONDecodeError) as error:
            print(json.dumps({"code": "RH_PATENT_INPUT", "message": str(error)}, ensure_ascii=False), file=sys.stderr)
            return 2
        except HarnessError as error:
            print(json.dumps(error.to_dict(), ensure_ascii=False), file=sys.stderr)
            return 3
        finally:
            if service is not None:
                service.close()
    if argv and argv[0] == "patent-analyze":
        parser = argparse.ArgumentParser(prog="rh patent-analyze")
        parser.add_argument("--input", required=True)
        args = parser.parse_args(argv[1:])
        from .patent_analysis_adapter import load_and_analyze_patent_input
        try:
            result = load_and_analyze_patent_input(args.input)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 4 if result.get("status") == "partial" else 0
        except HarnessError as error:
            print(json.dumps(error.to_dict(), ensure_ascii=False), file=sys.stderr)
            return 2 if error.code == "RH_INVALID_INPUT" else 3
    if argv and argv[0] in {"investigate", "monitor"}:
        from .investigation_cli import main as investigation_main
        return investigation_main(argv[1:] if argv[0] == "investigate" else argv)
    p=argparse.ArgumentParser(prog="rh"); sub=p.add_subparsers(dest="cmd",required=True)
    def ws(x): x.add_argument("--workspace",required=True)
    x=sub.add_parser("validate");x.add_argument("--spec",required=True)
    x=sub.add_parser("doctor");x.add_argument("--runtime",required=True);ws(x);x.add_argument("--lang",default="en",choices=("zh","en","ja"))
    x=sub.add_parser("import");x.add_argument("path");ws(x);x.add_argument("--collection",required=True,choices=("baseline","discovery"));x.add_argument("--kind",required=True,choices=("paper","patent"))
    x=sub.add_parser("run");x.add_argument("--spec",required=True);x.add_argument("--runtime",required=True);ws(x)
    x=sub.add_parser("resume");x.add_argument("run_id");x.add_argument("--runtime",required=True);ws(x)
    x=sub.add_parser("status");ws(x)
    x=sub.add_parser("demo");ws(x);x.add_argument("--spec");x.add_argument("--fixture")
    x=sub.add_parser("chat");x.add_argument("--runtime",required=True);ws(x);x.add_argument("--lang",default="en",choices=("zh","en","ja"));x.add_argument("--message")
    x=sub.add_parser("report");x.add_argument("run_id");ws(x);x.add_argument("--languages",default="zh,en,ja")
    x=sub.add_parser("review"); rs=x.add_subparsers(dest="review_cmd",required=True);l=rs.add_parser("list");ws(l);l.add_argument("--lang",default="en");d=rs.add_parser("decide");d.add_argument("issue_id");d.add_argument("--decision",required=True);d.add_argument("--note",required=True);ws(d)
    a=p.parse_args(argv)
    h=None
    try:
        if a.cmd=="validate":
            result=load_json(a.spec); validate_spec(result); print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
        if a.cmd=="doctor":
            result=Harness.doctor(a.runtime,a.lang); print(json.dumps(result,ensure_ascii=False,indent=2)); return 0 if result["ok"] else 3
        h=Harness(a.workspace); result=None
        if a.cmd=="chat": raise UnsupportedError("interactive chat is not supported")
        elif a.cmd=="import": result=h.import_document(a.path,a.collection,a.kind)
        elif a.cmd=="run": result={"run_id":h.run(a.spec,a.runtime)}
        elif a.cmd=="resume":
            run=h.store.run(a.run_id)
            if not run: raise PreflightError("run not found")
            if run["status"] not in {"partial","failed","cancelled"}: raise PreflightError("run is not resumable")
            raise PreflightError("resume is not implemented for this run")
        elif a.cmd=="status": result=h.status()
        elif a.cmd=="demo":
            base=resources.files("research_harness").joinpath("fixtures"); spec=a.spec or str(base.joinpath("demo-spec.json")); fixture=a.fixture or str(base.joinpath("demo.json"))
            if not a.spec: h.import_document(base.joinpath("baseline.txt"),"baseline","paper")
            result=h.run_fixture(spec,fixture)
        elif a.cmd=="report": result={"path":str(h.report(a.run_id,a.languages.split(",")))}
        elif a.cmd=="review" and a.review_cmd=="list": result=h.review_list()
        else: h.review_decide(a.issue_id,a.decision,a.note); result={"ok":True}
        print(json.dumps(result,ensure_ascii=False,indent=2));return {"completed":0,"partial":4,"failed":3}.get(result.get("outcome"),0) if a.cmd=="demo" else (4 if a.cmd=="run" and h.store.run(result["run_id"])["status"]=="partial" else 0)
    except HarnessError as e: print(json.dumps(e.to_dict(),ensure_ascii=False),file=sys.stderr);return 2 if e.code=="RH_INVALID_INPUT" else 3
    except (KeyError,ValueError): print(json.dumps({"error":"RH_INVALID_INPUT","message":"invalid input"}),file=sys.stderr);return 2
    finally:
        if h is not None: h.close()
if __name__=="__main__": raise SystemExit(main())
