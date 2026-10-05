"""Core-owned adapter between PaperQA and the existing investigation service."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess

import requests

from .investigation import InvestigationError
from .investigation_model_api import _authorized_payload
from .provider_profiles import validate_profile
from .research_engines import resolve_engine_citations, run_engine


def _engine_provider_request(rpc, runtime):
    """Build an API request from PaperQA's messages without imposing task JSON schema."""
    config = runtime["model_api"]
    profile = validate_profile(config)
    key = os.environ.get(config.get("api_key_env", "")) if config.get("api_key_env") else None
    if not profile["local"] and not key:
        raise InvestigationError("RH_MODEL_KEY_MISSING", "configured model API credential is missing")
    request = rpc.get("request")
    messages = request.get("messages") if isinstance(request, dict) else None
    if not isinstance(messages, list) or not messages:
        raise InvestigationError("RH_ENGINE_RPC", "PaperQA model request must contain messages")
    normalized = []
    for item in messages:
        if not isinstance(item, dict) or item.get("role") not in {"system", "user", "assistant"} or not isinstance(item.get("content"), str):
            raise InvestigationError("RH_ENGINE_RPC", "PaperQA model messages have an unsupported shape")
        normalized.append({"role": item["role"], "content": item["content"]})
    endpoint = profile["endpoint"]
    requested_tokens = request.get("max_output_tokens", config["max_output_tokens"])
    if type(requested_tokens) is not int or requested_tokens < 1:
        raise InvestigationError("RH_ENGINE_RPC", "PaperQA max_output_tokens must be a positive integer")
    token_limit = min(requested_tokens, config["max_output_tokens"])
    if config["provider"] == "anthropic":
        system = "\n\n".join(item["content"] for item in normalized if item["role"] == "system")
        body = {"model": profile["model"], "max_tokens": token_limit,
                "messages": [item for item in normalized if item["role"] != "system"]}
        if system:
            body["system"] = system
        headers = ({"x-api-key": key} if key else {}) | {"anthropic-version": "2023-06-01", "content-type": "application/json"}
    else:
        token_key = "max_completion_tokens" if config["provider"] == "openai" else "max_tokens"
        body = {"model": profile["model"], "messages": normalized, token_key: token_limit}
        headers = ({"authorization": "Bearer " + key} if key else {}) | {"content-type": "application/json"}
    return endpoint, headers, body


def _decode_engine_text(provider, response):
    """Accept complete text responses; PaperQA owns any JSON-in-text interpretation."""
    try:
        data = response.json()
        if provider == "anthropic":
            if data.get("stop_reason") not in {"end_turn", "stop_sequence"}:
                raise ValueError("Anthropic response did not finish normally")
            blocks = [part["text"] for part in data["content"] if part.get("type") == "text" and isinstance(part.get("text"), str)]
            text = "".join(blocks)
            usage = data.get("usage") or {}
            usage_result = {"input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens")}
        else:
            choice = data["choices"][0]
            if choice.get("finish_reason") != "stop":
                raise ValueError("model response was incomplete")
            text = choice["message"]["content"]
            usage = data.get("usage") or {}
            usage_result = {"input_tokens": usage.get("prompt_tokens"), "output_tokens": usage.get("completion_tokens")}
        if not isinstance(text, str) or not text:
            raise ValueError("model response contained no text")
        return text, usage_result
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise InvestigationError("RH_ENGINE_RESPONSE_INVALID", "provider returned no complete PaperQA text response") from error


def _findings_from_resolved(resolved):
    citations = {item["citation_id"]: item for item in resolved["draft"]["citations"]}
    findings = []
    excluded = []
    for claim in resolved["draft"]["claims"]:
        text = claim.get("text") if isinstance(claim, dict) else None
        refs = claim.get("citation_ids", []) if isinstance(claim, dict) else []
        bound = [citations[ref] for ref in refs if ref in citations]
        if not isinstance(text, str) or not text.strip() or not bound:
            excluded.append({"text": text, "citation_ids": refs, "reason": "no validated citation bound to claim"})
            continue
        evidence_ids = sorted({item["evidence_id"] for item in bound})
        finding_id = "paperqa-" + hashlib.sha256((text + "\0" + "\0".join(evidence_ids)).encode("utf-8")).hexdigest()[:16]
        findings.append({"finding_id": finding_id, "finding": text, "evidence_ids": evidence_ids,
            "value": None, "unit": None, "conditions": None})
    return findings, excluded


