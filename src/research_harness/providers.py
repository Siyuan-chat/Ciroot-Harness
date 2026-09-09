"""Bounded provider adapters. Only these adapters may perform HTTP."""
from __future__ import annotations
import os, time
import requests
from .errors import PreflightError

class SourceError(Exception):
    def __init__(self, kind: str, message: str): self.kind=kind; super().__init__(message)

def _request(method, url, *, headers=None, params=None, timeout=30):
    try: response=requests.request(method,url,headers=headers,params=params,timeout=timeout)
    except requests.Timeout as exc: raise SourceError("temporary","request timed out") from exc
    except requests.RequestException as exc: raise SourceError("temporary",str(exc)) from exc
    kinds={401:"authentication",403:"authorization",404:"not_found",429:"rate_limit"}
    if response.status_code in kinds: raise SourceError(kinds[response.status_code],f"HTTP {response.status_code}")
    if response.status_code>=500: raise SourceError("temporary",f"HTTP {response.status_code}")
    if not response.ok: raise SourceError("invalid_response",f"HTTP {response.status_code}")
    return response

def openalex_search(query: str, api_key_env: str, limit: int, timeout: int) -> dict:
    key=os.getenv(api_key_env)
    if not key: raise PreflightError("OpenAlex credential is required")
    data=_request("GET","https://api.openalex.org/works",params={"search":query,"per-page":limit,"api_key":key},timeout=timeout).json()
    if not isinstance(data.get("results"),list): raise SourceError("invalid_response","OpenAlex results missing")
    return {"candidates":[{"source_id":x.get("id"),"doi":x.get("doi"),"title":x.get("title"),"abstract_available":bool(x.get("abstract_inverted_index"))} for x in data["results"]],"continuation":data.get("meta",{}).get("next_cursor"),"completeness":"partial" if data.get("meta",{}).get("next_cursor") else "complete"}

def epo_search(cql: str, key_env: str, secret_env: str, limit: int, timeout: int) -> dict:
    key,secret=os.getenv(key_env),os.getenv(secret_env)
    if not key or not secret: raise PreflightError("EPO credential is required")
    response=_request("GET","https://ops.epo.org/3.2/rest-services/published-data/search",headers={"Accept":"application/xml"},params={"q":cql,"Range":f"1-{limit}"},timeout=timeout)
    return {"raw_xml":response.text,"completeness":"partial","continuation":None}
