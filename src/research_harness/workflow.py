from langgraph.graph import StateGraph, START, END

def run(fixture, source_adapter=None, model_adapter=None, on_progress=None, retrieve=None):
    state={"fixture":fixture,"spec":fixture.get("spec",{}),"reference_evidence":fixture.get("reference_evidence",[]),"stages":[],"issues":[]}
    def step(name):
        def fn(s):
            s["stages"].append(name)
            if on_progress: on_progress({"stage":name})
            if name=="search": s["candidates"]=(source_adapter or (lambda x:x))(s["fixture"]["candidates"])
            if name=="retrieve": s["candidates"]=(retrieve or (lambda x:x))(s["candidates"])
            if name=="analyze":
                def default(spec,candidate,ce,re): return {"disposition":"watch" if candidate.get("missing") else "include","comparison_result":"insufficient_evidence" if candidate.get("missing") else "similar","rationale":"fixture","candidate_citations":[] if candidate.get("missing") else [{"evidence_id":ce[0]["id"],"quote":ce[0]["quote"]}],"reference_citations":[]}
                model=model_adapter or default
                s["findings"]=[dict(model(s.get("spec",{}),x,x.get("evidence",[]),s.get("reference_evidence",[])),id="finding-"+x["id"],candidate_id=x["id"],document_id=x["document_id"]) for x in s["candidates"]]
            if name=="verify":
                s["issues"]=[]
                for f,x in zip(s["findings"],s["candidates"]):
                    allowed={e["id"]:e["quote"] for e in x["evidence"]}; errors=[]
                    for c in f["candidate_citations"]:
                        if allowed.get(c.get("evidence_id"))!=c.get("quote"): errors.append("invalid_candidate_citation")
                    if not f["candidate_citations"]: errors.append("missing_candidate_citation")
                    if errors: f.update(disposition="watch",comparison_result="insufficient_evidence",verification={"status":"invalid","errors":errors});s["issues"].append({"id":"issue-"+x["id"],"document_id":x["document_id"],"status":"open","note":errors[0]})
                    else:f["verification"]={"status":"valid","errors":[]}
            return s
        return fn
    g=StateGraph(dict); names=("plan","search","retrieve","analyze","verify","review","report")
    for n in names:g.add_node(n,step(n))
    g.add_edge(START,names[0])
    for a,b in zip(names,names[1:]):g.add_edge(a,b)
    g.add_edge(names[-1],END)
    return g.compile().invoke(state)
