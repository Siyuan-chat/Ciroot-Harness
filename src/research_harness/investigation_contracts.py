"""Public, resource-backed D19 investigation contract helpers."""
from __future__ import annotations
import json
from importlib import resources
from typing import Any
from urllib.parse import urlsplit
from jsonschema import Draft202012Validator
from .errors import ValidationError
from .provider_profiles import validate_profile

def _load(name: str) -> dict[str, Any]:
    return json.loads(resources.files("research_harness").joinpath("schemas", name).read_text(encoding="utf-8"))

def _validate(value: dict[str, Any], name: str) -> None:
    if not isinstance(value, dict): raise ValidationError("contract input must be an object")
    errors = sorted(Draft202012Validator(_load(name)).iter_errors(value), key=lambda error: list(error.path))
    if errors: raise ValidationError(f"invalid contract field: {'.'.join(map(str, errors[0].path)) or '$'}")

def validate_spec(spec: dict[str, Any]) -> None:
    _validate(spec, "investigation-spec.schema.json")
    if not isinstance(spec.get("research_question"),str) or not spec["research_question"].strip() or any(x not in {"technical_report","literature_review","patent_monitor_digest"} for x in spec["report_targets"] if isinstance(x,str)) or any(not isinstance(x,(str,dict)) for x in spec["report_targets"]): raise ValidationError("invalid investigation spec")
    for c in spec.get("criteria",[]):
        if "value" in c and c["value"] is not None and not isinstance(c.get("unit"),str): raise ValidationError("quantitative criterion needs unit")
def validate_runtime(runtime: dict[str, Any]) -> None:
    _validate(runtime, "investigation-runtime.schema.json")
    b=runtime["budget"]; allowed={"max_tasks","max_model_calls","max_source_calls","max_pages_per_query","max_cycles","max_total_tasks","max_downloads","max_download_calls","max_download_bytes","max_source_bytes","max_source_response_bytes"}
    if set(b)-allowed or any(type(v) is not int or v < (0 if key=="max_source_calls" else 1) for key,v in b.items()): raise ValidationError("invalid runtime budget")
    patent_sources=runtime.get("patent_sources")
    if patent_sources is not None:
        _validate(patent_sources, "patent-sources.schema.json")
        if any(profile.get("enabled") is True for profile in patent_sources.values()):
            if any(type(b.get(key)) is not int or b[key] < 1 for key in ("max_source_bytes","max_source_response_bytes")):
                raise ValidationError("enabled patent sources require explicit positive source byte and response budgets")
            if any("document_download" in profile.get("capabilities",[]) and (type(b.get(key)) is not int or b[key] < 1) for profile in patent_sources.values() for key in ("max_download_calls","max_download_bytes")):
                raise ValidationError("document download requires explicit call and byte budgets")
    if runtime.get("mode")=="api":
        config=runtime.get("model_api")
        if not isinstance(config,dict) or "max_model_calls" not in b or runtime.get("allow_network") is not True:
            raise ValidationError("model API runtime requires configuration, call budget, and network opt-in")
        validate_profile(config)
    engine=runtime.get("research_engine")
    if engine is not None:
        if runtime.get("mode")!="api" or not isinstance(engine,dict) or engine.get("name") not in {"paperqa", "storm"}:
            raise ValidationError("research engine requires API mode and a supported engine name")
        if not isinstance(engine.get("python_executable"),str):
            raise ValidationError("research engine requires an isolated Python runtime")
        if engine.get("name")=="paperqa" and not isinstance(engine.get("embedding_model"),str):
            raise ValidationError("PaperQA requires an explicit embedding model")
    p=runtime.get("data_policy",{})
    if p and (not isinstance(p,dict) or "allowed_models" in p and (not isinstance(p["allowed_models"],list) or not all(isinstance(x,str) for x in p["allowed_models"])) or "allow_query_egress" in p and type(p["allow_query_egress"]) is not bool): raise ValidationError("invalid data policy")
    if runtime.get("data_mode")=="live":
        sources=runtime.get("sources",{})
        if runtime.get("allow_network") is not True or not isinstance(sources,dict) or not sources: raise ValidationError("live runtime requires explicit network opt-in and source configuration")
        source=sources.get("openalex")
        if source is not None and bool(source.get("anonymous")) == bool(source.get("api_key_env")): raise ValidationError("OpenAlex configuration requires exactly one authentication mode")
        if "epo" in sources:
            epo=sources["epo"]
            if not isinstance(epo,dict) or b.get("max_source_calls",0)>20 or b.get("max_source_bytes",0)>20*1024*1024 or b.get("max_source_response_bytes",0)>5*1024*1024 or b.get("max_pages_per_query",0)>2 or epo.get("page_size",5)>5 or epo.get("max_candidates",20)>20 or b.get("max_tasks",0)>10:
                raise ValidationError("EPO runtime exceeds the approved P4 limits")
            if not all(name in b for name in ("max_source_calls","max_source_bytes","max_source_response_bytes","max_pages_per_query","max_tasks")):
                raise ValidationError("EPO runtime requires explicit P4 limits")

def get_task_schema(role: str) -> dict[str, Any]:
    schema = _load("investigation-task.schema.json")
    try:
        result = {"$schema": schema["$schema"], "$defs": schema["$defs"], **schema["$defs"]["roles"][role]}
        return result
    except KeyError as exc: raise ValidationError("unknown investigation task role") from exc
