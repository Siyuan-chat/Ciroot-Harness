from langgraph.graph import StateGraph, START, END

def run(fixture, source_adapter=None, model_adapter=None, on_progress=None):
    state={"fixture":fixture,"spec":fixture.get("spec",{}),"stages":[],"issues":[]}
    def step(name):
        def fn(s):
            s["stages"].append(name)
            if on_progress: on_progress({"stage":name})
            if name=="search": s["candidates"]=(source_adapter or (lambda x:x))(s["fixture"]["candidates"])
            if name=="analyze":
                model=model_adapter or (lambda spec,candidate,candidate_evidence,reference_evidence:{"id":candidate["id"],"quote":candidate["quote"],"locator":candidate["locator"],"disposition":"watch" if candidate.get("missing") else "include"})
                s["findings"]=[model(s.get("spec",{}),x,x.get("evidence",[]),s.get("reference_evidence",[])) for x in s["candidates"]]
            if name=="verify": s["issues"]=[{"id":"issue-"+x["id"],"status":"open","note":"missing evidence"} for x in s["candidates"] if x.get("missing")]
            return s
        return fn
    g=StateGraph(dict); names=("plan","search","retrieve","analyze","verify","review","report")
    for n in names:g.add_node(n,step(n))
    g.add_edge(START,names[0])
    for a,b in zip(names,names[1:]):g.add_edge(a,b)
    g.add_edge(names[-1],END)
    return g.compile().invoke(state)
