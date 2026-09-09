from langgraph.graph import StateGraph, START, END

def run(fixture, source_adapter=None, model_adapter=None, on_progress=None):
    state={"fixture":fixture,"stages":[],"issues":[]}
    def step(name):
        def fn(s):
            s["stages"].append(name)
            if on_progress: on_progress({"stage":name})
            if name=="search": s["candidates"]=(source_adapter or (lambda x:x))(s["fixture"]["candidates"])
            if name=="analyze": s["findings"]=[{"id":x["id"],"quote":x["quote"],"locator":x["locator"],"disposition":"watch" if x.get("missing") else "include"} for x in s["candidates"]]
            if name=="verify": s["issues"]=[{"id":"issue-"+x["id"],"status":"open","note":"missing evidence"} for x in s["candidates"] if x.get("missing")]
            return s
        return fn
    g=StateGraph(dict); names=("plan","search","retrieve","analyze","verify","review","report")
    for n in names:g.add_node(n,step(n))
    g.add_edge(START,names[0])
    for a,b in zip(names,names[1:]):g.add_edge(a,b)
    g.add_edge(names[-1],END)
    return g.compile().invoke(state)
