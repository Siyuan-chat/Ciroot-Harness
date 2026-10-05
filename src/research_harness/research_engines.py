"""Bounded JSONL supervisor and exact frozen-evidence citation validation.

An engine can propose a draft and request core-owned capabilities. It never
owns run state, arbitrary network access, or report persistence.
"""
from __future__ import annotations

import json
import math
import os
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .research_engine_protocol import PROTOCOL, ProtocolError, decode_message, encode_message, identity_of


MAX_LINE_BYTES = 1024 * 1024
MAX_TOTAL_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_STDERR_BYTES = 64 * 1024
DEFAULT_MAX_RPC_REQUESTS = 32


def engine_capability(profile: dict[str, Any]) -> dict[str, Any]:
    """Validate optional engine activation data without reading secrets."""
    if not isinstance(profile, dict):
        return {"status": "pending_activation", "reason": "engine profile is missing"}
    if profile.get("enabled") is not True:
        return {"status": "pending_activation", "reason": "engine is disabled"}
    runtime = profile.get("runtime_python")
    if not isinstance(runtime, str) or not Path(runtime).is_absolute():
        return {"status": "pending_activation", "reason": "runtime_python must be an absolute path"}
    if not Path(runtime).is_file():
        return {"status": "pending_activation", "reason": "configured Python runtime is unavailable"}
    return {"status": "ready", "runtime_python": runtime}


def _failure(code: str, message: str, trace: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "protocol": PROTOCOL,
        "status": "failed",
        "error": {"code": code, "message": message},
        "draft": {"sections": [], "claims": [], "citations": [], "coverage_gaps": []},
        "trace": trace or {},
    }


def _argv(command: Any) -> list[str]:
    if not isinstance(command, (list, tuple)) or not command or any(not isinstance(part, str) or not part for part in command):
        raise ProtocolError("RH_ENGINE_COMMAND", "command must be a non-empty argv list")
    executable = Path(command[0])
    if not executable.is_absolute() or not executable.is_file():
        raise ProtocolError("RH_ENGINE_RUNTIME", "argv[0] must be an existing absolute runtime path")
    return list(command)


