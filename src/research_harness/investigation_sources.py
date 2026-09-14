"""Injectable offline source, normalization, and policy boundary for D19."""
from __future__ import annotations
import base64, hashlib
from io import BytesIO
from xml.etree import ElementTree
from dataclasses import dataclass
from typing import Any

class SourceError(Exception):
    def __init__(self, code, message): self.code, self.message=code,message

@dataclass
class SyntheticTransport:
    pages: list[dict[str, Any]]
    def search(self, source, query_id, cursor=None):
        for page in self.pages:
            if page.get("source")==source and page.get("query_id",query_id)==query_id and page.get("cursor")==cursor:
                if page.get("error"): raise SourceError("RH_SOURCE_"+str(page["error"]).upper(),"offline source response failed")
                return {"candidates":list(page.get("candidates",[])),"next_cursor":page.get("next_cursor"),"complete":not bool(page.get("next_cursor"))}
        return {"candidates":[],"next_cursor":None,"complete":True}

def policy_allows(item, runtime, *, query=False):
    policy=runtime.get("data_policy",{}); visibility=item.get("visibility","public")
    if visibility=="public": return True
    if query and not policy.get("allow_query_egress",False): return False
    if item.get("company_id")!=policy.get("company_id"): return False
    return runtime.get("model_id",runtime.get("executor_id","host-synthetic")) in policy.get("allowed_models",[])

def normalize(document):
    content_type=document.get("content_type","text/plain"); raw=document.get("text")
    blob=base64.b64decode(document["base64_bytes"]) if document.get("base64_bytes") else None
    if content_type=="application/xml":
        try: root=ElementTree.fromstring(blob if blob is not None else raw.encode("utf-8"))
        except (ElementTree.ParseError, AttributeError, UnicodeError) as exc: raise SourceError("RH_NORMALIZE_XML","invalid XML") from exc
        node=next((x for x in root.iter() if x.tag.rsplit("}",1)[-1] in {"p","paragraph","claim"} and "".join(x.itertext()).strip()),None)
        if node is None: raise SourceError("RH_NORMALIZE_EMPTY","XML has no extractable paragraph or claim")
        text="".join(node.itertext()).strip(); locator=document.get("locator") or {"kind":"xml_"+node.tag.rsplit("}",1)[-1],"value":node.get("id") or "1"}
    elif content_type=="application/pdf":
        if blob is None: raise SourceError("RH_NORMALIZE_PDF","PDF requires base64_bytes")
        try:
            from pypdf import PdfReader
            reader=PdfReader(BytesIO(blob)); text="\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as exc: raise SourceError("RH_NORMALIZE_PDF","PDF extraction failed") from exc
        locator=document.get("locator") or {"kind":"pdf_page","value":"1"}
    elif content_type=="text/plain": text=raw; locator=document.get("locator") or {"kind":"paragraph","value":"1"}
    else: raise SourceError("RH_NORMALIZE_TYPE","unsupported synthetic content type")
    if not isinstance(text,str) or not text.strip(): raise SourceError("RH_NORMALIZE_EMPTY","source body is empty")
    if not locator.get("kind") or not locator.get("value"): raise SourceError("RH_SCENARIO_LOCATOR","source requires physical locator")
    version=str(document.get("version","synthetic-v1")); identity=document["document_id"]+version+str(locator)+text
    return {"evidence_id":"ev-"+hashlib.sha256(identity.encode()).hexdigest()[:12],"document_id":document["document_id"],"version_id":version,"text":text,"quote":text,"locator":locator,"content_type":content_type,"content_sha256":hashlib.sha256((blob if blob is not None else text.encode()).strip() if False else (blob if blob is not None else text.encode())).hexdigest()}

def baseline_snapshot(references, runtime):
    """Freeze only policy-authorized synthetic references before planning."""
    snapshot=[]
    for item in references or []:
        if not policy_allows(item, runtime):
            continue
        snapshot.append(normalize(item))
    return snapshot
