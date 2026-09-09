"""Local lexical retrieval; hybrid mode is refused until vector dependencies are present."""
from __future__ import annotations
import re

def search(documents: list[dict], query: str, top_k: int = 10) -> list[dict]:
    terms=[t.lower() for t in re.findall(r"[\w\u4e00-\u9fff\u3040-\u30ff]+",query) if len(t)>1]
    scored=[]
    for doc in documents:
        text=(doc.get("content") or "").lower(); score=sum(text.count(term) for term in terms)
        if score: scored.append({"document_id":doc["id"],"score":score,"mode":"lexical"})
    return sorted(scored,key=lambda x:(-x["score"],x["document_id"]))[:top_k]
