"""Bounded provider adapters. Only these adapters may perform HTTP."""
from __future__ import annotations
import os
from xml.etree import ElementTree
import requests
from .errors import PreflightError

class SourceError(Exception):
    def __init__(self, kind: str, message: str): self.kind=kind; super().__init__(message)

def _request(method, url, *, headers=None, params=None, data=None, auth=None, timeout=30):
    try: response=requests.request(method,url,headers=headers,params=params,data=data,auth=auth,timeout=timeout)
    except requests.Timeout: raise SourceError("temporary","request timed out")
    except requests.RequestException as exc: raise SourceError("temporary",type(exc).__name__)
    kinds={401:"authentication",403:"authorization",404:"not_found",429:"rate_limit"}
    if response.status_code in kinds: raise SourceError(kinds[response.status_code],f"HTTP {response.status_code}")
    if response.status_code>=500: raise SourceError("temporary",f"HTTP {response.status_code}")
    if not response.ok: raise SourceError("invalid_response",f"HTTP {response.status_code}")
    return response

def _json(response):
    try: value=response.json()
    except ValueError as exc: raise SourceError("invalid_response","invalid JSON response") from exc
    if not isinstance(value,dict): raise SourceError("invalid_response","JSON object expected")
    return value

def openalex_search(query: str, api_key_env: str, limit: int, timeout: int, cursor: str="*") -> dict:
    key=os.getenv(api_key_env)
    if not key: raise PreflightError("OpenAlex credential is required")
    data=_json(_request("GET","https://api.openalex.org/works",params={"search":query,"per-page":limit,"cursor":cursor,"api_key":key},timeout=timeout))
    if not isinstance(data.get("results"),list): raise SourceError("invalid_response","OpenAlex results missing")
    meta=data.get("meta")
    if not isinstance(meta,dict) or any(not isinstance(x,dict) for x in data["results"]): raise SourceError("invalid_response","invalid OpenAlex envelope")
    continuation=meta.get("next_cursor")
    if continuation is None and meta.get("count",0)>len(data["results"]): raise SourceError("invalid_response","cursor continuation missing")
    return {"candidates":[{"source_id":x.get("id"),"doi":x.get("doi"),"title":x.get("title"),"abstract_available":bool(x.get("abstract_inverted_index"))} for x in data["results"]],"continuation":continuation,"completeness":"partial" if continuation else "complete"}

def epo_search(cql: str, key_env: str, secret_env: str, limit: int, timeout: int, start: int=1) -> dict:
    key,secret=os.getenv(key_env),os.getenv(secret_env)
    if not key or not secret: raise PreflightError("EPO credential is required")
    token=_json(_request("POST","https://ops.epo.org/3.2/auth/accesstoken",data={"grant_type":"client_credentials"},auth=(key,secret),timeout=timeout)).get("access_token")
    if not isinstance(token,str) or not token: raise SourceError("invalid_response","EPO access token missing")
    response=_request("GET","https://ops.epo.org/3.2/rest-services/published-data/search",headers={"Accept":"application/xml","Authorization":"Bearer "+token},params={"q":cql,"Range":f"{start}-{start+limit-1}"},timeout=timeout)
    try: root=ElementTree.fromstring(response.text)
    except ElementTree.ParseError as exc: raise SourceError("invalid_response","invalid EPO XML") from exc
    candidates=[]; total=0
    for item in root.iter():
        if item.tag.rsplit("}",1)[-1]=="exchange-document":
            country=item.attrib.get("country"); number=item.attrib.get("doc-number"); kind=item.attrib.get("kind")
            if country and number: candidates.append({"source_id":country+number+(kind or ""),"country":country,"publication_number":number,"kind":kind})
        if item.tag.rsplit("}",1)[-1]=="search-result": total=int(item.attrib.get("total-result-count","0"))
    next_start=start+len(candidates); continuation=next_start if next_start<=total else None
    return {"candidates":candidates,"raw_xml":response.text,"completeness":"partial" if continuation else "complete","continuation":continuation}
