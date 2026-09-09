from __future__ import annotations
import argparse,json,sys
from .errors import HarnessError
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
    x=sub.add_parser("report");x.add_argument("run_id");ws(x);x.add_argument("--languages",default="zh,en,ja")
    x=sub.add_parser("review"); rs=x.add_subparsers(dest="review_cmd",required=True);l=rs.add_parser("list");ws(l);l.add_argument("--lang",default="en");d=rs.add_parser("decide");d.add_argument("issue_id");d.add_argument("--decision",required=True);d.add_argument("--note",required=True);ws(d)
    a=p.parse_args(argv)
    try:
        h=Harness(getattr(a,"workspace",".")); result=None
        if a.cmd=="validate": result=h.validate(a.spec)
        elif a.cmd=="doctor": result=h.doctor(a.runtime,a.lang)
        elif a.cmd=="import": result={"document_id":h.import_document(a.path,a.collection,a.kind)}
        elif a.cmd=="run": result={"run_id":h.run(a.spec,a.runtime)}
        elif a.cmd=="resume": result={"run":h.store.run(a.run_id),"note":"resume is safe only after a persisted partial run; no online state is recreated by the local core"}
        elif a.cmd=="status": result=h.status()
        elif a.cmd=="report": result={"path":str(h.report(a.run_id,a.languages.split(",")))}
        elif a.cmd=="review" and a.review_cmd=="list": result=h.review_list()
        else: h.review_decide(a.issue_id,a.decision,a.note); result={"ok":True}
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except HarnessError as e: print(json.dumps({"error":e.code,"message":str(e)},ensure_ascii=False),file=sys.stderr);return 2 if e.code=="RH_INVALID_INPUT" else 3
    except (KeyError,ValueError) as e: print(json.dumps({"error":"RH_INVALID_INPUT","message":str(e)}),file=sys.stderr);return 2
if __name__=="__main__": raise SystemExit(main())
