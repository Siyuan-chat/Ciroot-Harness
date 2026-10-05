"""Budgeted core gateway for the frozen patent source adapters.

Results are source drafts and frozen raw artifacts. This module never creates
accepted evidence or advances investigation state.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

import requests

from .patent_sources import (
    EPOLinkedAdapter, EPOPublicationAdapter, GPSSAdapter, JPOAdapter,
    KIPRISAdapter, PearlAdapter, SourceContext, SourceFailure, TIPOAdapter,
    USPTOAdapter,
)
from .patent_sources.uspto import DEFAULT_DOWNLOAD_HOSTS
from .patent_sources.contracts import pending

SOURCES = ("jpo", "epo_eps", "epo_linked", "uspto_odp", "wipo_pearl", "kipris_plus", "tipo_opd", "tipo_gpss")
TASK_STAGE_ROLES = {
    ("planning", "planning"): {"plan"},
    ("source", "patent_search"): {"search", "screen", "source_screening"},
    ("source", "paper_search"): {"search", "screen", "source_screening"},
    ("analysis", "evidence_analysis"): {"extract"},
}
_CREDENTIAL_FIELDS = re.compile(r"(?:^|_)(?:api_?key|access_?token|token|password|secret|authorization|credential)(?:$|_)", re.I)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _safe_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"}:
            return "[redacted-url]"
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "[redacted]" if parsed.query else "", ""))
    except ValueError:
        return "[redacted-url]"


def _contains_credentials(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_CREDENTIAL_FIELDS.search(str(k).casefold().replace("-", "_")) or _contains_credentials(v) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return any(_contains_credentials(v) for v in value)
    return False


def _sanitize(value: Any, secrets: tuple[str, ...] = ()) -> Any:
    if isinstance(value, bytes):
        return {"omitted_bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()}
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            name = str(key)
            if _CREDENTIAL_FIELDS.search(name.casefold().replace("-", "_")):
                result[name] = "[redacted]"
            elif name.casefold() in {"request_url", "final_url", "url"}:
                result[name] = _safe_url(item)
            else:
                result[name] = _sanitize(item, secrets)
        return result
    if isinstance(value, (list, tuple)):
        return [_sanitize(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[redacted]")
        return value
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:1000]


class PatentSourceGateway:
    """One-shot source execution bound to an existing run/task/request identity."""

    def __init__(self, service: Any, request_callback: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
                 *, timeout_seconds: float = 20.0, artifact_root: str | Path | None = None):
        self.service = service
        self.request_callback = request_callback or self._http_request
        if not callable(self.request_callback):
            raise ValueError("request_callback must be callable")
        if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
                or not 0 < timeout_seconds < float("inf")):
            raise ValueError("timeout_seconds must be finite and positive")
        self.timeout_seconds = float(timeout_seconds)
        self.artifact_root = Path(artifact_root) if artifact_root is not None else Path(service.root) / "patent-source-artifacts"
        self._ledger_path = Path(service.root) / "investigation.sqlite"

    def diagnose(self, run_id: str) -> dict[str, Any]:
        try:
            run = self.service._run(run_id)
            runtime = json.loads(run["runtime"])
        except Exception:
            return {"run_id": run_id, "status": "not_found", "sources": {}}
        profiles = runtime.get("patent_sources")
        if not isinstance(profiles, dict):
            return {"run_id": run_id, "status": "pending_config", "reason": "runtime.patent_sources is absent", "sources": {}}
        output = {}
        policy = runtime.get("data_policy")
        runtime_dispatchable = (runtime.get("data_mode") == "live" and runtime.get("allow_network") is True
                                and isinstance(policy, dict) and policy.get("allow_query_egress") is True)
        for source in SOURCES:
            profile = profiles.get(source)
            if not isinstance(profile, dict):
                output[source] = {"status": "pending_activation", "reason": "source profile is absent", "dispatch_enabled": False}
                continue
            enabled = profile.get("enabled") is True
            caps = profile.get("capabilities", [])
            status = "ready_for_authorized_dispatch" if enabled and isinstance(caps, list) and caps else ("pending_activation" if not enabled else "unsupported")
            reason = None if status == "ready_for_authorized_dispatch" else ("connector is disabled" if not enabled else "no explicit capabilities granted")
            runtime_budget = runtime.get("budget", {})
            row_budget = json.loads(run["budget"])
            if (any(type(runtime_budget.get(key)) is not int or runtime_budget[key] < 1 for key in ("max_source_calls", "max_source_bytes", "max_source_response_bytes"))
                    or type(row_budget.get("max_source_calls")) is not int or type(row_budget.get("reserved_source_calls")) is not int):
                status, reason = "pending_config", "explicit run source-call and byte budgets are incomplete"
            elif (type(profile.get("max_calls")) is not int or type(profile.get("max_response_bytes")) is not int
                  or profile.get("max_calls", 0) < 1 or not 1 <= profile.get("max_response_bytes", 0) <= runtime_budget["max_source_response_bytes"]):
                status, reason = "pending_config", "source-specific call and response-byte limits are incomplete"
            names, invalid_env = self._configured_env_names(source, profile)
            missing = [name for name in names if not os.environ.get(name)]
            if invalid_env:
                status, reason = "pending_config", "credential environment variable name is invalid"
            elif not runtime_dispatchable:
                status, reason = "pending_activation", "live network mode and explicit query-egress policy are required"
            elif not self._diagnostic_input_refs(run_id):
                status, reason = "policy_blocked", "no unique pending task with public, traceable input references"
            if missing:
                status, reason = "pending_activation", "required environment credential is not configured"
            if source in {"wipo_pearl", "tipo_gpss"}:
                status, reason = "pending_spec", "official business request/response contract is not available"
            elif source == "kipris_plus":
                status, reason = "pending_secure_transport", "official request examples specify HTTP; no request is dispatched"
            elif source == "tipo_opd":
                status, reason = "pending_spec", "TIPO getAuth response/token expiry decoder has no confirmed official schema"
            output[source] = {"status": status, "reason": reason, "enabled": enabled,
                              "capabilities": sorted(x for x in caps if isinstance(x, str)) if isinstance(caps, list) else [],
                              "credential_configured": not missing, "dispatch_enabled": status == "ready_for_authorized_dispatch"}
        return {"run_id": run_id, "status": "diagnosed", "sources": output,
                "network_enabled": runtime.get("allow_network") is True, "data_mode": runtime.get("data_mode")}

    def execute(self, run_id: str, task_id: str, task_version: int, request_id: str, source: str,
                operation: str, params: dict[str, Any], *, input_refs: list[str] | None = None) -> dict[str, Any]:
        """Dispatch exactly one logical request; request_id is never replayed."""
        error = self._preflight(run_id, task_id, task_version, request_id, source, operation, params, input_refs)
        if error is not None:
            return error
        run = self.service._run(run_id)
        runtime = json.loads(run["runtime"])
        profile = runtime["patent_sources"][source]
        query_id = "patent:" + hashlib.sha256(f"{task_id}\0{task_version}\0{request_id}".encode()).hexdigest()[:40]
        if not self._begin_logical_request(run_id, query_id, source, operation, params, input_refs or [], task_id, task_version, request_id):
            return (self._begin_failure or pending(source, operation, "busy", "RH_PATENT_SOURCE_BUSY", "source logical lease was not acquired")) | {"request_id": request_id}
        identity = {"run_id": run_id, "task_id": task_id, "task_version": task_version, "request_id": request_id, "query_id": query_id}
        capabilities = frozenset(profile["capabilities"])
        maximum = min(profile["max_response_bytes"], runtime["budget"]["max_source_response_bytes"])
        reservations: list[dict[str, Any]] = []
        artifacts: list[dict[str, Any]] = []
        blocked: dict[str, Any] = {}

        def reserve_budget(**kwargs: Any) -> dict[str, Any]:
            return self._reserve(run_id, query_id, source, profile, kwargs, reservations)

        def request(req: dict[str, Any]) -> dict[str, Any]:
            reservation = req.get("budget_reservation")
            if not self._prepare_dispatch(run_id, task_id, task_version, query_id, reservation, req, profile):
                blocked["reason"] = "query egress policy does not permit this payload"
                blocked["inactive"] = True
                self._abort_before_dispatch(reservation, "stale_or_inactive", {"code": "RH_PATENT_DISPATCH_REVALIDATION"})
                raise RuntimeError("policy blocked")
            try:
                response = self.request_callback({**req, "timeout": self.timeout_seconds})
            except BaseException:
                blocked["unknown"] = True
                self._finish_attempt(reservation, "outcome_unknown", {"code": "RH_SOURCE_OUTCOME_UNKNOWN"}, release_bytes=False)
                raise
            if not isinstance(response, dict) or not isinstance(response.get("content"), bytes):
                blocked["unknown"] = True
                self._finish_attempt(reservation, "outcome_unknown", {"code": "RH_SOURCE_OUTCOME_UNKNOWN"}, release_bytes=False)
                raise RuntimeError("transport did not return a byte response")
            body = response["content"]
            if len(body) > int(req["max_response_bytes"]):
                blocked["unknown"] = True
                self._finish_attempt(reservation, "outcome_unknown", {"code": "RH_SOURCE_SIZE_LIMIT", "response_bytes": len(body)}, release_bytes=False)
                raise RuntimeError("response exceeded reserved byte limit")
            artifact = self._freeze_artifact(run_id, request_id, len(artifacts), body, response.get("headers", {}))
            safe_result = {"operation": req.get("operation"), "capability": req.get("capability"),
                           "status_code": response.get("status_code", response.get("status")), "response_bytes": len(body),
                           "content_type": artifact["content_type"], "sha256": artifact["sha256"], "artifact_id": artifact["artifact_id"],
                           "request_url": _safe_url(req.get("url")), "final_url": _safe_url(response.get("url", req.get("url"))),
                           "redirects_disabled": True}
            if not self._finish_attempt(reservation, "received", safe_result, response_bytes=len(body), release_bytes=True):
                Path(artifact["path"]).unlink(missing_ok=True)
                blocked["late"] = True
                raise RuntimeError("late response ignored")
            artifacts.append(artifact)
            response = dict(response)
            response["request_identifier"] = artifact["artifact_id"]
            response["redirect_chain"] = []
            return response

        context = SourceContext(request=request, reserve_budget=reserve_budget, identity=identity,
                                capabilities=capabilities, max_response_bytes=maximum)
        adapter = self._adapter(source, context, profile)
        if source == "uspto_odp" and operation == "download_file":
            outcome = adapter.download_file(params.get("url"))
        else:
            outcome = adapter.execute(operation, params)
        if blocked.get("reason"):
            outcome = pending(source, operation, "inactive_run" if blocked.get("inactive") else "policy_blocked",
                              "RH_PATENT_DISPATCH_REVALIDATION" if blocked.get("inactive") else "RH_POLICY_BLOCKED", blocked["reason"])
        elif blocked.get("late"):
            outcome = pending(source, operation, "outcome_unknown", "RH_SOURCE_LATE_RESPONSE", "late response was ignored; request_id cannot be retried")
        elif blocked.get("unknown"):
            outcome = pending(source, operation, "outcome_unknown", "RH_SOURCE_OUTCOME_UNKNOWN", "transport outcome is unknown; request_id cannot be retried")
        outcome = self._externalize_bytes(outcome, run_id, request_id, artifacts)
        outcome["request_id"] = request_id
        outcome["identity"] = {key: identity[key] for key in ("run_id", "task_id", "task_version")}
        outcome["raw_response_artifacts"] = artifacts
        outcome["accepted_evidence"] = False
        outcome["coverage"] = {**(outcome.get("coverage") or {}), "normalization": "pending", "accepted_evidence": False}
        outcome = _sanitize(outcome, self._secret_values(profile))
        self._complete_logical_request(run_id, query_id, outcome)
        return outcome

    def _preflight(self, run_id: str, task_id: str, version: int, request_id: str, source: str,
                   operation: str, params: Any, input_refs: Any) -> dict[str, Any] | None:
        def reject(status: str, code: str, message: str) -> dict[str, Any]:
            return pending(source if source in SOURCES else "patent_source_gateway", operation if isinstance(operation, str) else "", status, code, message)
        if source not in SOURCES:
            return reject("unsupported", "RH_PATENT_SOURCE", "source is not registered")
        if (not all(isinstance(x, str) and x and len(x) <= 200 for x in (run_id, task_id, request_id))
                or type(version) is not int or version < 1):
            return reject("error", "RH_PATENT_IDENTITY", "run/task/request identity or task_version is invalid")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", request_id) or _CREDENTIAL_FIELDS.search(request_id.replace("-", "_")):
            return reject("error", "RH_PATENT_REQUEST_ID", "request_id must be a safe opaque identifier")
        if not isinstance(operation, str) or not operation or not isinstance(params, dict) or _contains_credentials(params):
            return reject("error", "RH_PATENT_PARAMS", "operation/params are invalid or contain credential fields")
        try:
            if len(_json(params).encode("utf-8")) > 65536:
                return reject("error", "RH_PATENT_PARAMS_SIZE", "params exceed 64 KiB")
        except (TypeError, ValueError):
            return reject("error", "RH_PATENT_PARAMS", "params must contain JSON-compatible values")
        try:
            run = self.service._run(run_id)
            runtime, stored_budget = json.loads(run["runtime"]), json.loads(run["budget"])
        except Exception:
            return reject("not_found", "RH_PATENT_RUN", "run does not exist")
        query_id = "patent:" + hashlib.sha256(f"{task_id}\0{version}\0{request_id}".encode()).hexdigest()[:40]
        prior = self.service.db.execute("SELECT 1 FROM source_queries WHERE run_id=? AND query_id=?", (run_id, query_id)).fetchone()
        if prior:
            return reject("duplicate_request", "RH_PATENT_REQUEST_DUPLICATE", "request_id has already been recorded; source calls are never replayed")
        if run["status"] in {"completed", "partial", "stopped", "failed", "policy_blocked", "cancelled"}:
            return reject("inactive_run", "RH_PATENT_RUN_TERMINAL", "terminal runs cannot dispatch source calls")
        if runtime.get("data_mode") != "live" or runtime.get("allow_network") is not True:
            return reject("pending_activation", "RH_PATENT_NETWORK_DISABLED", "live data_mode and allow_network=true are required")
        policy = runtime.get("data_policy")
        if not isinstance(policy, dict) or policy.get("allow_query_egress") is not True:
            return reject("policy_blocked", "RH_POLICY_BLOCKED", "explicit data_policy.allow_query_egress=true is required")
        profiles = runtime.get("patent_sources")
        if not isinstance(profiles, dict) or not isinstance(profiles.get(source), dict):
            return reject("pending_config", "RH_PATENT_PROFILE_MISSING", "runtime.patent_sources source profile is missing")
        profile = profiles[source]
        if profile.get("enabled") is not True:
            return reject("pending_activation", "RH_PATENT_DISABLED", "source profile is disabled")
        caps = profile.get("capabilities")
        if not isinstance(caps, list) or not caps or any(not isinstance(x, str) for x in caps):
            return reject("unsupported", "RH_PATENT_CAPABILITIES", "explicit source capabilities are required")
        if source in {"wipo_pearl", "kipris_plus", "tipo_gpss", "tipo_opd"}:
            state = {"wipo_pearl":"pending_spec", "kipris_plus":"pending_secure_transport", "tipo_gpss":"pending_spec", "tipo_opd":"pending_spec"}[source]
            return reject(state, "RH_PATENT_SOURCE_NOT_READY", "source adapter has no confirmed dispatch contract")
        env_names, invalid_env = self._configured_env_names(source, profile)
        if invalid_env:
            return reject("pending_config", "RH_PATENT_CREDENTIAL_ENV", "credential environment variable name is invalid")
        for name in env_names:
            if not os.environ.get(name):
                return reject("pending_activation", "RH_PATENT_CREDENTIAL_MISSING", "required environment credential is not configured")
        if type(profile.get("max_calls")) is not int or profile["max_calls"] < 1:
            return reject("pending_config", "RH_PATENT_SOURCE_BUDGET", "profile.max_calls must be an explicit positive integer")
        budget = runtime.get("budget")
        required = ("max_source_calls", "max_source_bytes", "max_source_response_bytes")
        if not isinstance(budget, dict) or any(type(budget.get(k)) is not int or budget[k] < 1 for k in required):
            return reject("pending_config", "RH_PATENT_BUDGET_MISSING", "max_source_calls, max_source_bytes and max_source_response_bytes must be explicitly configured")
        if (type(stored_budget.get("max_source_calls")) is not int or type(stored_budget.get("reserved_source_calls")) is not int
                or stored_budget["max_source_calls"] != budget["max_source_calls"]):
            return reject("pending_config", "RH_PATENT_BUDGET_MISSING", "run budget must contain max_source_calls and reserved_source_calls")
        maximum = profile.get("max_response_bytes")
        if type(maximum) is not int or not 1 <= maximum <= budget["max_source_response_bytes"]:
            return reject("pending_config", "RH_PATENT_RESPONSE_BUDGET", "profile.max_response_bytes must be positive and no greater than run response limit")
        task = self.service.db.execute("SELECT * FROM model_tasks WHERE id=? AND run_id=? AND task_version=?", (task_id, run_id, version)).fetchone()
        if task is None or task["status"] != "pending":
            return reject("stale_task", "RH_PATENT_TASK_STALE", "task is absent, belongs to another run/version, or is not pending")
        task_types = TASK_STAGE_ROLES.get((run["stage"], task["role"]))
        if not task_types or task["task_type"] not in task_types:
            return reject("stage_blocked", "RH_PATENT_TASK_STAGE", "current stage and task role/type do not permit source acquisition")
        pending_rows = list(self.service.db.execute("SELECT id FROM model_tasks WHERE run_id=? AND status='pending'", (run_id,)))
        if len(pending_rows) != 1 or pending_rows[0]["id"] != task_id:
            return reject("busy", "RH_PATENT_OTHER_TASK_PENDING", "the requested task must be the only pending model task")
        if self.service.db.execute("SELECT 1 FROM engine_task_leases WHERE run_id=? AND status IN ('reserved','dispatching','outcome_unknown') LIMIT 1", (run_id,)).fetchone():
            return reject("busy", "RH_PATENT_ENGINE_BUSY", "an engine task lease is unresolved")
        if self.service.db.execute("SELECT 1 FROM engine_task_leases WHERE run_id=? AND task_id=? AND task_version=? AND status='accepted' LIMIT 1", (run_id, task_id, version)).fetchone():
            return reject("busy", "RH_PATENT_ENGINE_BUSY", "the current task version already has an accepted engine lease")
        try:
            if self.service.db.execute("SELECT 1 FROM model_api_calls WHERE run_id=? AND status IN ('reserved','prepared','dispatching','response_received','outcome_unknown') LIMIT 1", (run_id,)).fetchone():
                return reject("busy", "RH_PATENT_MODEL_BUSY", "a model call is unresolved")
        except sqlite3.OperationalError:
            return reject("pending_config", "RH_PATENT_LEDGER_SCHEMA", "model_api_calls ledger is missing")
        ledger = self._connect()
        try:
            if ledger.execute("SELECT 1 FROM source_attempts WHERE run_id=? AND status IN ('pending','dispatching','outcome_unknown') LIMIT 1", (run_id,)).fetchone():
                return reject("busy", "RH_PATENT_SOURCE_BUSY", "an earlier source call has an unresolved outcome")
        finally:
            ledger.close()
        try:
            payload = json.loads(task["payload"])
        except Exception:
            return reject("error", "RH_PATENT_TASK_PAYLOAD", "task payload is invalid")
        declared = payload.get("input_refs")
        if (not isinstance(input_refs, list) or not input_refs
                or any(not isinstance(x, str) or not x for x in input_refs) or declared != input_refs):
            return reject("policy_blocked", "RH_PATENT_INPUT_REFS", "input_refs must exactly match the task's explicit, non-empty traceable references")
        if not self._inputs_exportable(run_id, run, runtime, input_refs):
            return reject("policy_blocked", "RH_POLICY_INPUT_VISIBILITY", "input visibility/company ownership is unknown or disallowed for source egress")
        return None

    def _inputs_exportable(self, run_id: str, run: Any, runtime: dict[str, Any], refs: list[str]) -> bool:
        db = getattr(self, "_validation_db", None) or self.service.db
        policy = runtime.get("data_policy", {})
        scenario = json.loads(run["scenario"])
        known: dict[str, dict[str, Any]] = {}
        for table, key in (("discovery_evidence", "evidence_id"), ("discovery_documents", "document_id")):
            columns = {item[1] for item in db.execute(f"PRAGMA table_info({table})")}
            visibility = ",visibility" if "visibility" in columns else ""
            company = ",company_id" if "company_id" in columns else ""
            for row in db.execute(f"SELECT {key},payload{visibility}{company} FROM {table} WHERE run_id=?", (run_id,)):
                try:
                    item = json.loads(row["payload"])
                except Exception:
                    item = {}
                actual_visibility = row["visibility"] if "visibility" in row.keys() else item.get("visibility", "unknown")
                actual_company = row["company_id"] if "company_id" in row.keys() else item.get("company_id")
                known[row[key]] = {**item, "visibility": actual_visibility or "unknown", "company_id": actual_company}
        for item in scenario.get("references", []) + scenario.get("baseline_snapshot", []):
            if isinstance(item, dict):
                for key in ("evidence_id", "document_id", "id"):
                    if isinstance(item.get(key), str):
                        known[item[key]] = item
        for ref in refs:
            item = known.get(ref)
            if not item or item.get("visibility", "unknown") != "public":
                return False
            if item.get("company_id") and item.get("company_id") != policy.get("company_id"):
                return False
        return True

    def _begin_logical_request(self, run_id: str, query_id: str, source: str, operation: str,
                               params: dict[str, Any], refs: list[str], task_id: str, task_version: int,
                               request_id: str) -> bool:
        self._begin_failure = None
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM source_queries WHERE run_id=? AND query_id=?", (run_id, query_id)).fetchone():
                db.rollback()
                self._begin_failure = pending(source, operation, "duplicate_request", "RH_PATENT_REQUEST_DUPLICATE", "request_id has already been recorded")
                return False
            self._validation_db = db
            failure = self._validate_live_lease(db, run_id, task_id, task_version, query_id=None)
            self._validation_db = None
            if failure:
                db.rollback()
                self._begin_failure = pending(source, operation, *failure)
                return False
            row = db.execute("SELECT budget FROM investigations WHERE id=?", (run_id,)).fetchone()
            budget = json.loads(row["budget"])
            if type(budget.get("max_source_calls")) is not int or type(budget.get("reserved_source_calls")) is not int:
                db.rollback()
                self._begin_failure = pending(source, operation, "pending_config", "RH_PATENT_BUDGET_MISSING", "run source-call budget is incomplete")
                return False
            descriptor = {"operation": operation, "params_sha256": _digest(params), "input_refs_sha256": _digest(refs)}
            db.execute("INSERT INTO source_queries VALUES (?,?,?,?,?,?,?,?)", (run_id, query_id, source, _json(descriptor), None, _json(refs), "dispatching", None))
            db.execute("INSERT OR REPLACE INTO source_query_details VALUES (?,?,?)", (run_id, query_id, _json({"gateway": {"task_id": task_id, "task_version": task_version, "request_id": request_id, "created": time.time()}})))
            db.commit()
            return True
        except sqlite3.Error:
            db.rollback()
            self._begin_failure = pending(source, operation, "ledger_error", "RH_PATENT_LEDGER", "logical source lease could not be recorded")
            return False
        finally:
            db.close()

    def _validate_live_lease(self, db: sqlite3.Connection, run_id: str, task_id: str,
                             task_version: int, query_id: str | None) -> tuple[str, str, str] | None:
        run = db.execute("SELECT * FROM investigations WHERE id=?", (run_id,)).fetchone()
        if not run:
            return ("not_found", "RH_PATENT_RUN", "run does not exist")
        if run["status"] in {"completed", "partial", "stopped", "failed", "policy_blocked", "cancelled"}:
            return ("inactive_run", "RH_PATENT_RUN_TERMINAL", "run is no longer active")
        runtime = json.loads(run["runtime"])
        policy = runtime.get("data_policy")
        if runtime.get("data_mode") != "live" or runtime.get("allow_network") is not True:
            return ("pending_activation", "RH_PATENT_NETWORK_DISABLED", "live network dispatch is disabled")
        if not isinstance(policy, dict) or policy.get("allow_query_egress") is not True:
            return ("policy_blocked", "RH_POLICY_BLOCKED", "query egress policy is disabled")
        task = db.execute("SELECT * FROM model_tasks WHERE id=? AND run_id=?", (task_id, run_id)).fetchone()
        if not task or task["task_version"] != task_version or task["status"] != "pending":
            return ("stale_task", "RH_PATENT_TASK_STALE", "task is no longer pending at the requested version")
        allowed = TASK_STAGE_ROLES.get((run["stage"], task["role"]))
        if not allowed or task["task_type"] not in allowed:
            return ("stage_blocked", "RH_PATENT_TASK_STAGE", "task stage or role no longer permits source acquisition")
        pending_tasks = list(db.execute("SELECT id FROM model_tasks WHERE run_id=? AND status='pending'", (run_id,)))
        if len(pending_tasks) != 1 or pending_tasks[0]["id"] != task_id:
            return ("busy", "RH_PATENT_OTHER_TASK_PENDING", "the requested task is not the unique pending task")
        if db.execute("SELECT 1 FROM engine_task_leases WHERE run_id=? AND status IN ('reserved','dispatching','outcome_unknown') LIMIT 1", (run_id,)).fetchone():
            return ("busy", "RH_PATENT_ENGINE_BUSY", "an engine task lease is unresolved")
        if db.execute("SELECT 1 FROM engine_task_leases WHERE run_id=? AND task_id=? AND task_version=? AND status='accepted' LIMIT 1", (run_id, task_id, task_version)).fetchone():
            return ("busy", "RH_PATENT_ENGINE_BUSY", "the current task version already has an accepted engine lease")
        try:
            if db.execute("SELECT 1 FROM model_api_calls WHERE run_id=? AND status IN ('reserved','prepared','dispatching','response_received','outcome_unknown') LIMIT 1", (run_id,)).fetchone():
                return ("busy", "RH_PATENT_MODEL_BUSY", "a model call is unresolved")
        except sqlite3.OperationalError:
            return ("pending_config", "RH_PATENT_LEDGER_SCHEMA", "model_api_calls ledger is missing")
        unresolved = db.execute("SELECT query_id FROM source_queries WHERE run_id=? AND status IN ('pending','dispatching','outcome_unknown')", (run_id,))
        if any(row["query_id"] != query_id for row in unresolved):
            return ("busy", "RH_PATENT_SOURCE_BUSY", "another source logical request is unresolved")
        refs = json.loads(task["payload"]).get("input_refs")
        self._validation_db = db
        exportable = isinstance(refs, list) and bool(refs) and self._inputs_exportable(run_id, run, runtime, refs)
        self._validation_db = None
        if not exportable:
            return ("policy_blocked", "RH_POLICY_INPUT_VISIBILITY", "task input references are absent or not exportable")
        return None

    def _diagnostic_input_refs(self, run_id: str) -> bool:
        db = self._connect()
        try:
            rows = list(db.execute("SELECT * FROM model_tasks WHERE run_id=? AND status='pending'", (run_id,)))
            if len(rows) != 1:
                return False
            run = db.execute("SELECT * FROM investigations WHERE id=?", (run_id,)).fetchone()
            runtime = json.loads(run["runtime"])
            refs = json.loads(rows[0]["payload"]).get("input_refs")
            self._validation_db = db
            return isinstance(refs, list) and bool(refs) and self._inputs_exportable(run_id, run, runtime, refs)
        except Exception:
            return False
        finally:
            self._validation_db = None
            db.close()

    def _finish_attempt(self, reservation: Any, status: str, result: dict[str, Any], *,
                        response_bytes: int = 0, release_bytes: bool) -> bool:
        if not isinstance(reservation, dict):
            return False
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT budget FROM investigations WHERE id=?", (reservation["run_id"],)).fetchone()
            attempt = db.execute("SELECT status FROM source_attempts WHERE run_id=? AND query_id=? AND cursor=? AND attempt=?",
                                 (reservation["run_id"], reservation["query_id"], reservation["cursor"], reservation["attempt"])).fetchone()
            if not row or not attempt or attempt["status"] != "dispatching":
                db.rollback()
                return False
            budget = json.loads(row["budget"])
            maximum = reservation["max_bytes"]
            try:
                prior_result = json.loads(db.execute("SELECT result FROM source_attempts WHERE run_id=? AND query_id=? AND cursor=? AND attempt=?",
                                                     (reservation["run_id"], reservation["query_id"], reservation["cursor"], reservation["attempt"])).fetchone()[0])
            except (TypeError, json.JSONDecodeError):
                prior_result = {}
            final_result = {**prior_result, **result}
            if release_bytes:
                budget["reserved_source_bytes"] = max(0, int(budget.get("reserved_source_bytes", 0)) - maximum)
            if response_bytes:
                budget["received_source_bytes"] = int(budget.get("received_source_bytes", 0)) + response_bytes
            if reservation.get("download"):
                if release_bytes:
                    budget["reserved_download_bytes"] = max(0, int(budget.get("reserved_download_bytes", 0)) - maximum)
                if response_bytes:
                    budget["received_download_bytes"] = int(budget.get("received_download_bytes", 0)) + response_bytes
            db.execute("UPDATE investigations SET budget=?,updated=? WHERE id=?", (_json(budget), time.time(), reservation["run_id"]))
            db.execute("UPDATE source_attempts SET status=?,result=? WHERE run_id=? AND query_id=? AND cursor=? AND attempt=? AND status='dispatching'",
                       (status, _json(_sanitize(final_result)), reservation["run_id"], reservation["query_id"], reservation["cursor"], reservation["attempt"]))
            changed = db.execute("SELECT changes()").fetchone()[0] == 1
            db.commit()
            return changed
        except sqlite3.Error:
            db.rollback()
            return False
        finally:
            db.close()

    def _prepare_dispatch(self, run_id: str, task_id: str, task_version: int, query_id: str,
                          reservation: Any, request: dict[str, Any], profile: dict[str, Any]) -> bool:
        if not isinstance(reservation, dict) or _contains_credentials(request.get("params")):
            return False
        body = request.get("body")
        if isinstance(body, bytes) and len(body) > 65536:
            return False
        identity = request.get("identity")
        if not isinstance(identity, dict) or identity.get("run_id") != run_id or identity.get("task_id") != task_id or identity.get("task_version") != task_version or identity.get("query_id") != query_id:
            return False
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            failure = self._validate_live_lease(db, run_id, task_id, task_version, query_id)
            if failure:
                db.rollback()
                return False
            attempt = db.execute("SELECT status,result FROM source_attempts WHERE run_id=? AND query_id=? AND cursor=? AND attempt=?",
                                 (run_id, query_id, reservation["cursor"], reservation["attempt"])).fetchone()
            if not attempt or attempt["status"] != "dispatching":
                db.rollback()
                return False
            sensitive = {str(x).casefold() for x in request.get("sensitive_headers", []) if isinstance(x, str)}
            headers = request.get("headers") if isinstance(request.get("headers"), dict) else {}
            safe_header_names = sorted(str(k).casefold() for k in headers if str(k).casefold() not in sensitive and str(k).casefold() not in {"authorization", "proxy-authorization", "x-api-key", "cookie", "set-cookie"})
            secrets = self._secret_values(profile)
            sanitized_params = self._redact_values(request.get("params") or {}, secrets)
            receipt = {"method": request.get("method"), "url": _safe_url(request.get("url")),
                       "params_sha256": _digest(sanitized_params), "header_names": safe_header_names,
                       "body_bytes": len(body) if isinstance(body, bytes) else (len(body.encode("utf-8")) if isinstance(body, str) else 0)}
            if isinstance(body, bytes):
                try:
                    parsed = json.loads(body.decode("utf-8"))
                    if not _contains_credentials(parsed):
                        receipt["body_sha256"] = _digest(parsed)
                    else:
                        receipt["body_sha256"] = _digest(self._redact_values(self._redact_credential_fields(parsed), secrets))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    receipt["body_sha256"] = None
            result = json.loads(attempt["result"])
            result.update({"request_sha256": _digest(receipt), "request_receipt": receipt,
                           "request_receipt_status": "recorded_before_dispatch"})
            db.execute("UPDATE source_attempts SET result=? WHERE run_id=? AND query_id=? AND cursor=? AND attempt=? AND status='dispatching'",
                       (_json(_sanitize(result)),
                        run_id, query_id, reservation["cursor"], reservation["attempt"]))
            db.commit()
            return True
        except (sqlite3.Error, KeyError, TypeError, ValueError):
            db.rollback()
            return False
        finally:
            db.close()

    @staticmethod
    def _redact_credential_fields(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: ("[redacted]" if _CREDENTIAL_FIELDS.search(str(k).casefold().replace("-", "_")) else PatentSourceGateway._redact_credential_fields(v)) for k, v in value.items()}
        if isinstance(value, list):
            return [PatentSourceGateway._redact_credential_fields(v) for v in value]
        return value

    @staticmethod
    def _redact_values(value: Any, secrets: tuple[str, ...]) -> Any:
        if isinstance(value, dict):
            return {k: PatentSourceGateway._redact_values(v, secrets) for k, v in value.items()}
        if isinstance(value, list):
            return [PatentSourceGateway._redact_values(v, secrets) for v in value]
        if isinstance(value, str):
            for secret in secrets:
                if secret:
                    value = value.replace(secret, "[redacted]")
        return value

    def _abort_before_dispatch(self, reservation: Any, status: str, result: dict[str, Any]) -> bool:
        if not isinstance(reservation, dict):
            return False
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            run = db.execute("SELECT budget FROM investigations WHERE id=?", (reservation["run_id"],)).fetchone()
            attempt = db.execute("SELECT status FROM source_attempts WHERE run_id=? AND query_id=? AND cursor=? AND attempt=?",
                                 (reservation["run_id"], reservation["query_id"], reservation["cursor"], reservation["attempt"])).fetchone()
            if not run or not attempt or attempt["status"] != "dispatching":
                db.rollback()
                return False
            budget = json.loads(run["budget"])
            maximum = reservation["max_bytes"]
            budget["reserved_source_calls"] = max(0, int(budget.get("reserved_source_calls", 0)) - 1)
            budget["reserved_source_bytes"] = max(0, int(budget.get("reserved_source_bytes", 0)) - maximum)
            if reservation.get("download"):
                budget["reserved_download_calls"] = max(0, int(budget.get("reserved_download_calls", 0)) - 1)
                budget["reserved_download_bytes"] = max(0, int(budget.get("reserved_download_bytes", 0)) - maximum)
            db.execute("UPDATE investigations SET budget=?,updated=? WHERE id=?", (_json(budget), time.time(), reservation["run_id"]))
            db.execute("UPDATE source_attempts SET status=?,result=? WHERE run_id=? AND query_id=? AND cursor=? AND attempt=? AND status='dispatching'",
                       (status, _json(_sanitize(result)), reservation["run_id"], reservation["query_id"], reservation["cursor"], reservation["attempt"]))
            db.execute("UPDATE source_queries SET status=? WHERE run_id=? AND query_id=? AND status='dispatching'",
                       (status, reservation["run_id"], reservation["query_id"]))
            db.commit()
            return True
        except sqlite3.Error:
            db.rollback()
            return False
        finally:
            db.close()

    def _complete_logical_request(self, run_id: str, query_id: str, outcome: dict[str, Any]) -> None:
        status = outcome.get("status", "partial")
        issues = outcome.get("issues") or []
        reason = issues[0].get("code") if issues and isinstance(issues[0], dict) else None
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE source_queries SET status=?,reason=? WHERE run_id=? AND query_id=? AND status IN ('dispatching','pending')",
                       (status, reason, run_id, query_id))
            row = db.execute("SELECT payload FROM source_query_details WHERE run_id=? AND query_id=?", (run_id, query_id)).fetchone()
            details = json.loads(row["payload"]) if row else {}
            details["outcome"] = _sanitize({k: outcome.get(k) for k in
                ("source", "operation", "status", "capability", "coverage", "issues", "provenance", "raw_response_artifacts", "accepted_evidence")})
            db.execute("INSERT OR REPLACE INTO source_query_details VALUES (?,?,?)", (run_id, query_id, _json(details)))
            db.commit()
        except sqlite3.Error:
            db.rollback()
        finally:
            db.close()

    def _egress_allowed(self, run_id: str, task_id: str, request: dict[str, Any]) -> bool:
        if _contains_credentials(request.get("params")):
            return False
        body = request.get("body")
        if isinstance(body, bytes) and len(body) > 65536:
            return False
        try:
            run = self.service._run(run_id)
            runtime = json.loads(run["runtime"])
            policy = runtime.get("data_policy", {})
            if runtime.get("data_mode") != "live" or runtime.get("allow_network") is not True or policy.get("allow_query_egress") is not True:
                return False
            task = self.service.db.execute("SELECT payload FROM model_tasks WHERE id=? AND run_id=?", (task_id, run_id)).fetchone()
            if task is None:
                return False
            refs = json.loads(task["payload"]).get("input_refs", [])
            return isinstance(refs, list) and bool(refs) and self._inputs_exportable(run_id, run, runtime, refs)
        except Exception:
            return False

    def _adapter(self, source: str, context: SourceContext, profile: dict[str, Any]) -> Any:
        enabled = profile.get("enabled") is True
        if source == "jpo":
            return JPOAdapter(context, enabled=enabled, token_env=profile.get("token_env", "JPO_API_TOKEN"), opd_enabled=profile.get("opd_enabled") is True)
        if source == "epo_eps":
            return EPOPublicationAdapter(context, enabled=enabled)
        if source == "epo_linked":
            return EPOLinkedAdapter(context, enabled=enabled)
        if source == "uspto_odp":
            return USPTOAdapter(context, enabled=enabled, api_key_env=profile.get("api_key_env", "USPTO_ODP_API_KEY"),
                                download_hosts=DEFAULT_DOWNLOAD_HOSTS)
        if source == "wipo_pearl":
            return PearlAdapter(context, enabled=enabled, spec_configured=False)
        if source == "kipris_plus":
            return KIPRISAdapter(context, enabled=enabled, api_key_env=profile.get("api_key_env", "KIPRIS_SERVICE_KEY"))
        if source == "tipo_opd":
            # No decoder is injected until an identified official response/expiry schema exists.
            return TIPOAdapter(context, enabled=enabled, username_env=profile.get("username_env", "TIPO_API_USERNAME"),
                               password_env=profile.get("password_env", "TIPO_API_PASSWORD"))
        if source == "tipo_gpss":
            return GPSSAdapter(context, enabled=enabled, spec_configured=False)
        return None

    def _env_names(self, source: str, profile: dict[str, Any]) -> list[str]:
        return self._configured_env_names(source, profile)[0]

    def _configured_env_names(self, source: str, profile: dict[str, Any]) -> tuple[list[str], bool]:
        mapping = {
            "jpo": (profile.get("token_env", "JPO_API_TOKEN"),),
            "uspto_odp": (profile.get("api_key_env", "USPTO_ODP_API_KEY"),),
            "kipris_plus": (profile.get("api_key_env", "KIPRIS_SERVICE_KEY"),),
            "tipo_opd": (profile.get("username_env", "TIPO_API_USERNAME"), profile.get("password_env", "TIPO_API_PASSWORD")),
        }
        configured = mapping.get(source, ())
        invalid = any(not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) for name in configured)
        return ([name for name in configured if isinstance(name, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)], invalid)

    def _secret_values(self, profile: dict[str, Any]) -> tuple[str, ...]:
        values = []
        for key in ("token_env", "api_key_env", "username_env", "password_env"):
            name = profile.get(key)
            if isinstance(name, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) and os.environ.get(name):
                values.append(os.environ[name])
        return tuple(values)

    def _freeze_artifact(self, run_id: str, request_id: str, ordinal: int, body: bytes, headers: Any) -> dict[str, Any]:
        digest = hashlib.sha256(body).hexdigest()
        run_part = hashlib.sha256(run_id.encode()).hexdigest()[:24]
        request_part = hashlib.sha256(request_id.encode()).hexdigest()[:24]
        root = self.artifact_root.resolve()
        directory = (root / run_part / request_part).resolve()
        if root != directory and root not in directory.parents:
            raise ValueError("artifact path escaped root")
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{ordinal:03d}-{digest}.bin"
        if not path.exists():
            with tempfile.NamedTemporaryFile(dir=directory, delete=False) as tmp:
                tmp.write(body)
                temp_path = Path(tmp.name)
            os.replace(temp_path, path)
        ctype = "application/octet-stream"
        if isinstance(headers, dict):
            ctype = str(next((v for k, v in headers.items() if str(k).casefold() == "content-type"), ctype))[:120]
        return {"artifact_id": f"sha256:{digest}", "sha256": digest, "size_bytes": len(body),
                "content_type": ctype, "path": str(path), "frozen": True, "parsed": False}

    def _externalize_bytes(self, outcome: dict[str, Any], run_id: str, request_id: str,
                           artifacts: list[dict[str, Any]]) -> dict[str, Any]:
        def visit(value: Any) -> Any:
            if isinstance(value, bytes):
                digest = hashlib.sha256(value).hexdigest()
                if not any(item["sha256"] == digest for item in artifacts):
                    artifacts.append(self._freeze_artifact(run_id, request_id, len(artifacts), value, {}))
                artifact = next(item for item in artifacts if item["sha256"] == digest)
                return {"artifact_id": artifact["artifact_id"], "sha256": digest, "size_bytes": len(value),
                        "content_type": artifact["content_type"], "parse_status": "pending", "accepted_evidence": False}
            if isinstance(value, dict):
                return {key: visit(item) for key, item in value.items()}
            if isinstance(value, list):
                return [visit(item) for item in value]
            return value
        if outcome.get("data") is not None:
            outcome["data"] = visit(outcome["data"])
        return outcome

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self._ledger_path, timeout=15.0)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _is_download(operation: str) -> bool:
        value = str(operation).casefold()
        return (any(part in value for part in ("download", "document_file", "getfile", "global_doc_content", "jp_doc_content"))
                or value in {"document", "application_documents", "dispatch_documents", "refusal_reason_documents"})

    def _http_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """One HTTPS request, redirects disabled, response read under byte cap."""
        url = request.get("url")
        if not isinstance(url, str) or urlsplit(url).scheme != "https":
            raise ValueError("only HTTPS requests are permitted")
        method = request.get("method")
        if method not in {"GET", "POST"}:
            raise ValueError("unsupported HTTP method")
        response = requests.request(method, url, headers=request.get("headers"), params=request.get("params"),
                                    data=request.get("body"), timeout=request.get("timeout", self.timeout_seconds),
                                    allow_redirects=False, stream=True)
        try:
            limit = int(request["max_response_bytes"])
            length = response.headers.get("Content-Length")
            if length is not None and int(length) > limit:
                raise ValueError("response exceeds byte limit")
            parts = []
            size = 0
            for chunk in response.iter_content(65536):
                if not chunk:
                    continue
                size += len(chunk)
                if size > limit:
                    raise ValueError("response exceeds byte limit")
                parts.append(chunk)
            return {"status_code": response.status_code, "headers": dict(response.headers),
                    "content": b"".join(parts), "url": response.url, "redirect_chain": []}
        finally:
            response.close()

    def _reserve(self, run_id: str, query_id: str, source: str, profile: dict[str, Any],
                 kwargs: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
        identity = kwargs.get("identity", {})
        if identity.get("run_id") != run_id or identity.get("query_id") != query_id:
            raise SourceFailure("error", "RH_PATENT_IDENTITY", "physical request identity differs from active run")
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            failure = self._validate_live_lease(db, run_id, identity.get("task_id"), identity.get("task_version"), query_id)
            if failure:
                raise SourceFailure(*failure)
            row = db.execute("SELECT budget,runtime FROM investigations WHERE id=?", (run_id,)).fetchone()
            if not row:
                raise SourceFailure("not_found", "RH_PATENT_RUN", "run disappeared before reservation")
            budget, runtime = json.loads(row["budget"]), json.loads(row["runtime"])
            limits = runtime.get("budget", {})
            max_calls, used = budget.get("max_source_calls"), budget.get("reserved_source_calls")
            if type(max_calls) is not int or type(used) is not int or max_calls != limits.get("max_source_calls") or used >= max_calls:
                raise SourceFailure("budget_denied", "RH_PATENT_BUDGET", "source call budget is absent or exhausted")
            count = db.execute("SELECT COUNT(*) FROM source_attempts a JOIN source_queries q ON q.run_id=a.run_id AND q.query_id=a.query_id WHERE a.run_id=? AND q.source=?", (run_id, source)).fetchone()[0]
            if count >= profile["max_calls"]:
                raise SourceFailure("budget_denied", "RH_PATENT_SOURCE_BUDGET", "source-specific max_calls is exhausted")
            if type(limits.get("max_source_bytes")) is not int or type(limits.get("max_source_response_bytes")) is not int:
                raise SourceFailure("pending_config", "RH_PATENT_BUDGET_MISSING", "source byte limits are missing")
            maximum = min(int(kwargs.get("max_response_bytes", 0)), profile["max_response_bytes"], limits["max_source_response_bytes"])
            if maximum < 1:
                raise SourceFailure("budget_denied", "RH_PATENT_RESPONSE_BUDGET", "invalid response-byte reservation")
            received, reserved = budget.get("received_source_bytes", 0), budget.get("reserved_source_bytes", 0)
            if type(received) is not int or type(reserved) is not int or received + reserved + maximum > limits["max_source_bytes"]:
                raise SourceFailure("budget_denied", "RH_PATENT_BYTE_BUDGET", "source byte budget cannot reserve the maximum response")
            is_download = self._is_download(kwargs.get("operation", ""))
            if is_download:
                dl_calls, dl_max = budget.get("reserved_download_calls"), limits.get("max_download_calls")
                dl_bytes, dl_limit = budget.get("reserved_download_bytes", 0), limits.get("max_download_bytes")
                dl_received = budget.get("received_download_bytes", 0)
                if type(dl_calls) is not int or type(dl_max) is not int or type(dl_limit) is not int or dl_calls >= dl_max:
                    raise SourceFailure("budget_denied", "RH_PATENT_DOWNLOAD_BUDGET", "download count budget is absent or exhausted")
                if type(dl_bytes) is not int or type(dl_received) is not int or dl_bytes + dl_received + maximum > dl_limit:
                    raise SourceFailure("budget_denied", "RH_PATENT_DOWNLOAD_BYTES", "download byte budget cannot reserve response")
                budget["reserved_download_calls"] = dl_calls + 1
                budget["reserved_download_bytes"] = dl_bytes + maximum
            budget["reserved_source_calls"] = used + 1
            budget["reserved_source_bytes"] = reserved + maximum
            db.execute("UPDATE investigations SET budget=?,updated=? WHERE id=?", (_json(budget), time.time(), run_id))
            cursor = f"{len(records) + 1}:{kwargs.get('operation', 'request')}"
            reservation = {"run_id": run_id, "query_id": query_id, "cursor": cursor, "attempt": 1, "max_bytes": maximum, "download": is_download}
            safe_request = {"operation": kwargs.get("operation"), "capability": kwargs.get("capability"),
                            "request_sha256": None, "request_receipt_status": "awaiting_prepared_request"}
            db.execute("INSERT INTO source_attempts VALUES (?,?,?,?,?,?)", (run_id, query_id, cursor, 1, "dispatching", _json(safe_request)))
            db.execute("UPDATE source_queries SET status='dispatching' WHERE run_id=? AND query_id=?", (run_id, query_id))
            db.commit()
            records.append(reservation)
            return reservation
        except SourceFailure:
            db.rollback()
            raise
        except sqlite3.Error as exc:
            db.rollback()
            raise SourceFailure("budget_denied", "RH_PATENT_LEDGER", "source ledger reservation failed") from exc
        finally:
            db.close()
