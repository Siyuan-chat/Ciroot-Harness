from __future__ import annotations
import argparse,json,sys
from .contracts import load_json, validate_spec
from .errors import HarnessError, PreflightError
from .service import Harness

def main(argv=None):
    p=argparse.ArgumentParser(prog="rh"); sub=p.add_subparsers(dest="cmd",required=True)
    def ws(x): x.add_argument("--workspace",required=True)
    x=sub.add_parser("validate");x.add_argument("--spec",required=True)
    x=sub.add_parser("doctor");x.add_argument("--runtime",required=True);ws(x);x.add_argument("--lang",default="en",choices=("zh","en","ja"))
    x=sub.add_parser("import");x.add_argument("path");ws(x);x.add_argument("--collection",required=True,choices=("baseline","discovery"));x.add_argument("--kind",required=True,choices=("paper","patent"))
    x=sub.add_parser("run");x.add_argument("--spec",required=True);x.add_argument("--runtime",required=True);ws(x)
    x=sub.add_parser("resume");x.add_argument("run_id");x.add_argument("--runtime",required=True);ws(x)
    x=sub.add_parser("status");ws(x)
    x=sub.add_parser("chat");x.add_argument("--runtime",required=True);ws(x);x.add_argument("--lang",default="en",choices=("zh","en","ja"));x.add_argument("--message")
    x=sub.add_parser("report");x.add_argument("run_id");ws(x);x.add_argument("--languages",default="zh,en,ja")
    x=sub.add_parser("review"); rs=x.add_subparsers(dest="review_cmd",required=True);l=rs.add_parser("list");ws(l);l.add_argument("--lang",default="en");d=rs.add_parser("decide");d.add_argument("issue_id");d.add_argument("--decision",required=True);d.add_argument("--note",required=True);ws(d)
    a=p.parse_args(argv)
    try:
        if a.cmd=="validate":
            result=load_json(a.spec); validate_spec(result); print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
        if a.cmd=="doctor":
            result=Harness.doctor(a.runtime,a.lang); print(json.dumps(result,ensure_ascii=False,indent=2)); return 0 if result["ok"] else 3
        h=Harness(a.workspace); result=None
        if a.cmd=="chat": result={"intent":"clarify","message":"Interactive intake is not implemented; use validate/run with a versioned JSON spec."}
        elif a.cmd=="import": result={"document_id":h.import_document(a.path,a.collection,a.kind)}
        elif a.cmd=="run": result={"run_id":h.run(a.spec,a.runtime)}
        elif a.cmd=="resume":
            run=h.store.run(a.run_id)
            if not run: raise PreflightError("run not found")
            if run["status"] not in {"partial","failed","cancelled"}: raise PreflightError("run is not resumable")
            raise PreflightError("resume is not implemented for this run")
        elif a.cmd=="status": result=h.status()
        elif a.cmd=="report": result={"path":str(h.report(a.run_id,a.languages.split(",")))}
        elif a.cmd=="review" and a.review_cmd=="list": result=h.review_list()
        else: h.review_decide(a.issue_id,a.decision,a.note); result={"ok":True}
        print(json.dumps(result,ensure_ascii=False,indent=2));return 4 if a.cmd=="run" and h.store.run(result["run_id"])["status"]=="partial" else 0
    except HarnessError as e: print(json.dumps({"error":e.code,"message":str(e)},ensure_ascii=False),file=sys.stderr);return 2 if e.code=="RH_INVALID_INPUT" else 3
    except (KeyError,ValueError) as e: print(json.dumps({"error":"RH_INVALID_INPUT","message":str(e)}),file=sys.stderr);return 2
if __name__=="__main__": raise SystemExit(main())