def _paperqa_runtime_ready(executable):
    code = "import os,socket; deny=lambda *a,**k: (_ for _ in ()).throw(PermissionError('offline preflight')); socket.create_connection=deny; socket.getaddrinfo=deny; socket.socket.connect=deny; os.environ['LITELLM_LOCAL_MODEL_COST_MAP']='true'; os.environ['HF_HUB_OFFLINE']='1'; import importlib.metadata; import research_harness.engines.paperqa_worker; import paperqa; assert importlib.metadata.version('paper-qa')=='2026.8.12'"
    allowed = {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH"}
    env = {key:value for key,value in os.environ.items() if key.upper() in allowed} | {"PYTHONNOUSERSITE":"1", "PYTHONUTF8":"1"}
    try:
        result = subprocess.run([str(executable), "-c", code], capture_output=True, text=True, timeout=25, check=False, env=env)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _storm_runtime_ready(executable):
    code = "import os,socket,tempfile,importlib.metadata; home=tempfile.mkdtemp(prefix='rh-storm-preflight-'); os.environ['HOME']=home; os.environ['USERPROFILE']=home; os.environ['LITELLM_LOCAL_MODEL_COST_MAP']='true'; os.environ['DSP_CACHEBOOL']='false'; os.environ['DSP_CACHEDIR']=os.path.join(home,'dsp-cache'); deny=lambda *a,**k: (_ for _ in ()).throw(PermissionError('offline preflight')); socket.create_connection=deny; socket.getaddrinfo=deny; socket.socket.connect=deny; import knowledge_storm.storm_wiki.engine; assert importlib.metadata.version('knowledge-storm')=='1.1.1'"
    allowed = {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH"}
    env = {key:value for key,value in os.environ.items() if key.upper() in allowed} | {"PYTHONNOUSERSITE":"1", "PYTHONUTF8":"1"}
    try:
        result = subprocess.run([str(executable), "-c", code], capture_output=True, text=True, timeout=60, check=False, env=env)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _storm_claims_for_synthesis(resolved, task):
    """Project only exact resolver-approved citations to the existing synthesis schema."""
    citations = {row["citation_id"]: row for row in resolved["draft"]["citations"]}
    evidence = {row.get("evidence_id"): row for row in task["payload"].get("evidence", []) if isinstance(row, dict)}
    findings = task["payload"].get("findings", [])
    by_evidence = {}
    for index, finding in enumerate(findings):
        for evidence_id in finding.get("evidence_ids", []) if isinstance(finding, dict) else []:
            by_evidence.setdefault(evidence_id, []).append(index)
    output, excluded = [], []
    for claim in resolved["draft"]["claims"]:
        text = claim.get("text") if isinstance(claim, dict) else None
        ids = claim.get("citation_ids", []) if isinstance(claim, dict) else []
        bound = [citations[item] for item in ids if item in citations]
        # Keep separate claim rows so every quote/document tuple is explicit.
        for citation in bound:
            source = evidence.get(citation["evidence_id"])
            finding_refs = by_evidence.get(citation["evidence_id"], [])
            if not isinstance(text, str) or not text.strip() or source is None or not finding_refs:
                excluded.append({"claim": text, "citation_id": citation["citation_id"], "reason": "citation is not linked to an accepted extraction finding"})
                continue
            output.append({"claim_id": claim.get("claim_id", "storm-claim"), "claim": text,
                "finding_refs": finding_refs, "evidence_refs": [citation["evidence_id"]], "quote": citation["quote"],
                "document_id": citation["document_id"], "version_id": citation["version_id"],
                **({"parse_revision_id": citation["parse_revision_id"]} if citation.get("parse_revision_id") else {})})
    return output, excluded


def _storm_frozen_rows(evidence, query, top_k):
    """Return STORM RM rows from only the already-frozen task evidence."""
    if not isinstance(query, str) or not query.strip() or type(top_k) is not int or top_k < 1:
        raise InvestigationError("RH_ENGINE_RPC", "STORM retrieval query/top_k is invalid")
    import re
    tokens = set(re.findall(r"[\w-]+", query.casefold()))
    eligible = [item for item in evidence if isinstance(item, dict) and isinstance(item.get("text"), str)
        and (item.get("legacy") is True or bool(item.get("parse_revision_id")))]
    ranked = sorted(eligible, key=lambda item: (-len(tokens & set(re.findall(r"[\w-]+", item["text"].casefold()))), str(item.get("evidence_id", ""))))
    return [{"url":"frozen:"+str(item.get("evidence_id")), "title":str(item.get("title") or item.get("document_id") or item.get("evidence_id")),
        "description":item["text"], "snippets":[item["text"]], "meta":{key:item.get(key) for key in ("evidence_id","document_id","version_id","parse_revision_id","locator","legacy")}}
        for item in ranked[:top_k]]


def run_storm_task(service, run_id, task, *, post=requests.post):
    run = service._run(run_id); runtime = json.loads(run["runtime"]); config = runtime.get("research_engine")
    if not isinstance(config, dict) or config.get("name") != "storm":
        raise InvestigationError("RH_ENGINE_PENDING", "STORM is not explicitly configured")
    executable = Path(config.get("python_executable", "")).resolve()
    if not executable.is_file() or not _storm_runtime_ready(executable):
        raise InvestigationError("RH_ENGINE_PENDING", "configured runtime must import the installed STORM 1.1.1 worker")
    api_profile = runtime.get("model_api")
    if not isinstance(api_profile, dict):
        raise InvestigationError("RH_ENGINE_PENDING", "STORM requires an explicit core model profile")
    validated = validate_profile(api_profile)
    if not validated["local"] and not os.environ.get(api_profile.get("api_key_env", "")):
        raise InvestigationError("RH_MODEL_KEY_MISSING", "configured model API credential is missing")
    payload = task["payload"]; evidence = payload.get("evidence", [])
    if not isinstance(evidence, list): evidence = []
    evidence = [({**item, "legacy": True} if isinstance(item, dict) and item.get("legacy_unversioned") is True and item.get("parse_revision_id") is None and item.get("legacy") is None else item) for item in evidence]
    _authorized_payload(payload, runtime)
    safe_profile = {"enabled": True, "runtime_python": str(executable), "engine": "storm", "version": "1.1.1", "model": api_profile.get("model")}
    limits = {"max_output_tokens": api_profile["max_output_tokens"], "max_rpc_requests": min(32, runtime.get("budget", {}).get("max_model_calls", 8)),
        "max_conv_turn": min(3, int(config.get("max_conv_turn", 2))), "max_search_queries_per_turn": min(3, int(config.get("max_search_queries_per_turn", 2))),
        "search_top_k": min(5, int(config.get("search_top_k", 3))), "retrieve_top_k": min(5, int(config.get("retrieve_top_k", 3)))}
    envelope = {"run_id": run_id, "research_question": json.loads(run["spec"]).get("research_question"),
        "task": {key: task[key] for key in ("task_id", "task_version", "role", "task_type", "payload", "output_schema")},
        "evidence": evidence, "profile": safe_profile, "limits": limits}
    auth = {"result": "passed", "policy": "runtime model data policy", "scope": "synthesis task and frozen evidence",
        "payload_sha256": hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "frozen_evidence_ids": [item.get("evidence_id") for item in evidence if isinstance(item, dict)]}
    lease = service.reserve_engine_lease(run_id, task["task_id"], task["task_version"])

    def handle_rpc(rpc):
        if rpc["op"] == "retrieve_frozen":
            call_id = service.reserve_engine_model_call(lease, rpc["request_id"], "retrieve_frozen", rpc["purpose"])
            request = rpc["request"]
            query = request.get("query")
            top_k = request.get("top_k", limits["search_top_k"])
            rows = _storm_frozen_rows(evidence, query, min(top_k, limits["search_top_k"]) if type(top_k) is int and top_k > 0 else top_k)
            context = service.engine_context(run_id, task, {"request":{"query":query,"context_ids":[x["meta"]["evidence_id"] for x in rows],"top_k":top_k},"op":"retrieve_frozen"}, api_profile, auth)
            service.prepare_model_call(call_id, {"query":query,"top_k":top_k,"evidence_ids":[x["meta"]["evidence_id"] for x in rows]}, context)
            service.mark_model_call_dispatching(call_id); service.record_model_response(call_id, json.dumps(rows, ensure_ascii=False).encode()); service.finish_model_call(call_id,"accepted",{"kind":"retrieval","items":len(rows)})
            return {"outcome":"accepted","result":rows,"core_call_id":call_id,"usage":{"kind":"retrieval","items":len(rows)}}
        if rpc["op"] != "model_call": raise InvestigationError("RH_ENGINE_RPC", "unsupported STORM capability")
        call_id = service.reserve_engine_model_call(lease, rpc["request_id"], "model_call", rpc["purpose"])
        endpoint, headers, body = _engine_provider_request(rpc, runtime)
        service.prepare_model_call(call_id, body, service.engine_context(run_id, task, rpc, api_profile, auth)); service.mark_model_call_dispatching(call_id)
        try:
            response = post(endpoint, headers=headers, json=body, timeout=api_profile["timeout_seconds"], allow_redirects=False)
            service.record_model_response(call_id, bytes(response.content))
            if response.status_code != 200:
                service.finish_model_call(call_id,"failed",None); return {"outcome":"failed","result":None,"core_call_id":call_id,"usage":{}}
            text, usage = _decode_engine_text(api_profile["provider"], response); service.finish_model_call(call_id,"accepted",usage)
            return {"outcome":"accepted","result":{"text":text},"core_call_id":call_id,"usage":usage}
        except requests.RequestException:
            # Once dispatch started, the child ledger marks transport failure unknown.
            service.finish_model_call(call_id,"failed",None); raise

    service.mark_engine_dispatching(lease)
    result = run_engine([str(executable), "-m", "research_harness.engines.storm_worker"], envelope, handle_rpc, config.get("timeout_seconds", 180))
    if result.get("status") != "draft":
        service.finish_engine_lease(lease, "outcome_unknown" if result.get("error", {}).get("code") in {"RH_ENGINE_TIMEOUT","RH_ENGINE_RPC_TIMEOUT","RH_ENGINE_EOF"} else "failed")
        raise InvestigationError(result.get("error", {}).get("code", "RH_ENGINE_FAILED"), "STORM did not return a usable draft")
    resolved = resolve_engine_citations(envelope, result)
    claims, excluded = _storm_claims_for_synthesis(resolved, task)
    receipt = service.record_engine_receipt(run_id, task, lease, result, {"validated":resolved["draft"],"issues":resolved["issues"],"excluded_claims":excluded}, authorization=auth)
    if resolved["draft"]["coverage_gaps"] or resolved["issues"] or excluded:
        service.add_engine_coverage_issue(run_id, task["task_id"], task["task_version"], receipt, resolved["draft"]["coverage_gaps"], resolved["issues"], len(excluded))
    if not claims:
        service.finish_engine_lease(lease,"failed")
        raise InvestigationError("RH_ENGINE_NO_CITATIONS", "STORM produced no synthesis claim linked to an exact frozen citation; receipt="+receipt)
    accepted = service.submit_model_result(run_id, task["task_id"], {"claims":claims}, task["task_version"])
    service.finish_engine_lease(lease,"accepted")
    return accepted


def run_research_engine_task(service, run_id, task, *, post=requests.post):
    run = service._run(run_id)
    runtime = json.loads(run["runtime"])
    config = runtime.get("research_engine")
    if not isinstance(config, dict) or config.get("name") != "paperqa":
        raise InvestigationError("RH_ENGINE_PENDING", "PaperQA is not explicitly configured")
    python = config.get("python_executable")
    executable = Path(python).resolve() if isinstance(python, str) else None
    if executable is None or not executable.is_file():
        raise InvestigationError("RH_ENGINE_PENDING", "configured PaperQA runtime is unavailable")
    if not _paperqa_runtime_ready(executable):
        raise InvestigationError("RH_ENGINE_PENDING", "configured runtime must import the installed research_harness worker and PaperQA 2026.8.12")
    payload = task["payload"]
    evidence = payload.get("evidence", [])
    if not isinstance(evidence, list):
        evidence = []
    evidence = [({**item, "legacy": True} if isinstance(item, dict) and item.get("legacy_unversioned") is True and item.get("parse_revision_id") is None and item.get("legacy") is None else item) for item in evidence]
    api_profile = runtime.get("model_api")
    if not isinstance(api_profile, dict):
        raise InvestigationError("RH_ENGINE_PENDING", "PaperQA requires an explicit core model profile")
    validated_profile = validate_profile(api_profile)
    if not validated_profile["local"] and not os.environ.get(api_profile.get("api_key_env", "")):
        raise InvestigationError("RH_MODEL_KEY_MISSING", "configured model API credential is missing")
    # The child receives only public, non-secret profile fields.
    safe_profile = {"enabled": True, "runtime_python": str(executable), "engine": "paperqa", "version": "2026.8.12",
        "model": api_profile.get("model"), "embedding_model": config.get("embedding_model")}
    if not safe_profile["embedding_model"]:
        raise InvestigationError("RH_ENGINE_PENDING", "PaperQA requires a separately configured embedding model")
    embedding_runtime = config.get("local_embedding")
    if not isinstance(embedding_runtime, dict) or any(not isinstance(embedding_runtime.get(key), str) or not embedding_runtime[key] for key in ("python_executable", "model", "cache_dir")):
        raise InvestigationError("RH_ENGINE_PENDING", "PaperQA currently requires an explicit local embedding runtime, model and cache")
    if not Path(embedding_runtime["python_executable"]).is_absolute() or not Path(embedding_runtime["python_executable"]).is_file() or not Path(embedding_runtime["cache_dir"]).is_absolute() or not Path(embedding_runtime["cache_dir"]).is_dir():
        raise InvestigationError("RH_ENGINE_PENDING", "configured local embedding runtime or cache is unavailable")
    if not service.local_embedding_model_supported(runtime):
        raise InvestigationError("RH_ENGINE_PENDING", "configured local embedding model is not registered in the offline FastEmbed runtime")
    _authorized_payload(payload, runtime)
    authorization = {"result": "passed", "policy": "runtime model data policy", "scope": "task payload and frozen evidence",
        "payload_sha256": hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
        "frozen_evidence_ids": [item.get("evidence_id") for item in evidence if isinstance(item, dict) and isinstance(item.get("evidence_id"), str)]}
    envelope = {"run_id": run_id, "task": {key: task[key] for key in ("task_id", "task_version", "role", "task_type", "payload", "output_schema")},
        "evidence": evidence, "research_question": json.loads(run["spec"]).get("research_question"), "profile": safe_profile,
        "limits": {"max_output_tokens": api_profile["max_output_tokens"], "max_rpc_requests": runtime.get("budget", {}).get("max_model_calls", 8)}}
    lease = service.reserve_engine_lease(run_id, task["task_id"], task["task_version"])

    def handle_rpc(rpc):
        if rpc["op"] == "retrieve_frozen":
            # PaperQA operates on the evidence array already frozen in envelope.
            return {"outcome": "accepted", "result": [], "core_call_id": None, "usage": {}}
        if rpc["op"] not in {"model_call", "embedding"}:
            raise InvestigationError("RH_ENGINE_RPC", "unsupported PaperQA capability")
        call_id = service.reserve_engine_model_call(lease, rpc["request_id"], rpc["op"], rpc["purpose"])
        try:
            if rpc["op"] == "embedding":
                # Explicit local embeddings only. Execution is core-owned and audited; never use chat API.
                service.prepare_model_call(call_id, rpc["request"], service.engine_context(run_id, task, rpc, api_profile, authorization))
                service.mark_model_call_dispatching(call_id)
                vectors = service.run_local_embedding(runtime, rpc["request"].get("texts", []))
                raw = json.dumps(vectors, separators=(",", ":")).encode()
                service.record_model_response(call_id, raw)
                service.finish_model_call(call_id, "accepted", {"kind": "embedding", "items": len(vectors)})
                return {"outcome": "accepted", "result": vectors, "core_call_id": call_id, "usage": {"kind": "embedding"}}
            endpoint, headers, body = _engine_provider_request(rpc, runtime)
            # Persist the complete application-layer provider JSON body before dispatch;
            # authorization headers and secret values are never captured.
            service.prepare_model_call(call_id, body, service.engine_context(run_id, task, rpc, api_profile, authorization))
            service.mark_model_call_dispatching(call_id)
            response = post(endpoint, headers=headers, json=body, timeout=api_profile["timeout_seconds"], allow_redirects=False)
            raw = bytes(response.content)
            service.record_model_response(call_id, raw)
            if response.status_code != 200:
                service.finish_model_call(call_id, "failed", None)
                return {"outcome": "failed", "result": None, "core_call_id": call_id, "usage": {}}
            text, usage = _decode_engine_text(api_profile["provider"], response)
            service.finish_model_call(call_id, "accepted", usage)
            return {"outcome": "accepted", "result": {"text": text}, "core_call_id": call_id, "usage": usage}
        except requests.RequestException:
            service.finish_model_call(call_id, "failed", None)
            raise
        except Exception:
            state=service.db.execute("SELECT status FROM model_api_calls WHERE id=?",(call_id,)).fetchone()
            if state and state["status"] in {"reserved","prepared","dispatching","response_received"}:
                service.finish_model_call(call_id, "failed", None)
            raise

    service.mark_engine_dispatching(lease)
    result = run_engine([str(executable), "-m", "research_harness.engines.paperqa_worker"], envelope,
        handle_rpc, config.get("timeout_seconds", 180))
    if result.get("status") != "draft":
        service.finish_engine_lease(lease, "outcome_unknown" if result.get("error", {}).get("code") in {"RH_ENGINE_TIMEOUT", "RH_ENGINE_RPC_TIMEOUT", "RH_ENGINE_EOF"} else "failed")
        raise InvestigationError(result.get("error", {}).get("code", "RH_ENGINE_FAILED"), "research engine did not return a usable draft")
    resolved = resolve_engine_citations(envelope, result)
    findings, excluded_claims = _findings_from_resolved(resolved)
    artifact_id = service.record_engine_receipt(run_id, task, lease, result,
        {"validated": resolved["draft"], "issues": resolved["issues"], "excluded_claims": excluded_claims},
        authorization=authorization)
    if not findings:
        service.finish_engine_lease(lease, "failed")
        raise InvestigationError("RH_ENGINE_NO_FINDINGS", "PaperQA produced no claim with an exact validated citation; draft receipt=" + artifact_id)
    if resolved["draft"]["coverage_gaps"] or resolved["issues"]:
        service.add_engine_coverage_issue(run_id, task["task_id"], task["task_version"], artifact_id,
            resolved["draft"]["coverage_gaps"], resolved["issues"], len(excluded_claims))
    accepted = service.submit_model_result(run_id, task["task_id"], {"findings": findings}, task["task_version"])
    service.finish_engine_lease(lease, "accepted")
    return accepted