def _worker_environment() -> dict[str, str]:
    """Pass only runtime necessities; provider credentials stay in the core."""
    allowed = {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH"}
    environment = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    environment.update({"PYTHONNOUSERSITE": "1", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    return environment


def _validate_envelope(envelope: Any) -> dict[str, Any]:
    if not isinstance(envelope, dict):
        raise ProtocolError("RH_ENGINE_ENVELOPE", "envelope must be an object")
    identity = identity_of(envelope)
    task = envelope["task"]
    if not all(isinstance(task.get(key), str) and task[key] for key in ("role", "task_type")):
        raise ProtocolError("RH_ENGINE_ENVELOPE", "task role and task_type are required")
    if not isinstance(task.get("payload"), dict) or not isinstance(task.get("output_schema"), dict):
        raise ProtocolError("RH_ENGINE_ENVELOPE", "task payload and output_schema must be objects")
    if not isinstance(envelope.get("evidence"), list) or not isinstance(envelope.get("profile"), dict):
        raise ProtocolError("RH_ENGINE_ENVELOPE", "evidence array and profile object are required")
    def reject_secrets(value):
        if isinstance(value, dict):
            for key, child in value.items():
                normalized = "".join(char for char in str(key).casefold() if char.isalnum())
                credential_fields = {"apikey", "apikeyenv", "accesstoken", "refreshtoken", "token", "password", "passwd",
                                     "secret", "clientsecret", "credential", "credentials", "authorization", "authheader", "xapikey"}
                if normalized in credential_fields or normalized.endswith(("apikey", "token", "password", "secret", "credential")):
                    raise ProtocolError("RH_ENGINE_PROFILE_SECRET", "profile must not contain credentials")
                reject_secrets(child)
        elif isinstance(value, list):
            for child in value:
                reject_secrets(child)
    reject_secrets(envelope["profile"])
    if not isinstance(envelope.get("limits"), dict):
        raise ProtocolError("RH_ENGINE_ENVELOPE", "limits object is required")
    return identity


def _stream_lines(pipe, output: queue.Queue, limit: int) -> None:
    try:
        while True:
            line = pipe.readline(limit + 1)
            if not line:
                output.put(("eof", None))
                return
            if len(line) > limit:
                output.put(("error", "RH_ENGINE_LINE_LIMIT"))
                return
            if not line.endswith(b"\n"):
                output.put(("error", "RH_ENGINE_TRUNCATED_LINE"))
                return
            output.put(("line", line))
    except Exception:
        output.put(("error", "RH_ENGINE_STDOUT"))


def _drain_stderr(pipe, sink: bytearray) -> None:
    try:
        while True:
            chunk = pipe.read(4096)
            if not chunk:
                return
            if len(sink) < MAX_STDERR_BYTES:
                sink.extend(chunk[: MAX_STDERR_BYTES - len(sink)])
    except Exception:
        return


def run_engine(
    command: list[str] | tuple[str, ...],
    envelope: dict[str, Any],
    handle_rpc: Callable[[dict[str, Any]], dict[str, Any]],
    timeout_seconds: float,
) -> dict[str, Any]:
    """Run one child to exactly one terminal result; RPCs are synchronous.

    ``handle_rpc`` is the only capability bridge. The caller must bind it to
    the existing core gateway and enforce core budgets/policy there.
    """
    started = time.monotonic()
    proc = None
    stderr = bytearray()
    trace: dict[str, Any] = {"rpc_count": 0, "stderr_bytes_captured": 0}
    try:
        identity = _validate_envelope(envelope)
        argv = _argv(command)
        capability = engine_capability(envelope["profile"])
        if capability["status"] != "ready":
            raise ProtocolError("RH_ENGINE_PENDING_ACTIVATION", capability["reason"])
        if Path(argv[0]).resolve() != Path(capability["runtime_python"]).resolve():
            raise ProtocolError("RH_ENGINE_RUNTIME", "command runtime does not match configured absolute Python runtime")
        if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
                or not math.isfinite(timeout_seconds) or timeout_seconds <= 0):
            raise ProtocolError("RH_ENGINE_TIMEOUT", "timeout_seconds must be positive")
        limits = envelope.get("limits")
        if not isinstance(limits, dict):
            raise ProtocolError("RH_ENGINE_ENVELOPE", "limits object is required")
        max_rpc = limits.get("max_rpc_requests", DEFAULT_MAX_RPC_REQUESTS)
        max_output = limits.get("max_output_bytes", MAX_TOTAL_OUTPUT_BYTES)
        if any(isinstance(x, bool) or not isinstance(x, int) or x < 0 for x in (max_rpc, max_output)) or max_output == 0:
            raise ProtocolError("RH_ENGINE_ENVELOPE", "RPC/output limits must be non-negative integers")
        max_rpc = min(max_rpc, DEFAULT_MAX_RPC_REQUESTS)
        max_output = min(max_output, MAX_TOTAL_OUTPUT_BYTES)
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_worker_environment(),
            shell=False,
            bufsize=0,
        )
        assert proc.stdin is not None and proc.stdout is not None and proc.stderr is not None
        incoming: queue.Queue = queue.Queue(maxsize=8)
        threading.Thread(target=_stream_lines, args=(proc.stdout, incoming, MAX_LINE_BYTES), daemon=True).start()
        threading.Thread(target=_drain_stderr, args=(proc.stderr, stderr), daemon=True).start()
        proc.stdin.write(encode_message({"protocol": PROTOCOL, "op": "run", "identity": identity, "envelope": envelope}))
        proc.stdin.flush()
        total_output = 0
        request_ids: set[str] = set()
        final: dict[str, Any] | None = None
        while True:
            remaining = timeout_seconds - (time.monotonic() - started)
            if remaining <= 0:
                raise ProtocolError("RH_ENGINE_TIMEOUT", "engine exceeded its deadline")
            try:
                kind, payload = incoming.get(timeout=remaining)
            except queue.Empty as exc:
                raise ProtocolError("RH_ENGINE_TIMEOUT", "engine exceeded its deadline") from exc
            if kind == "eof":
                if final is None:
                    raise ProtocolError("RH_ENGINE_EOF", "engine exited before a terminal result")
                break
            if kind == "error":
                raise ProtocolError(payload, "engine stdout exceeded or violated JSONL framing")
            total_output += len(payload)
            if total_output > max_output:
                raise ProtocolError("RH_ENGINE_OUTPUT_LIMIT", "engine exceeded total output limit")
            message = decode_message(payload[:-1])
            if final is not None:
                raise ProtocolError("RH_ENGINE_LATE_MESSAGE", "engine emitted a message after its terminal result")
            if message.get("protocol") != PROTOCOL:
                raise ProtocolError("RH_ENGINE_PROTOCOL", "engine protocol version mismatch")
            candidate_identity = message.get("identity")
            if (not isinstance(candidate_identity, dict) or candidate_identity != identity
                    or isinstance(candidate_identity.get("task_version"), bool)
                    or not isinstance(candidate_identity.get("task_version"), int)):
                raise ProtocolError("RH_ENGINE_IDENTITY", "message identity differs from parent task")
            op = message.get("op")
            if op == "rpc":
                if trace["rpc_count"] >= max_rpc:
                    raise ProtocolError("RH_ENGINE_RPC_LIMIT", "engine exceeded RPC request limit")
                request_id = message.get("request_id")
                purpose = message.get("purpose")
                rpc_op = message.get("rpc_op")
                request = message.get("request")
                if not isinstance(request_id, str) or not request_id or request_id in request_ids:
                    raise ProtocolError("RH_ENGINE_REQUEST_ID", "RPC request_id is missing or repeated")
                if rpc_op not in {"model_call", "embedding", "retrieve_frozen"}:
                    raise ProtocolError("RH_ENGINE_RPC_UNKNOWN", "engine requested an unsupported RPC operation")
                if not isinstance(purpose, str) or not purpose.strip() or not isinstance(request, dict):
                    raise ProtocolError("RH_ENGINE_RPC_INVALID", "RPC purpose and request object are required")
                request_ids.add(request_id)
                rpc_message = {"op": rpc_op, "request_id": request_id, "purpose": purpose, "request": request, "identity": identity}
                rpc_result: queue.Queue = queue.Queue(maxsize=1)
                def invoke_core():
                    try:
                        rpc_result.put(("ok", handle_rpc(rpc_message)))
                    except Exception:
                        # Do not expose callback exception text which may contain private data.
                        rpc_result.put(("error", {"outcome": "failed", "result": None, "core_call_id": None, "usage": {}, "error_code": "RH_ENGINE_RPC_FAILED"}))
                threading.Thread(target=invoke_core, daemon=True).start()
                remaining = timeout_seconds - (time.monotonic() - started)
                if remaining <= 0:
                    raise ProtocolError("RH_ENGINE_TIMEOUT", "deadline expired while handling core RPC")
                try:
                    _, reply = rpc_result.get(timeout=remaining)
                except queue.Empty as exc:
                    raise ProtocolError("RH_ENGINE_RPC_TIMEOUT", "core RPC did not return before the engine deadline") from exc
                if not isinstance(reply, dict):
                    raise ProtocolError("RH_ENGINE_RPC_INVALID", "core RPC handler returned a non-object")
                if not isinstance(reply.get("outcome"), str) or not reply["outcome"] or not isinstance(reply.get("usage", {}), dict):
                    raise ProtocolError("RH_ENGINE_RPC_INVALID", "core RPC reply has invalid outcome or usage")
                if reply.get("core_call_id") is not None and not isinstance(reply.get("core_call_id"), str):
                    raise ProtocolError("RH_ENGINE_RPC_INVALID", "core_call_id must be a string or null")
                response = {"protocol": PROTOCOL, "op": "rpc_result", "request_id": request_id,
                            "outcome": reply.get("outcome"), "result": reply.get("result"),
                            "core_call_id": reply.get("core_call_id"), "usage": reply.get("usage", {}),
                            "identity": identity}
                proc.stdin.write(encode_message(response))
                proc.stdin.flush()
                trace["rpc_count"] += 1
            elif op == "result":
                engine = message.get("engine")
                draft = message.get("draft")
                engine_trace = message.get("trace", {})
                if not isinstance(engine, dict) or not isinstance(engine.get("name"), str) or not isinstance(engine.get("version"), str):
                    raise ProtocolError("RH_ENGINE_RESULT", "engine name and version are required")
                profile = envelope["profile"]
                if ((profile.get("engine") is not None and profile["engine"] != engine.get("name"))
                        or (profile.get("version") is not None and profile["version"] != engine.get("version"))):
                    raise ProtocolError("RH_ENGINE_IDENTITY", "engine name/version differs from the activated profile")
                if not isinstance(draft, dict) or any(not isinstance(draft.get(key), list) for key in ("sections", "claims", "citations", "coverage_gaps")):
                    raise ProtocolError("RH_ENGINE_RESULT", "draft must include sections, claims, citations, and coverage_gaps arrays")
                if not isinstance(engine_trace, dict):
                    raise ProtocolError("RH_ENGINE_RESULT", "trace must be an object")
                final = {"protocol": PROTOCOL, "status": "draft", "engine": engine, "draft": draft,
                         "trace": {**engine_trace, "rpc_count": trace["rpc_count"]}}
                # Close stdin: one result is terminal, worker must exit without another message.
                proc.stdin.close()
            else:
                raise ProtocolError("RH_ENGINE_OP", "unknown engine message operation")
        remaining = timeout_seconds - (time.monotonic() - started)
        if remaining <= 0 or proc.wait(timeout=remaining) != 0:
            raise ProtocolError("RH_ENGINE_EXIT", "engine did not exit successfully after its result")
        trace.update({"elapsed_seconds": round(time.monotonic() - started, 6), "stderr_bytes_captured": len(stderr)})
        return {**final, "trace": {**final["trace"], **trace}}
    except (ProtocolError, OSError, subprocess.SubprocessError) as exc:
        code = exc.code if isinstance(exc, ProtocolError) else "RH_ENGINE_START_OR_IO"
        trace.update({"elapsed_seconds": round(time.monotonic() - started, 6), "stderr_bytes_captured": len(stderr)})
        return _failure(code, str(exc), trace)
    finally:
        if proc is not None:
            if proc.poll() is None:
                proc.kill()
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
            for pipe in (proc.stdin, proc.stdout, proc.stderr):
                if pipe is not None:
                    try:
                        pipe.close()
                    except OSError:
                        pass


def resolve_engine_citations(envelope: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Keep only citations exactly bound to one frozen evidence passage."""
    issues: list[dict[str, str]] = []
    identity_of(envelope)
    draft = result.get("draft") if isinstance(result, dict) else None
    if not isinstance(draft, dict):
        return {"draft": {"sections": [], "claims": [], "citations": [], "coverage_gaps": []},
                "issues": [{"code": "RH_ENGINE_DRAFT_INVALID", "path": "draft", "message": "draft object is missing"}]}
    evidence = envelope.get("evidence", [])
    if not isinstance(evidence, list):
        evidence = []
        issues.append({"code": "RH_ENGINE_EVIDENCE_INVALID", "path": "evidence", "message": "frozen evidence must be an array"})
    by_id: dict[str, dict[str, Any]] = {}
    duplicate_evidence_ids: set[str] = set()
    for item in evidence:
        if isinstance(item, dict) and isinstance(item.get("evidence_id"), str) and item["evidence_id"]:
            ev_id = item["evidence_id"]
            if ev_id in by_id:
                duplicate_evidence_ids.add(ev_id)
            by_id[ev_id] = item
    valid: list[dict[str, Any]] = []
    citations = draft.get("citations", [])
    if not isinstance(citations, list):
        citations = []
        issues.append({"code": "RH_ENGINE_CITATIONS_INVALID", "path": "draft.citations", "message": "citations must be an array"})
    id_counts: dict[str, int] = {}
    for citation in citations:
        if isinstance(citation, dict) and isinstance(citation.get("citation_id"), str) and citation["citation_id"]:
            id_counts[citation["citation_id"]] = id_counts.get(citation["citation_id"], 0) + 1
    for index, citation in enumerate(citations):
        path = f"draft.citations[{index}]"
        if not isinstance(citation, dict):
            issues.append({"code": "RH_ENGINE_CITATION_INVALID", "path": path, "message": "citation must be an object"})
            continue
        citation_id = citation.get("citation_id")
        if not isinstance(citation_id, str) or not citation_id:
            issues.append({"code": "RH_ENGINE_CITATION_ID", "path": path, "message": "citation_id must be a non-empty string"})
            continue
        if id_counts.get(citation_id, 0) > 1:
            issues.append({"code": "RH_ENGINE_CITATION_ID", "path": path, "message": "citation_id is repeated; every occurrence is ambiguous"})
            continue
        ev_id = citation.get("evidence_id")
        if not isinstance(ev_id, str) or not ev_id:
            issues.append({"code": "RH_ENGINE_EVIDENCE_REF", "path": path, "message": "evidence_id must be a non-empty string"})
            continue
        ev = by_id.get(ev_id)
        if ev is None:
            issues.append({"code": "RH_ENGINE_EVIDENCE_REF", "path": path, "message": "citation does not identify frozen evidence"})
            continue
        if ev_id in duplicate_evidence_ids:
            issues.append({"code": "RH_ENGINE_EVIDENCE_AMBIGUOUS", "path": path, "message": "evidence_id is not unique in the frozen envelope"})
            continue
        if any(citation.get(field) != ev.get(source) for field, source in (("document_id", "document_id"), ("version_id", "version_id"), ("locator", "locator"))):
            issues.append({"code": "RH_ENGINE_EVIDENCE_IDENTITY", "path": path, "message": "document, version, or locator differs from frozen evidence"})
            continue
        parse_revision = ev.get("parse_revision_id")
        if parse_revision is None:
            if ev.get("legacy") is not True:
                issues.append({"code": "RH_ENGINE_PARSE_REVISION", "path": path, "message": "evidence without a parse revision must be explicitly marked legacy"})
                continue
            if citation.get("parse_revision_id") not in (None, "legacy"):
                issues.append({"code": "RH_ENGINE_PARSE_REVISION", "path": path, "message": "legacy evidence has no parse revision to bind"})
                continue
        elif citation.get("parse_revision_id") != parse_revision:
            issues.append({"code": "RH_ENGINE_PARSE_REVISION", "path": path, "message": "parse revision differs from frozen evidence"})
            continue
        quote = citation.get("quote")
        text = ev.get("text")
        if not isinstance(quote, str) or not quote or not isinstance(text, str) or _overlapping_count(text, quote, 2) != 1:
            issues.append({"code": "RH_ENGINE_QUOTE", "path": path, "message": "quote must be a non-empty, unique contiguous substring of frozen evidence"})
            continue
        valid.append({**citation, "legacy": parse_revision is None})
    citation_ids = {item["citation_id"] for item in valid}
    claims = draft.get("claims", [])
    if not isinstance(claims, list):
        claims = []
        issues.append({"code": "RH_ENGINE_CLAIMS_INVALID", "path": "draft.claims", "message": "claims must be an array"})
    normalized_claims = []
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            issues.append({"code": "RH_ENGINE_CLAIM_INVALID", "path": f"draft.claims[{index}]", "message": "claim must be an object"})
            continue
        refs = claim.get("citation_ids", [])
        if not isinstance(refs, list):
            refs = []
        kept = [ref for ref in refs if isinstance(ref, str) and ref in citation_ids]
        for ref in refs:
            if not isinstance(ref, str) or ref not in citation_ids:
                issues.append({"code": "RH_ENGINE_CLAIM_CITATION_REF", "path": f"draft.claims[{index}].citation_ids", "message": "claim references a citation that was not validated"})
        normalized_claims.append({**claim, "citation_ids": kept})
    sections = draft.get("sections", [])
    gaps = draft.get("coverage_gaps", [])
    if not isinstance(sections, list):
        issues.append({"code": "RH_ENGINE_SECTIONS_INVALID", "path": "draft.sections", "message": "sections must be an array"})
        sections = []
    if not isinstance(gaps, list):
        issues.append({"code": "RH_ENGINE_COVERAGE_INVALID", "path": "draft.coverage_gaps", "message": "coverage_gaps must be an array"})
        gaps = []
    return {"draft": {"sections": sections, "claims": normalized_claims, "citations": valid, "coverage_gaps": gaps}, "issues": issues}


def _overlapping_count(text: str, needle: str, stop_after: int) -> int:
    count = 0
    offset = 0
    while count < stop_after:
        found = text.find(needle, offset)
        if found < 0:
            break
        count += 1
        offset = found + 1
    return count
