"""Loopback-only HTTP projection of existing harness services."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
import threading
import uuid
import asyncio
import html
import io
import contextvars
from urllib.parse import urlsplit
from importlib import resources
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse, Response, HTMLResponse
from fastapi.staticfiles import StaticFiles

from research_harness.investigation import InvestigationService, InvestigationError
from research_harness.rag import RagLibrary, RagError
from research_harness.gui import local_library
from research_harness.investigation_model_api import run_model_task
from research_harness.golden_demo import run_golden_demo
from research_harness.gui.golden_demo import GoldenDemoFacade
from research_harness.gui.conversation import ConversationError, ConversationStore
from research_harness.gui.conversation_model_api import controlled_runtime, plan as plan_conversation, validate_api_config
from research_harness.gui.help import HelpLibrary


MODEL_KEY_ENV = {
    "openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY", "qwen": "DASHSCOPE_API_KEY",
    "kimi": "MOONSHOT_API_KEY",
}
SOURCE_KEY_ENV = {
    "openalex_api_key": "OPENALEX_API_KEY",
    "epo_consumer_key": "EPO_CONSUMER_KEY",
    "epo_consumer_secret": "EPO_CONSUMER_SECRET",
}


def _page(items, limit, cursor):
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    try:
        offset = int(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))) if cursor else 0
    except Exception as exc:
        raise ValueError("invalid cursor") from exc
    if offset < 0:
        raise ValueError("invalid cursor")
    end = offset + limit
    next_cursor = base64.urlsafe_b64encode(str(end).encode()).decode().rstrip("=") if end < len(items) else None
    return {"items": items[offset:end], "next_cursor": next_cursor}


def _golden_demo_available() -> bool:
    """Return whether the deterministic demo inputs are present in the package."""
    base = resources.files("research_harness").joinpath("examples", "investigation")
    names = ("golden-demo-spec.json", "synthetic-runtime.json", "golden-demo-scenario.json")
    try:
        return all(
            resource.is_file()
            and isinstance(json.loads(resource.read_text(encoding="utf-8-sig")), dict)
            for resource in (base.joinpath(name) for name in names)
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ModuleNotFoundError):
        return False


def load_context_registry(path: str | Path) -> tuple[dict, dict]:
    """Read trusted local registrations; browser requests can only choose IDs."""
    config_path=Path(path).resolve()
    data=json.loads(config_path.read_text(encoding="utf-8"))
    def normalize(records):
        result={}
        for ident,record in records.items():
            if not ident or any(char in ident for char in "/\\\0"):
                raise ValueError("context IDs must be stable names, not paths")
            item=dict(record)
            item["path"]=(config_path.parent/Path(item["path"])).resolve() if not Path(item["path"]).is_absolute() else Path(item["path"]).resolve()
            result[ident]=item
        return result
    return normalize(data.get("workspaces",{})), normalize(data.get("libraries",{}))


def _allowed_hostnames(values: list[str] | str | None) -> set[str]:
    if values is None:
        values = ["127.0.0.1", "localhost", "testserver"]
    elif isinstance(values, str):
        values = values.split(",")
    hosts = set()
    for raw in values:
        if not isinstance(raw, str) or not raw.strip():
            continue
        value = raw.strip().lower().rstrip(".")
        if value.startswith("[") and value.endswith("]"):
            value = value[1:-1]
            if ":" not in value:
                raise ValueError("bracketed allowed_hosts values must be IPv6 addresses")
        elif ":" in value or "/" in value or "*" in value:
            raise ValueError("allowed_hosts must contain exact hostnames without ports or wildcards")
        hosts.add(value)
    if not hosts:
        raise ValueError("allowed_hosts must contain at least one hostname")
    return hosts


def create_app(workspace: str | Path, *, static_dir: str | Path | None = None, token: str | None = None,
               library_workspace: str | Path | None = None, desktop_shutdown=None,
               mcp_python: str | Path | None = None,
               registered_workspaces: dict | None = None, registered_libraries: dict | None = None,
               profile: str = "research", allowed_hosts: list[str] | str | None = None) -> FastAPI:
    if profile != "research":
        raise ValueError("the mutable research application only supports profile='research'; use demo_app for demo")
    hostnames = _allowed_hostnames(allowed_hosts)
    root = Path(workspace).resolve()
    root.mkdir(parents=True, exist_ok=True)
    help_library = HelpLibrary()
    registry_path = root / "gui-workspace-registry.json"
    workspace_data_root = root / "gui-workspaces"
    library_data_root = root / "gui-libraries"

    def read_runtime_registry():
        if not registry_path.exists():
            return {"schema_version": "1", "workspaces": {}, "libraries": {}, "idempotency": {}}
        try:
            value = json.loads(registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("runtime workspace registry is unreadable") from exc
        if not isinstance(value, dict) or value.get("schema_version") != "1":
            raise ValueError("runtime workspace registry has an unsupported schema")
        for key in ("workspaces", "libraries", "idempotency"):
            if not isinstance(value.get(key, {}), dict):
                raise ValueError("runtime workspace registry is malformed")
            value.setdefault(key, {})
        return value

    def write_runtime_registry(value):
        temp = registry_path.with_suffix(".tmp")
        try:
            temp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
            os.replace(temp, registry_path)
        finally:
            if temp.exists():
                temp.unlink()

    runtime_registry = read_runtime_registry()
    workspaces = {"default": {"name": "Default workspace", "path": root}}
    for ident, value in (registered_workspaces or {}).items():
        record = value if isinstance(value, dict) else {"path": value}
        path = Path(record["path"]).resolve()
        path.mkdir(parents=True, exist_ok=True)
        workspaces[str(ident)] = {**record, "path": path, "name": record.get("name", str(ident))}
    default_library_root = Path(library_workspace).resolve() if library_workspace else root
    legacy_rag_present = (default_library_root / "rag.sqlite").is_file()
    libraries = {"default": {"name": "Default library", "path": default_library_root, "workspace_ids": ["default"], "collections": {}, "runtime_empty": not legacy_rag_present, "read_only": bool(library_workspace and Path(library_workspace).resolve() != root)}}
    for ident, value in (registered_libraries or {}).items():
        record = value if isinstance(value, dict) else {"path": value}
        libpath = Path(record["path"]).resolve()
        libraries[str(ident)] = {**record, "path": libpath, "name": record.get("name", str(ident)), "workspace_ids": list(record.get("workspace_ids", workspaces.keys())), "collections": record.get("collections", {}), "runtime_created": False}
    for ident, record in runtime_registry["workspaces"].items():
        if not re.fullmatch(r"ws-[0-9a-f]{32}", ident) or ident in workspaces:
            raise ValueError("runtime workspace ID conflicts with trusted registration")
        if not isinstance(record, dict) or not isinstance(record.get("name"), str) or not isinstance(record.get("default_library_id"), str):
            raise ValueError("runtime workspace registry is malformed")
        path = (workspace_data_root / ident).resolve()
        if path.parent != workspace_data_root.resolve() or not path.is_dir():
            raise ValueError("runtime workspace directory is unavailable")
        workspaces[ident] = {"name": record["name"], "description": record.get("description", ""),
                             "default_library_id": record["default_library_id"], "path": path}
    for ident, record in runtime_registry["libraries"].items():
        if not re.fullmatch(r"lib-[0-9a-f]{32}", ident) or ident in libraries:
            raise ValueError("runtime library ID conflicts with trusted registration")
        if not isinstance(record, dict) or not isinstance(record.get("name"), str) or not isinstance(record.get("workspace_ids"), list):
            raise ValueError("runtime workspace registry is malformed")
        path = (library_data_root / ident).resolve()
        if path.parent != library_data_root.resolve() or not path.is_dir():
            raise ValueError("runtime library directory is unavailable")
        libraries[ident] = {"name": record["name"], "path": path, "workspace_ids": list(record["workspace_ids"]),
                            "collections": {}, "runtime_empty": True, "runtime_created": True}
    for wid, record in runtime_registry["workspaces"].items():
        reference_id = record.get("reference_library_id")
        if reference_id:
            if reference_id not in libraries:
                raise ValueError("runtime workspace references an unknown library")
            libraries[reference_id]["workspace_ids"] = list(dict.fromkeys([*libraries[reference_id]["workspace_ids"], wid]))
            libraries[reference_id].setdefault("read_only_workspace_ids", []).append(wid)
    default_library_for = {wid: next((lid for lid, lib in libraries.items() if wid in lib["workspace_ids"]), None) for wid in workspaces}
    for wid, record in workspaces.items():
        declared = record.get("default_library_id")
        if declared:
            default_library_for[wid] = declared
        if not default_library_for[wid] or default_library_for[wid] not in libraries or wid not in libraries[default_library_for[wid]]["workspace_ids"]:
            raise ValueError(f"workspace {wid!r} has no registered library")
    current_workspace_id = contextvars.ContextVar("gui_workspace_id", default="default")
    current_library_id = contextvars.ContextVar("gui_library_id", default="default")
    current_collection_id = contextvars.ContextVar("gui_collection_id", default="all")
    def active_workspace_id(): return current_workspace_id.get()
    def active_library_id(): return current_library_id.get()
    def active_collection_id(): return current_collection_id.get()
    def active_root(): return workspaces[active_workspace_id()]["path"]
    def active_library_root(): return libraries[active_library_id()]["path"]
    session_model_keys: dict[tuple[str, str], str] = {}
    session_source_keys: dict[tuple[str, str], str] = {}
    rag_search_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gui-rag-search")
    rag_searcher = OrderedDict()
    def search_rag(lib_id: str, lib_path: Path, query: str, top_k: int, filters: dict):
        key = (lib_id, str(lib_path))
        if key not in rag_searcher:
            rag_searcher[key] = RagLibrary(lib_path, read_only=True)
        rag_searcher.move_to_end(key)
        while len(rag_searcher) > 4:
            _, old = rag_searcher.popitem(last=False)
            old.close()
        return rag_searcher[key].search_evidence(query, top_k=top_k, filters=filters)
    def close_rag():
        for rag in rag_searcher.values(): rag.close()
        rag_searcher.clear()
    secret = token or secrets.token_urlsafe(32)
    @asynccontextmanager
    async def lifespan(_app):
        nonlocal queue_enabled
        try:
            yield
        finally:
            rag_search_executor.submit(close_rag).result()
            rag_search_executor.shutdown(wait=True)
            for db in [*event_dbs.values(), *replay_dbs.values()]: db.close()
            for db in context_dbs.values(): db.close()
            for db in conversation_dbs.values(): db.close()
            with queue_lock: queue_enabled=False
            if queue_thread is not None and queue_thread.is_alive(): queue_thread.join(timeout=5)
            if queue_thread is None or not queue_thread.is_alive():
                with queue_lock: queue_db.close()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    control_clients: dict[str, dict] = {}
    lock = threading.RLock()
    replay_lock = threading.RLock()
    registry_lock = threading.RLock()
    active_write_lock = threading.Lock()
    replay_dbs = {}
    event_dbs = {}
    conversation_dbs = {}
    stopped_reply_conversations: set[str] = set()
    queue_lock = threading.RLock()
    queue_db = sqlite3.connect(root / "gui-command-queue.sqlite", check_same_thread=False, timeout=10)
    queue_db.execute("PRAGMA busy_timeout=10000")
    queue_db.row_factory = sqlite3.Row
    queue_db.execute("""CREATE TABLE IF NOT EXISTS commands(
        command_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, library_id TEXT NOT NULL,
        collection_id TEXT NOT NULL, run_id TEXT NOT NULL, operation TEXT NOT NULL,
        params TEXT NOT NULL, idempotency_key TEXT NOT NULL, digest TEXT NOT NULL,
        status TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
        error_code TEXT, error_message TEXT, eligible INTEGER NOT NULL DEFAULT 1, manual_reviewed INTEGER NOT NULL DEFAULT 0,
        request_digest TEXT, precondition_json TEXT, result_json TEXT,
        UNIQUE(workspace_id,idempotency_key))""")
    queue_columns={row[1] for row in queue_db.execute("PRAGMA table_info(commands)")}
    if "eligible" not in queue_columns: queue_db.execute("ALTER TABLE commands ADD COLUMN eligible INTEGER NOT NULL DEFAULT 1")
    if "manual_reviewed" not in queue_columns: queue_db.execute("ALTER TABLE commands ADD COLUMN manual_reviewed INTEGER NOT NULL DEFAULT 0")
    for column, declaration in (("request_digest", "TEXT"), ("precondition_json", "TEXT"), ("result_json", "TEXT")):
        if column not in queue_columns: queue_db.execute(f"ALTER TABLE commands ADD COLUMN {column} {declaration}")
    queue_db.execute("CREATE INDEX IF NOT EXISTS gui_commands_order ON commands(status,created)")
    queue_db.execute("""CREATE TABLE IF NOT EXISTS queue_replays(
        workspace_id TEXT NOT NULL,idempotency_key TEXT NOT NULL,request_digest TEXT NOT NULL,
        command_id TEXT NOT NULL,result_json TEXT NOT NULL,created REAL NOT NULL,
        PRIMARY KEY(workspace_id,idempotency_key))""")
    queue_db.execute("""CREATE TABLE IF NOT EXISTS stop_intents(
        command_id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,library_id TEXT NOT NULL,collection_id TEXT NOT NULL,
        run_id TEXT NOT NULL,idempotency_key TEXT NOT NULL,digest TEXT NOT NULL,status TEXT NOT NULL,
        created REAL NOT NULL,updated REAL NOT NULL,error_code TEXT,error_message TEXT,
        UNIQUE(workspace_id,idempotency_key))""")
    queue_db.execute("UPDATE commands SET status='needs_review',error_code='RH_GUI_RESTART_REVIEW',error_message='Execution was interrupted; inspect the run before deciding whether to resume.' WHERE status='running'")
    queue_db.execute("UPDATE stop_intents SET status='queued',error_code=NULL,error_message=NULL WHERE status='running'")
    queue_db.execute("UPDATE commands SET eligible=0 WHERE status='queued'")
    queue_db.commit()
    queue_enabled = False
    queue_thread = None
    def database(cache, filename):
        path = active_root() / filename
        key = str(path)
        if key not in cache:
            cache[key] = sqlite3.connect(path, check_same_thread=False)
        return cache[key]
    def replay_db():
        db=database(replay_dbs,"gui-idempotency.sqlite")
        db.execute("CREATE TABLE IF NOT EXISTS writes(key TEXT PRIMARY KEY, digest TEXT NOT NULL, result TEXT NOT NULL)")
        return db
    def event_db():
        db=database(event_dbs,"gui-events.sqlite")
        db.execute("CREATE TABLE IF NOT EXISTS observations(seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, type TEXT NOT NULL, time REAL NOT NULL, payload TEXT NOT NULL, fingerprint TEXT NOT NULL)")
        db.execute("CREATE INDEX IF NOT EXISTS observations_run_seq ON observations(run_id,seq)")
        return db

    def conversation_db():
        path = active_root() / "gui-conversations.sqlite"
        key = str(path)
        if key not in conversation_dbs:
            conversation_dbs[key] = ConversationStore(active_root())
        return conversation_dbs[key]

    def observe(run_id, snapshot):
        payload = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",",":"))
        fingerprint = hashlib.sha256(payload.encode()).hexdigest()
        with lock:
            db=event_db()
            prior = db.execute("SELECT fingerprint FROM observations WHERE run_id=? ORDER BY seq DESC LIMIT 1", (run_id,)).fetchone()
            if not prior or prior[0] != fingerprint:
                db.execute("INSERT INTO observations(run_id,type,time,payload,fingerprint) VALUES (?,?,?,?,?)", (run_id,"status_snapshot",time.time(),payload,fingerprint))
                db.commit()

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        detail=str(exc.detail)
        code,message=(detail.split(":",1)[0],detail.split(":",1)[1]) if detail.startswith("RH_") and ":" in detail else ("RH_GUI_HTTP",detail)
        return JSONResponse({"schema_version":"1","code":code,"message":message,"retryable":exc.status_code == 409,"request_id":uuid.uuid4().hex}, status_code=exc.status_code)

    @contextmanager
    def service():
        with lock:
            with InvestigationService(active_root()) as instance:
                yield instance

    def scripted_result(task):
        """Deterministic fixture executor for offline W3 acceptance only."""
        role, payload = task["role"], task["payload"]
        if role == "planning":
            return {"search_plan": {"queries": [{"query_id": "paper-query", "source": "synthetic-paper", "query": "synthetic crosslinking membrane", "input_refs": [], "parent_query_id": None}, {"query_id": "patent-query", "source": "synthetic-patent", "query": "synthetic crosslinked polymer", "input_refs": [], "parent_query_id": None}]}}
        if role in ("paper_search", "patent_search"):
            return {"candidates": [{"document_id": item["document_id"], "relevance": "relevant", "reason": "matches synthetic fixture"} for item in payload["candidates"]]}
        if role == "evidence_analysis":
            return {"findings": [{"finding_id": "f0", "finding": "Synthetic fixture evidence was extracted.", "evidence_ids": [payload["evidence"][0]["evidence_id"]], "value": None, "unit": None, "conditions": None}]}
        if role == "business_judgment":
            return {"judgments": [{"document_id": item["document_id"], "relevance": "relevant", "human_review_required": False, "reason": "synthetic fixture scope"} for item in payload["documents"]]}
        if role == "synthesis":
            evidence = payload["evidence"][0]
            return {"claims": [{"claim_id": "c0", "claim": evidence["text"], "finding_refs": [0], "evidence_refs": [evidence["evidence_id"]], "quote": evidence["text"], "document_id": evidence["document_id"], "version_id": evidence["version_id"]}]}
        if role == "writing":
            return {"sections": [{"deliverable_type": kind, "language": "en", "section_id": kind, "title": "Synthetic fixture result", "body": "The supplied synthetic fixture evidence supports the route.", "claim_ids": ["c0"]} for kind in ("technical_report", "literature_review")]}
        return {"verification": {"status": "supported", "conclusion": "Supported by normalized synthetic fixture evidence.", "supported_claim_refs": [0]}}

    def load_scripted_fixture(fixture_id: str, question: str):
        if fixture_id != "synthetic-d19":
            raise HTTPException(400, "RH_GUI_SCRIPTED_FIXTURE: selected scripted fixture is not available")
        base = resources.files("research_harness").joinpath("examples", "investigation")
        try:
            spec = json.loads(base.joinpath("synthetic-spec.json").read_text(encoding="utf-8"))
            runtime = json.loads(base.joinpath("synthetic-runtime.json").read_text(encoding="utf-8"))
            scenario = json.loads(base.joinpath("synthetic-scenario.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(500, "RH_GUI_SCRIPTED_FIXTURE: bundled synthetic fixture is unavailable") from exc
        spec["research_question"] = question.strip()
        return spec, runtime, scenario

    def run_scripted_fixture(svc, run_id, conversation_id=None):
        """Complete an existing host/synthetic run through the normal role protocol."""
        while True:
            if conversation_id and conversation_id in stopped_reply_conversations:
                raise InvestigationError("RH_GUI_REPLY_STOPPED", "conversation reply was stopped before the next tool action")
            state = svc.status(run_id)
            if state["status"] in {"completed", "partial", "failed", "stopped", "policy_blocked"}:
                if state["status"] in {"completed", "partial"}:
                    svc.export_report(run_id)
                return svc.status(run_id)
            for task in svc.get_pending_tasks(run_id):
                svc.submit_model_result(run_id, task["task_id"], scripted_result(task), task["task_version"])
            prior = (state["status"], state["stage"])
            svc.advance_investigation(run_id)
            current = svc.status(run_id)
            if (current["status"], current["stage"]) == prior and not svc.get_pending_tasks(run_id):
                raise InvestigationError("RH_GUI_SCRIPTED_STALLED", "scripted fixture execution made no progress")

    @contextmanager
    def model_key_for(runtime: dict):
        if runtime.get("mode") != "api":
            yield
            return
        config = runtime.get("model_api", {})
        provider = config.get("provider")
        env_name = MODEL_KEY_ENV.get(provider)
        if not env_name or config.get("api_key_env") != env_name:
            raise HTTPException(400, "GUI model provider configuration is invalid")
        key = session_model_keys.get((active_workspace_id(),provider))
        if not key:
            yield
            return
        previous = os.environ.get(env_name)
        os.environ[env_name] = key
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop(env_name, None)
            else:
                os.environ[env_name] = previous

    @contextmanager
    def source_keys_for():
        previous = {env_name: os.environ.get(env_name) for env_name in SOURCE_KEY_ENV.values()}
        try:
            for (workspace_id,name), value in session_source_keys.items():
                if workspace_id != active_workspace_id(): continue
                os.environ[SOURCE_KEY_ENV[name]] = value
            yield
        finally:
            for env_name, value in previous.items():
                if value is None:
                    os.environ.pop(env_name, None)
                else:
                    os.environ[env_name] = value

    @app.middleware("http")
    async def protect(request: Request, call_next):
        request_id = uuid.uuid4().hex
        host = request.headers.get("host", "")
        origin = request.headers.get("origin")
        try:
            request_host = (request.url.hostname or "").lower().rstrip(".")
            origin_url = urlsplit(origin) if origin else None
            origin_invalid = bool(origin and (origin_url.scheme not in {"http", "https"} or origin_url.netloc.lower() != host.lower() or origin_url.path or origin_url.query or origin_url.fragment or origin_url.username or origin_url.password))
        except ValueError:
            request_host, origin_invalid = "", True
        if request_host not in hostnames or origin_invalid:
            return JSONResponse({"schema_version":"1","code":"RH_GUI_ORIGIN","message":"origin is not allowed","retryable":False,"request_id":request_id}, status_code=403)
        protected_read = (request.url.path == "/api/v1/queue" or request.url.path.startswith("/api/v1/queue/")
                          or request.url.path.startswith("/api/v1/control/clients/"))
        if (request.method not in {"GET", "HEAD", "OPTIONS"} or protected_read) and not hmac.compare_digest(request.headers.get("x-session-token", ""), secret):
            return JSONResponse({"schema_version":"1","code":"RH_GUI_TOKEN","message":"session token is required","retryable":False,"request_id":request_id}, status_code=403)
        wid=request.headers.get("x-workspace-id", "default")
        if wid not in workspaces:
            return JSONResponse({"schema_version":"1","code":"RH_GUI_WORKSPACE_UNKNOWN","message":"workspace is not registered","retryable":False,"request_id":request_id},status_code=404)
        lid=request.headers.get("x-library-id") or default_library_for[wid]
        if lid not in libraries:
            return JSONResponse({"schema_version":"1","code":"RH_GUI_LIBRARY_UNKNOWN","message":"library is not registered","retryable":False,"request_id":request_id},status_code=404)
        if wid not in libraries[lid]["workspace_ids"]:
            return JSONResponse({"schema_version":"1","code":"RH_GUI_LIBRARY_SCOPE","message":"library is not associated with this workspace","retryable":False,"request_id":request_id},status_code=403)
        collection=request.headers.get("x-collection-id", "all")
        collections=libraries[lid]["collections"]
        if collection!="all" and collection not in collections:
            return JSONResponse({"schema_version":"1","code":"RH_GUI_COLLECTION_UNKNOWN","message":"collection is not registered for this library","retryable":False,"request_id":request_id},status_code=404)
        tokens=(current_workspace_id.set(wid),current_library_id.set(lid),current_collection_id.set(collection))
        try:
            return await call_next(request)
        except Exception as exc:
            code = getattr(exc, "code", "RH_GUI_ERROR")
            status = 404 if "NOT_FOUND" in code else 409 if "CONFLICT" in code or "BUSY" in code else 400
            return JSONResponse({"schema_version":"1","code":code,"message":str(getattr(exc, "message", "request failed")),"retryable":status == 409,"request_id":request_id}, status_code=status)
        finally:
            current_workspace_id.reset(tokens[0]); current_library_id.reset(tokens[1]); current_collection_id.reset(tokens[2])

    def pack(value):
        return {"schema_version":"1", "context":{"workspace_id":active_workspace_id(),"library_id":active_library_id(),"collection_id":active_collection_id()}, **value}

    def library_status(item):
        path = item["path"]
        if (path / "rag.sqlite").is_file():
            return "ready" if (path / "qdrant").is_dir() else "unavailable"
        if local_library.has_index(path):
            db = sqlite3.connect(f"file:{(path / local_library.DB_NAME).as_posix()}?mode=ro", uri=True)
            try:
                if db.execute("SELECT COUNT(*) FROM documents").fetchone()[0]:
                    return "basic"
            finally:
                db.close()
        return "unindexed"

    def library_public(ident, item, workspace_id):
        return {"library_id": ident, "name": item["name"],
                "read_only": bool(item.get("read_only", not item.get("runtime_empty", False)) or (item["path"] / "rag.sqlite").is_file() or workspace_id in item.get("read_only_workspace_ids", [])),
                "index_status": library_status(item)}

    def workspace_public(ident):
        item = workspaces[ident]
        default_id = default_library_for[ident]
        return {"workspace_id": ident, "name": item["name"], "description": item.get("description", ""),
                "default_library_id": default_id,
                "libraries": [library_public(lid, library, ident) for lid, library in libraries.items() if ident in library["workspace_ids"]],
                "status": "ready"}

    def queue_public(row):
        return {"command_id":row["command_id"],"workspace_id":row["workspace_id"],"library_id":row["library_id"],"collection_id":row["collection_id"],"run_id":row["run_id"],
                "operation":row["operation"],"status":row["status"],"created_at":row["created"],
                "waiting_reason":row["error_message"],"error_code":row["error_code"],"requires_resume":row["status"]=="queued" and not row["eligible"],"manual_reviewed":bool(row["manual_reviewed"])}

    def run_precondition(wid, run_id, db=None):
        """Compact identity of persisted core state; excludes source text and credentials."""
        owned = db is None
        if owned:
            path = workspaces[wid]["path"] / "investigation.sqlite"
            if not path.exists(): return None
            db = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=0.2)
            db.row_factory = sqlite3.Row
        try:
            run = db.execute("SELECT id,status,stage,budget,result FROM investigations WHERE id=?", (run_id,)).fetchone()
            if not run: return None
            tasks = db.execute("SELECT id,task_version,role,task_type,status,result_hash FROM model_tasks WHERE run_id=? ORDER BY id", (run_id,)).fetchall()
            calls = db.execute("SELECT id,task_id,task_version,status,usage FROM model_api_calls WHERE run_id=? ORDER BY id", (run_id,)).fetchall()
            value = {"run_id":run["id"],"status":run["status"],"stage":run["stage"],
                     "budget_hash":hashlib.sha256((run["budget"] or "").encode()).hexdigest(),
                     "result_hash":hashlib.sha256((run["result"] or "").encode()).hexdigest(),
                     "tasks":[list(row) for row in tasks],
                     "calls":[[row["id"],row["task_id"],row["task_version"],row["status"],hashlib.sha256((row["usage"] or "").encode()).hexdigest()] for row in calls]}
            return json.dumps(value, sort_keys=True, separators=(",", ":"))
        finally:
            if owned: db.close()

    def workspace_lock_is_free(wid):
        try:
            with InvestigationService(workspaces[wid]["path"]):
                return True
        except InvestigationError as exc:
            if getattr(exc, "code", None) == "RH_WORKSPACE_BUSY": return False
            raise

    def queue_items(wid):
        with queue_lock:
            rows=queue_db.execute("SELECT * FROM commands WHERE workspace_id=? AND (status IN ('queued','running','waiting_credentials','waiting_external_lock','needs_review') OR command_id IN (SELECT command_id FROM commands WHERE workspace_id=? AND status IN ('completed','failed','cancelled') ORDER BY created DESC LIMIT 50))",(wid,wid)).fetchall()
            rows=[*rows,*queue_db.execute("SELECT command_id,workspace_id,library_id,collection_id,run_id,'stop' AS operation,'{}' AS params,idempotency_key,digest,status,created,updated,error_code,error_message,1 AS eligible,0 AS manual_reviewed FROM stop_intents WHERE workspace_id=? AND (status IN ('queued','running') OR command_id IN (SELECT command_id FROM stop_intents WHERE workspace_id=? AND status IN ('completed','failed','cancelled') ORDER BY created DESC LIMIT 50))",(wid,wid)).fetchall()]
            rows.sort(key=lambda row:(row["created"],row["command_id"]))
            active=queue_db.execute("SELECT command_id,workspace_id,run_id FROM commands WHERE status='running' UNION ALL SELECT command_id,workspace_id,run_id FROM stop_intents WHERE status='running' LIMIT 1").fetchone()
            queued=queue_db.execute("SELECT command_id FROM (SELECT command_id,created,CASE operation WHEN 'stop' THEN 0 ELSE 1 END AS priority FROM commands WHERE status='queued' UNION ALL SELECT command_id,created,0 AS priority FROM stop_intents WHERE status='queued') ORDER BY priority,created").fetchall()
        positions={row[0]:index for index,row in enumerate(queued,1)}
        items=[]
        for row in rows:
            item=queue_public(row)
            item["position"]=positions.get(row["command_id"],0)
            item["active"]=bool(active and active[0]==row["command_id"])
            items.append(item)
        return items

    def enqueue(operation, run_id, params, key, request_digest=None):
        if operation not in {"advance","model-step","resume","export","conversation-scripted","conversation-api"} or not isinstance(run_id,str) or not re.fullmatch(r"inv-[0-9a-f]{12}",run_id):
            raise HTTPException(400,"RH_GUI_QUEUE_ARGUMENT:queued operation or run identity is invalid")
        if not isinstance(key,str) or not 1<=len(key)<=4096:
            raise HTTPException(400,"RH_GUI_QUEUE_ARGUMENT:idempotency key is invalid")
        wid,lid,cid=active_workspace_id(),active_library_id(),active_collection_id()
        safe_params={k:v for k,v in params.items() if k in {"languages","conversation_id"} and v is not None}
        if "languages" in safe_params and (not isinstance(safe_params["languages"],list) or len(safe_params["languages"])>10 or any(not isinstance(v,str) or len(v)>32 for v in safe_params["languages"])):
            raise HTTPException(400,"RH_GUI_QUEUE_ARGUMENT:export language parameters are invalid")
        key_digest=hashlib.sha256(key.encode("utf-8")).hexdigest()
        digest=hashlib.sha256(json.dumps([wid,lid,cid,run_id,operation,safe_params],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        try:
            precondition=run_precondition(wid,run_id)
        except sqlite3.Error:
            precondition=None
        with queue_lock:
            prior=queue_db.execute("SELECT * FROM commands WHERE workspace_id=? AND idempotency_key=?",(wid,key_digest)).fetchone()
            if prior:
                if prior["digest"]!=digest or (prior["request_digest"] and request_digest and prior["request_digest"]!=request_digest): raise HTTPException(409,"RH_GUI_IDEMPOTENCY_CONFLICT:idempotency key conflict")
                return queue_public(prior)
            count=queue_db.execute("SELECT count(*) FROM commands WHERE status IN ('queued','running','waiting_credentials','waiting_external_lock','needs_review')").fetchone()[0]
            if count>=100: raise HTTPException(429,"RH_GUI_QUEUE_FULL:command queue is full")
            ident=uuid.uuid4().hex; now=time.time()
            status="queued" if precondition is not None else "needs_review"
            code=None if precondition is not None else "RH_GUI_PRECONDITION_UNAVAILABLE"
            message=None if precondition is not None else "Core run state could not be verified; inspect before resuming."
            queue_db.execute("INSERT INTO commands(command_id,workspace_id,library_id,collection_id,run_id,operation,params,idempotency_key,digest,status,created,updated,error_code,error_message,eligible,manual_reviewed,request_digest,precondition_json,result_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,0,?,?,NULL)",(ident,wid,lid,cid,run_id,operation,json.dumps(safe_params),key_digest,digest,status,now,now,code,message,request_digest,precondition))
            queue_db.commit()
            return queue_public(queue_db.execute("SELECT * FROM commands WHERE command_id=?",(ident,)).fetchone())

    def enqueue_stop_intent(run_id,key):
        if not isinstance(run_id,str) or not re.fullmatch(r"inv-[0-9a-f]{12}",run_id) or not isinstance(key,str) or not 1<=len(key)<=4096:
            raise HTTPException(400,"RH_GUI_QUEUE_ARGUMENT:stop identity or idempotency key is invalid")
        wid,lid,cid=active_workspace_id(),active_library_id(),active_collection_id()
        key_digest=hashlib.sha256(key.encode("utf-8")).hexdigest()
        digest=hashlib.sha256(json.dumps([wid,lid,cid,run_id,"stop"],ensure_ascii=False).encode()).hexdigest()
        with queue_lock:
            prior=queue_db.execute("SELECT * FROM stop_intents WHERE workspace_id=? AND idempotency_key=?",(wid,key_digest)).fetchone()
            if prior:
                if prior["digest"]!=digest: raise HTTPException(409,"RH_GUI_IDEMPOTENCY_CONFLICT:idempotency key conflict")
                return {"command_id":prior["command_id"],"workspace_id":wid,"library_id":lid,"collection_id":cid,"run_id":run_id,"operation":"stop","status":prior["status"],"created_at":prior["created"],"waiting_reason":prior["error_message"],"error_code":prior["error_code"]}
            ident=uuid.uuid4().hex; now=time.time()
            queue_db.execute("INSERT INTO stop_intents VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",(ident,wid,lid,cid,run_id,key_digest,digest,"queued",now,now,None,None)); queue_db.commit()
            return {"command_id":ident,"workspace_id":wid,"library_id":lid,"collection_id":cid,"run_id":run_id,"operation":"stop","status":"queued","created_at":now,"waiting_reason":None,"error_code":None}

    def queued_dispatch(row):
        wid,lid,cid=row["workspace_id"],row["library_id"],row["collection_id"]
        tokens=(current_workspace_id.set(wid),current_library_id.set(lid),current_collection_id.set(cid))
        try:
            op,run_id,params=row["operation"],row["run_id"],json.loads(row["params"])
            with service() as svc:
                before=run_precondition(wid,run_id,svc.db) if op!="stop" else None
                if op!="stop" and (not row["precondition_json"] or before != row["precondition_json"]):
                    raise InvestigationError("RH_GUI_PRECONDITION_CHANGED", "Core run state changed since this command was queued; review is required.")
                if op=="advance":
                    with source_keys_for(): return svc.advance_investigation(run_id)
                if op=="resume": return svc.resume_investigation(run_id)
                if op=="stop": return svc.request_stop(run_id)
                if op=="export":
                    result=svc.export_report(run_id,params.get("languages"))
                    return {"artifacts":[{**item,"artifact_id":hashlib.sha256((run_id+":"+item["path"]).encode()).hexdigest(),"name":Path(item["path"]).name,"path":None} for item in result["artifacts"]]}
                if op=="model-step":
                    runtime=json.loads(svc._run(run_id)["runtime"])
                    provider=runtime.get("model_api",{}).get("provider"); env=MODEL_KEY_ENV.get(provider)
                    if runtime.get("mode")=="api" and not session_model_keys.get((wid,provider)) and not os.environ.get(env or ""):
                        raise InvestigationError("RH_GUI_WAITING_CREDENTIALS","This workspace needs its configured model credential before the command can run.")
                    with model_key_for(runtime):
                        with source_keys_for():
                            pending=svc.get_pending_tasks(run_id)
                            if pending: run_model_task(svc,run_id,pending[0])
                            else: svc.advance_investigation(run_id)
                    return svc.status(run_id)
                if op=="conversation-scripted":
                    runtime=json.loads(svc._run(run_id)["runtime"])
                    if runtime.get("mode") != "host" or runtime.get("data_mode") != "synthetic":
                        raise InvestigationError("RH_GUI_SCRIPTED_RUNTIME", "scripted executor requires a host synthetic runtime")
                    return run_scripted_fixture(svc, run_id, params.get("conversation_id"))
                if op=="conversation-api":
                    runtime=json.loads(svc._run(run_id)["runtime"])
                    if runtime.get("mode") != "api":
                        raise InvestigationError("RH_GUI_API_RUNTIME", "API executor requires an API runtime")
                    provider=runtime.get("model_api",{}).get("provider"); env=MODEL_KEY_ENV.get(provider)
                    if not session_model_keys.get((wid,provider)) and not os.environ.get(env or ""):
                        raise InvestigationError("RH_GUI_WAITING_CREDENTIALS","This workspace needs its configured model credential before the command can run.")
                    with model_key_for(runtime):
                        with source_keys_for():
                            pending=svc.get_pending_tasks(run_id)
                            if pending: run_model_task(svc,run_id,pending[0])
                            else: svc.advance_investigation(run_id)
                    return svc.status(run_id)
            raise InvestigationError("RH_GUI_QUEUE_OPERATION","Unsupported queued operation")
        finally:
            current_workspace_id.reset(tokens[0]); current_library_id.reset(tokens[1]); current_collection_id.reset(tokens[2])

    def complete_queue_replay(row, result):
        with queue_lock:
            queue_db.execute("BEGIN IMMEDIATE")
            prior=queue_db.execute("SELECT request_digest,result_json FROM queue_replays WHERE workspace_id=? AND idempotency_key=?",(row["workspace_id"],row["idempotency_key"])).fetchone()
            if prior and prior[0]!=row["request_digest"]:
                queue_db.rollback()
                raise HTTPException(409,"RH_GUI_IDEMPOTENCY_CONFLICT:idempotency key conflict")
            if prior: result=json.loads(prior[1])
            else:
                queue_db.execute("INSERT INTO queue_replays VALUES (?,?,?,?,?,?)",(row["workspace_id"],row["idempotency_key"],row["request_digest"],row["command_id"],json.dumps(result,ensure_ascii=False),time.time()))
            queue_db.execute("UPDATE commands SET status='completed',result_json=?,updated=?,error_code=NULL,error_message=NULL WHERE command_id=?",(json.dumps(result,ensure_ascii=False),time.time(),row["command_id"]))
            queue_db.commit()
            return result

    def queue_worker_loop():
        nonlocal queue_enabled
        while True:
            with queue_lock:
                if not queue_enabled: return
                if not queue_db.execute("SELECT 1 FROM stop_intents WHERE status='queued' LIMIT 1").fetchone() and queue_db.execute("SELECT 1 FROM commands WHERE status='queued' AND eligible=0 LIMIT 1").fetchone():
                    queue_enabled=False; return
                if not queue_db.execute("SELECT 1 FROM stop_intents WHERE status='queued' LIMIT 1").fetchone() and not queue_db.execute("SELECT 1 FROM commands WHERE status='queued' AND eligible=1 LIMIT 1").fetchone():
                    queue_enabled=False; return
            active_write_lock.acquire()
            try:
                with queue_lock:
                    stop_row=queue_db.execute("SELECT command_id,workspace_id,library_id,collection_id,run_id,'stop' AS operation,'{}' AS params,idempotency_key,digest,status,created,updated,error_code,error_message FROM stop_intents WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
                    if stop_row:
                        row=stop_row; is_stop=True
                        queue_db.execute("UPDATE stop_intents SET status='running',updated=? WHERE command_id=?",(time.time(),row["command_id"]))
                    else:
                        if queue_db.execute("SELECT 1 FROM commands WHERE status='queued' AND eligible=0 LIMIT 1").fetchone(): continue
                        row=queue_db.execute("SELECT * FROM commands WHERE status='queued' AND eligible=1 ORDER BY created LIMIT 1").fetchone()
                        if not row: continue
                        is_stop=False
                        queue_db.execute("UPDATE commands SET status='running',updated=? WHERE command_id=?",(time.time(),row["command_id"]))
                    queue_db.commit()
                try:
                    wid,lid,cid=row["workspace_id"],row["library_id"],row["collection_id"]
                    tokens=(current_workspace_id.set(wid),current_library_id.set(lid),current_collection_id.set(cid))
                    try:
                        if is_stop:
                            queued_dispatch(row)
                        else:
                            with queue_lock:
                                replay=queue_db.execute("SELECT request_digest,result_json FROM queue_replays WHERE workspace_id=? AND idempotency_key=?",(wid,row["idempotency_key"])).fetchone()
                            if replay and replay[0] == row["request_digest"]:
                                packed=json.loads(replay[1])
                                with queue_lock:
                                    queue_db.execute("UPDATE commands SET status='completed',result_json=?,updated=? WHERE command_id=?",(json.dumps(packed,ensure_ascii=False),time.time(),row["command_id"])); queue_db.commit()
                            else:
                                dispatched=queued_dispatch(row)
                                packed=pack(dispatched)
                                complete_queue_replay(row,packed)
                    finally:
                        current_workspace_id.reset(tokens[0]); current_library_id.reset(tokens[1]); current_collection_id.reset(tokens[2])
                    status,code,message="completed",None,None
                except Exception as error:
                    code=getattr(error,"code",None) or (str(error).split(":",1)[0] if str(error).startswith("RH_") else "RH_GUI_QUEUE_FAILED")
                    status="waiting_credentials" if code=="RH_GUI_WAITING_CREDENTIALS" else "waiting_external_lock" if code=="RH_WORKSPACE_BUSY" else "needs_review" if code in {"RH_GUI_PRECONDITION_CHANGED","RH_GUI_IDEMPOTENCY_CONFLICT"} else "failed"
                    message="This workspace needs its configured model credential before the command can run." if status=="waiting_credentials" else "Another process owns this workspace; resume after it releases the lock." if status=="waiting_external_lock" else "Command failed; inspect the run details before retrying."
                with queue_lock:
                    table="stop_intents" if is_stop else "commands"
                    if not (not is_stop and status=="completed"):
                        queue_db.execute(f"UPDATE {table} SET status=?,updated=?,error_code=?,error_message=? WHERE command_id=?",(status,time.time(),code,message,row["command_id"])); queue_db.commit()
            finally:
                active_write_lock.release()

    def start_queue_worker():
        nonlocal queue_enabled,queue_thread
        with queue_lock:
            was_enabled=queue_enabled
            queue_enabled=True
            if not was_enabled or queue_thread is None or not queue_thread.is_alive():
                queue_thread=threading.Thread(target=queue_worker_loop,name="gui-command-queue",daemon=True); queue_thread.start()

    def write(key, body, action, queue_operation=None, run_id=None, queue_params=None):
        if not key:
            raise HTTPException(400, "idempotency_key required")
        scoped_body={"workspace_id":active_workspace_id(),"library_id":active_library_id(),"collection_id":active_collection_id(),"body":body}
        digest = hashlib.sha256(json.dumps(scoped_body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        scoped_key=active_workspace_id()+":"+key
        with replay_lock:
            db=replay_db(); prior=db.execute("SELECT digest,result FROM writes WHERE key=?",(scoped_key,)).fetchone()
            if prior:
                if prior[0]!=digest: raise HTTPException(409,"idempotency key conflict")
                return json.loads(prior[1])
        if queue_operation:
            with queue_lock:
                pending=queue_db.execute("SELECT 1 FROM commands WHERE status IN ('queued','running','waiting_credentials','waiting_external_lock','needs_review') UNION ALL SELECT 1 FROM stop_intents WHERE status IN ('queued','running') LIMIT 1").fetchone()
            wait_for_idle_result=not pending and not active_write_lock.locked()
            command=enqueue(queue_operation,run_id,queue_params or {},key,digest)
            with queue_lock:
                existing=queue_db.execute("SELECT * FROM commands WHERE command_id=?",(command["command_id"],)).fetchone()
                if existing and existing["request_digest"] and existing["request_digest"]!=digest:
                    raise HTTPException(409,"RH_GUI_IDEMPOTENCY_CONFLICT:idempotency key conflict")
                if existing and existing["result_json"]: return json.loads(existing["result_json"])
            if command["status"] == "queued": start_queue_worker()
            if wait_for_idle_result and command["status"] in {"queued","running"}:
                deadline=time.monotonic()+300
                while time.monotonic()<deadline:
                    with queue_lock:
                        finished=queue_db.execute("SELECT status,error_code,result_json FROM commands WHERE command_id=?",(command["command_id"],)).fetchone()
                    if finished and finished["status"] in {"completed","failed","needs_review","waiting_credentials","waiting_external_lock","cancelled"}:
                        if finished["status"]=="completed" and finished["result_json"]: return json.loads(finished["result_json"])
                        if finished["status"]=="failed": raise HTTPException(400,f"{finished['error_code'] or 'RH_GUI_QUEUE_FAILED'}:queued command failed")
                        return pack({"command_id":command["command_id"],"status":finished["status"],"queued":True})
                    time.sleep(.02)
            return pack({"command_id":command["command_id"],"status":command["status"],"queued":command["status"] in {"queued","running","waiting_credentials","waiting_external_lock"}})
        with queue_lock:
            pending=queue_db.execute("SELECT 1 FROM commands WHERE status IN ('queued','running','waiting_credentials','waiting_external_lock') UNION ALL SELECT 1 FROM stop_intents WHERE status IN ('queued','running') LIMIT 1").fetchone()
        acquired=active_write_lock.acquire(blocking=False)
        if queue_operation and (pending or not acquired):
            if acquired: active_write_lock.release()
            command=enqueue(queue_operation,run_id,queue_params or {},key,digest)
            if command["status"] == "queued": start_queue_worker()
            return pack({"command_id":command["command_id"],"status":command["status"],"queued":command["status"] in {"queued","running","waiting_credentials","waiting_external_lock"}})
        if not acquired:
            raise HTTPException(409, "RH_GUI_BUSY:another investigation write is active; retry shortly")
        try:
            with replay_lock:
                db=replay_db()
                prior = db.execute("SELECT digest,result FROM writes WHERE key=?", (scoped_key,)).fetchone()
                if prior:
                    if prior[0] != digest:
                        raise HTTPException(409, "idempotency key conflict")
                    return json.loads(prior[1])
            result = pack(action())
            with replay_lock:
                db=replay_db()
                db.execute("INSERT INTO writes VALUES (?,?,?)", (scoped_key,digest,json.dumps(result,ensure_ascii=False)))
                db.commit()
            if queue_operation:
                start_queue_worker()
            return result
        except Exception as error:
            code=getattr(error,"code",None)
            if queue_operation and code in {"RH_WORKSPACE_BUSY","RH_GUI_WAITING_CREDENTIALS"}:
                command=enqueue(queue_operation,run_id,queue_params or {},key,digest)
                status="waiting_external_lock" if code=="RH_WORKSPACE_BUSY" else "waiting_credentials"
                message=getattr(error,"message",None) or "Required local state is not available."
                with queue_lock:
                    queue_db.execute("UPDATE commands SET status=?,updated=?,error_code=?,error_message=? WHERE command_id=?",(status,time.time(),code,message,command["command_id"])); queue_db.commit()
                command.update({"status":status,"error_code":code,"waiting_reason":message})
                return pack({"command_id":command["command_id"],"status":status,"queued":True})
            raise
        finally:
            active_write_lock.release()

    def collection_ids():
        if active_collection_id()=="all": return None
        record=libraries[active_library_id()]["collections"][active_collection_id()]
        ids=record.get("document_ids", record.get("members", []))
        if isinstance(ids,dict): ids=list(ids)
        return list(ids)

    @app.get("/api/v1/queue")
    def command_queue():
        items=queue_items(active_workspace_id())
        active=next((item for item in items if item["active"]),None)
        with queue_lock: waiting_resume=bool(queue_db.execute("SELECT 1 FROM commands WHERE status='queued' AND eligible=0 LIMIT 1").fetchone())
        return pack({"items":items,"active_command_id":active["command_id"] if active else None,
                     "current_object":active["run_id"] if active and active["workspace_id"]==active_workspace_id() else None,
                     "global_busy":active_write_lock.locked(),
                     "global_waiting_resume":waiting_resume,
                     "queued_count":sum(item["status"] in {"queued","running","waiting_credentials","waiting_external_lock","needs_review"} for item in items)})

    @app.get("/api/v1/queue/{command_id}")
    def command_detail(command_id: str):
        with queue_lock: row=queue_db.execute("SELECT * FROM commands WHERE command_id=? AND workspace_id=?",(command_id,active_workspace_id())).fetchone()
        if not row:
            with queue_lock: row=queue_db.execute("SELECT command_id,workspace_id,library_id,collection_id,run_id,'stop' AS operation,'{}' AS params,idempotency_key,digest,status,created,updated,error_code,error_message,1 AS eligible,0 AS manual_reviewed FROM stop_intents WHERE command_id=? AND workspace_id=?",(command_id,active_workspace_id())).fetchone()
        if not row: raise HTTPException(404,"RH_GUI_COMMAND_NOT_FOUND:command is not available in this workspace")
        return pack(queue_public(row))

    @app.post("/api/v1/queue/{command_id}/cancel")
    def cancel_command(command_id: str):
        with queue_lock:
            row=queue_db.execute("SELECT * FROM commands WHERE command_id=? AND workspace_id=?",(command_id,active_workspace_id())).fetchone()
            table="commands"
            if not row:
                row=queue_db.execute("SELECT command_id,workspace_id,library_id,collection_id,run_id,'stop' AS operation,'{}' AS params,idempotency_key,digest,status,created,updated,error_code,error_message FROM stop_intents WHERE command_id=? AND workspace_id=?",(command_id,active_workspace_id())).fetchone()
                table="stop_intents"
            if not row: raise HTTPException(404,"RH_GUI_COMMAND_NOT_FOUND:command is not available in this workspace")
            if row["status"]!="queued": raise HTTPException(409,"RH_GUI_COMMAND_NOT_CANCELLABLE:only commands that have not started can be cancelled")
            queue_db.execute(f"UPDATE {table} SET status='cancelled',updated=? WHERE command_id=?",(time.time(),command_id)); queue_db.commit()
            if table=="commands": row=queue_db.execute("SELECT * FROM commands WHERE command_id=?",(command_id,)).fetchone()
            else: row=queue_db.execute("SELECT command_id,workspace_id,library_id,collection_id,run_id,'stop' AS operation,'{}' AS params,idempotency_key,digest,status,created,updated,error_code,error_message,1 AS eligible,0 AS manual_reviewed FROM stop_intents WHERE command_id=?",(command_id,)).fetchone()
        return pack(queue_public(row))

    @app.post("/api/v1/queue/resume")
    def resume_queue(body: dict):
        wid=active_workspace_id()
        if body.get("workspace_id") not in (None,wid): raise HTTPException(403,"RH_GUI_QUEUE_SCOPE:queue resume is workspace scoped")
        reviewed=body.get("reviewed_command_ids",[])
        if reviewed and (body.get("confirm_needs_review") is not True or not isinstance(reviewed,list) or len(reviewed)>100 or any(not isinstance(x,str) or not re.fullmatch(r"[0-9a-f]{32}",x) for x in reviewed)):
            raise HTTPException(400,"RH_GUI_REVIEW_CONFIRMATION:explicit confirmation is required for interrupted commands")
        if not workspace_lock_is_free(wid):
            raise HTTPException(409,"RH_GUI_RESUME_LOCKED:workspace lock is still held")
        candidates=[]
        with queue_lock:
            for row in queue_db.execute("SELECT * FROM commands WHERE workspace_id=? AND status IN ('queued','waiting_credentials','waiting_external_lock','needs_review')",(wid,)).fetchall():
                is_review=row["status"]=="needs_review"
                if is_review and row["command_id"] not in reviewed: continue
                candidates.append((row,is_review))
        for row,is_review in candidates:
            if row["status"]=="waiting_credentials":
                # Credential presence is checked again at dispatch, in this workspace only.
                pass
            now_state=run_precondition(wid,row["run_id"])
            if not row["precondition_json"] or now_state!=row["precondition_json"]:
                with queue_lock:
                    queue_db.execute("UPDATE commands SET status='needs_review',eligible=0,updated=?,error_code='RH_GUI_PRECONDITION_CHANGED',error_message='Core run state changed while waiting; inspect before retrying.' WHERE command_id=?",(time.time(),row["command_id"])); queue_db.commit()
                if is_review: raise HTTPException(409,"RH_GUI_PRECONDITION_CHANGED:core run state changed; command remains under review")
                continue
            # An already-recorded result is reconciled without dispatch.
            with queue_lock:
                replay=queue_db.execute("SELECT request_digest,result_json FROM queue_replays WHERE workspace_id=? AND idempotency_key=?",(wid,row["idempotency_key"])).fetchone()
            with queue_lock:
                if replay:
                    if replay[0]!=row["request_digest"]:
                        queue_db.execute("UPDATE commands SET status='needs_review',eligible=0,error_code='RH_GUI_IDEMPOTENCY_CONFLICT',error_message='Stored replay identity conflicts with this command.' WHERE command_id=?",(row["command_id"],)); queue_db.commit()
                        if is_review: raise HTTPException(409,"RH_GUI_IDEMPOTENCY_CONFLICT:stored replay identity conflicts")
                        continue
                    queue_db.execute("UPDATE commands SET status='completed',result_json=?,updated=?,error_code=NULL,error_message=NULL WHERE command_id=?",(replay[1],time.time(),row["command_id"]))
                else:
                    queue_db.execute("UPDATE commands SET status='queued',eligible=1,manual_reviewed=CASE WHEN ? THEN 1 ELSE manual_reviewed END,updated=?,error_code=NULL,error_message=NULL WHERE command_id=?",(int(is_review),time.time(),row["command_id"]))
                queue_db.commit()
        with queue_lock:
            queue_db.execute("UPDATE stop_intents SET status='queued',updated=?,error_code=NULL,error_message=NULL WHERE workspace_id=? AND status='waiting_external_lock'",(time.time(),wid))
            queue_db.commit()
            count=queue_db.execute("SELECT (SELECT count(*) FROM commands WHERE status='queued' AND workspace_id=?) + (SELECT count(*) FROM stop_intents WHERE status='queued' AND workspace_id=?)",(wid,wid)).fetchone()[0]
        start_queue_worker()
        return pack({"resumed":True,"queued_count":count})

    def validate_collection_members(document_ids):
        selected=collection_ids()
        if selected is not None and set(selected)-set(document_ids):
            raise HTTPException(409,"registered collection contains documents absent from its library")
        return selected

    def check_document_scope(document_id):
        ids=collection_ids()
        if ids is not None and document_id not in ids:
            raise HTTPException(404,"document is not in the selected collection")

    context_dbs={}
    def context_db():
        path=active_root()/"gui-contexts.sqlite"; key=str(path)
        if key not in context_dbs:
            db=sqlite3.connect(path,check_same_thread=False)
            db.execute("CREATE TABLE IF NOT EXISTS run_references(run_id TEXT PRIMARY KEY, snapshot TEXT NOT NULL)"); db.commit(); context_dbs[key]=db
        return context_dbs[key]

    def freeze_reference_snapshot(question):
        lib=libraries[active_library_id()]; libpath=lib["path"]
        if not (libpath/"rag.sqlite").is_file() and not (libpath/"qdrant").exists():
            selected=collection_ids()
            return local_library.reference_snapshot(libpath, workspace_id=active_workspace_id(), library_id=active_library_id(), collection_id=active_collection_id(), query=question, document_ids=set(selected) if selected is not None else None)
        if not (libpath/"rag.sqlite").is_file() or not (libpath/"qdrant").is_dir():
            raise HTTPException(409,"selected library index is unavailable; reference was not frozen")
        with RagLibrary(libpath,read_only=True) as rag:
            status=rag.get_library_status(); allowed=validate_collection_members([d["document_id"] for d in status["documents"]])
            documents=[]
            for row in status["documents"]:
                if allowed is not None and row["document_id"] not in allowed: continue
                doc=rag.get_document(row["document_id"])
                documents.append({"document_id":doc["document_id"],"current_version_id":doc.get("current_version_id"),"versions":[v["version_id"] for v in doc.get("versions",[])]})
            snapshot={"workspace_id":active_workspace_id(),"library_id":active_library_id(),"collection_id":active_collection_id(),"member_document_versions":documents,"index_snapshot":{"index_status":status["index_status"],"embedding_model":status.get("embedding_model"),"active_collection":rag._active_collection()}}
            versions=[item["current_version_id"] for item in documents if item.get("current_version_id")]
            if len(versions)!=len(documents):
                raise HTTPException(409,"selected library contains a document without a current version")
            if versions:
                result=rag.search_evidence(question,top_k=8,filters={"version_ids":versions})
            else:
                result={"items":[],"diagnostics":{"mode":"hybrid","coverage_limits":["no documents in selected collection"],"evidence_gap":"no documents in selected collection"},"snapshot_version_ids":[]}
            expected=set(versions)
            if not set(result.get("snapshot_version_ids",[])).issubset(expected):
                raise HTTPException(409,"selected library evidence does not match the frozen document versions")
            snapshot["reference_evidence"]=[{**item,"context":rag.get_evidence_context(item["evidence_id"],before=1,after=1)["items"]} for item in result["items"]]
            snapshot["reference_rag_diagnostics"]=result["diagnostics"]
            return snapshot

    @app.get("/api/v1/runs/{run_id}/reference-snapshot")
    def reference_snapshot(run_id: str):
        with service() as svc: svc.status(run_id)
        row=context_db().execute("SELECT snapshot FROM run_references WHERE run_id=?",(run_id,)).fetchone()
        return pack({"reference_snapshot":json.loads(row[0]) if row else None})

    @app.get("/api/v1/contexts")
    def contexts():
        wid=active_workspace_id(); lid=active_library_id(); collection=active_collection_id()
        available_libraries=[library_public(ident, item, wid) for ident,item in libraries.items() if wid in item["workspace_ids"]]
        for item in available_libraries: item["default"] = item["library_id"]==default_library_for[wid]
        collections=[{"collection_id":"all","name":"All documents","member_count":None}]
        for ident,item in libraries[lid]["collections"].items():
            members=item.get("document_ids",item.get("members",[])); members=list(members) if not isinstance(members,dict) else list(members)
            collections.append({"collection_id":ident,"name":item.get("name",ident),"member_count":len(members)})
        return pack({"workspace_id":wid,"workspace_name":workspaces[wid]["name"],"library_id":lid,"collection_id":collection,"workspaces":[{"workspace_id":ident,"name":item["name"]} for ident,item in workspaces.items()],"libraries":available_libraries,"collections":collections,"cross_library_search":False})

    @app.get("/api/v1/workspaces")
    def list_workspaces():
        return pack({"items":[{"workspace_id":ident,"name":item["name"],"description":item.get("description","")} for ident,item in workspaces.items()]})

    @app.get("/api/v1/conversations")
    def list_conversations():
        return pack({"items": conversation_db().list()})

    @app.post("/api/v1/conversations")
    def create_conversation(body: dict, idempotency_key: str | None = Header(None)):
        if not isinstance(body, dict) or set(body) - {"executor", "fixture_id", "api_config"}:
            raise HTTPException(400, "RH_GUI_CONVERSATION_REQUEST: conversation request is invalid")
        executor = body.get("executor", "scripted")
        fixture_id = body.get("fixture_id")
        if executor == "scripted" and fixture_id != "synthetic-d19":
            raise HTTPException(400, "RH_GUI_SCRIPTED_FIXTURE: scripted conversations require the synthetic-d19 fixture")
        if executor == "api" and fixture_id is not None:
            raise HTTPException(400, "RH_GUI_CONVERSATION_REQUEST: API conversations do not accept a scripted fixture")
        api_config = None
        if executor == "api":
            try:
                api_config = validate_api_config(body.get("api_config"))
            except InvestigationError as exc:
                raise HTTPException(400, f"{exc.code}:{exc.message}") from exc
        elif body.get("api_config") is not None:
            raise HTTPException(400, "RH_GUI_CONVERSATION_REQUEST: only API conversations accept API configuration")
        if executor == "external" and fixture_id is not None:
            raise HTTPException(400, "RH_GUI_CONVERSATION_REQUEST: external conversations do not accept a scripted fixture")
        try:
            return pack(conversation_db().create(active_library_id(), active_collection_id(), executor, fixture_id, idempotency_key or "", body, api_config))
        except ConversationError as exc:
            raise HTTPException(409 if exc.code == "RH_GUI_IDEMPOTENCY_CONFLICT" else 400, f"{exc.code}:{exc.message}") from exc

    @app.get("/api/v1/conversations/{conversation_id}")
    def conversation(conversation_id: str):
        try:
            value = conversation_db().get(conversation_id)
            if value["run_id"] and value["status"] in {"queued", "running"}:
                with service() as svc:
                    run_status = svc.status(value["run_id"])["status"]
                if run_status in {"completed", "partial", "failed", "stopped", "policy_blocked"}:
                    conversation_db().bind_execution(conversation_id, value["run_id"], value["command_id"], run_status)
                    conversation_db().tool_result(conversation_id, "execution", "run.status", run_status, {"run_id": value["run_id"], "command_id": value["command_id"]})
                    value = conversation_db().get(conversation_id)
            return pack({"conversation": value})
        except ConversationError as exc:
            raise HTTPException(404, f"{exc.code}:{exc.message}") from exc

    @app.post("/api/v1/conversations/{conversation_id}/executor")
    def switch_conversation_executor(conversation_id: str, body: dict, idempotency_key: str | None = Header(None)):
        if not isinstance(body, dict) or set(body) - {"executor", "fixture_id", "api_config"}:
            raise HTTPException(400, "RH_GUI_CONVERSATION_REQUEST: executor switch request is invalid")
        try:
            api_config = None
            if body.get("executor") == "api":
                try:
                    api_config = validate_api_config(body.get("api_config"))
                except InvestigationError as exc:
                    raise HTTPException(400, f"{exc.code}:{exc.message}") from exc
            elif body.get("api_config") is not None:
                raise HTTPException(400, "RH_GUI_CONVERSATION_REQUEST: only API executor accepts API configuration")
            current = conversation_db().get(conversation_id)
            busy = current["status"] in {"queued", "running", "stop_requested"}
            if current["command_id"]:
                with queue_lock:
                    command = queue_db.execute("SELECT status FROM commands WHERE command_id=? AND workspace_id=? AND library_id=? AND collection_id=?", (current["command_id"], active_workspace_id(), active_library_id(), active_collection_id())).fetchone()
                busy = busy or bool(command and command["status"] in {"queued", "running", "waiting_credentials", "waiting_external_lock", "needs_review"})
            value = conversation_db().switch_executor(conversation_id, body.get("executor"), body.get("fixture_id"), api_config, idempotency_key or "", body, execution_busy=busy)
            return pack({"conversation": value})
        except ConversationError as exc:
            status = 404 if exc.code.endswith("NOT_FOUND") else 409 if exc.code in {"RH_GUI_IDEMPOTENCY_CONFLICT", "RH_GUI_EXECUTOR_SWITCH_EXTERNAL_PENDING", "RH_GUI_EXECUTOR_SWITCH_BUSY", "RH_GUI_API_CONFIG_EXPANSION"} else 400
            raise HTTPException(status, f"{exc.code}:{exc.message}") from exc

    @app.post("/api/v1/conversations/{conversation_id}/turns")
    def conversation_turn(conversation_id: str, body: dict):
        if not isinstance(body, dict) or set(body) - {"request_id", "content", "research_spec", "runtime"}:
            raise HTTPException(400, "RH_GUI_TURN_REQUEST: turn request is invalid")
        try:
            current = conversation_db().get(conversation_id)
            spec, runtime = body.get("research_spec"), body.get("runtime")
            if current["executor"] == "scripted" and spec is None and runtime is None:
                spec, runtime, _ = load_scripted_fixture(current["fixture_id"], body.get("content", ""))
            if current["executor"] == "external":
                if spec is not None or runtime is not None:
                    raise HTTPException(400, "RH_GUI_EXTERNAL_TURN: external turns cannot attach a local research spec or runtime")
                value = conversation_db().submit_external_turn(conversation_id, body.get("request_id", ""), body.get("content", ""))
            elif current["executor"] == "api":
                if spec is not None or runtime is not None:
                    raise HTTPException(400, "RH_GUI_API_TURN: API turns are planned by the configured model and cannot attach a local runtime")
                config = current.get("api")
                provider = config["provider"] if config else None
                key = session_model_keys.get((active_workspace_id(), provider)) or os.environ.get(MODEL_KEY_ENV.get(provider, ""))
                if not key:
                    value = conversation_db().submit_turn(conversation_id, body.get("request_id", ""), body.get("content", ""), None, None,
                                                          reply="等待此工作区的模型凭据；没有发送模型请求。", forced_status="waiting_credentials")
                    return pack({"conversation": value})
                value, dispatch = conversation_db().begin_api_turn(conversation_id, body.get("request_id", ""), body.get("content", ""))
                if dispatch is None:
                    return pack({"conversation": value})
                try:
                    help_context = help_library.search(dispatch["content"], limit=3)
                    history = [{"role": item["role"], "content": item["content"][:2000]} for item in current.get("messages", [])[-8:]]
                    api_config = dispatch["config"]
                    workspace = workspaces.get(active_workspace_id(), {})
                    library = libraries.get(current["library_id"], {})
                    collections = library.get("collections", {})
                    collection = collections.get(current["collection_id"], {}) if isinstance(collections, dict) else {}
                    runtime = api_config.get("runtime_template", {})
                    dynamic_context = {
                        "workspace": {"id": active_workspace_id(), "name": workspace.get("name", active_workspace_id())},
                        "library": {"id": current["library_id"], "name": library.get("name", current["library_id"])},
                        "collection": {"id": current["collection_id"], "name": collection.get("name", current["collection_id"]) if isinstance(collection, dict) else current["collection_id"]},
                        "conversation": {"executor": current["executor"], "status": "planning"},
                        "model_accounting": {"used_calls": dispatch["planning_calls"],
                                             "remaining_calls": max(0, api_config["total_model_calls"] - dispatch["planning_calls"]),
                                             "usage": "UNKNOWN"},
                        "authorization": {"provider": api_config["provider"], "model": api_config["model"],
                                           "runtime_mode": runtime.get("mode"), "data_mode": runtime.get("data_mode"),
                                           "allow_network": runtime.get("allow_network"),
                                           "sources": runtime.get("sources", []),
                                           "max_planning_calls": api_config["max_planning_calls"],
                                           "total_model_calls": api_config["total_model_calls"],
                                           "max_output_tokens": api_config["max_output_tokens"],
                                           "timeout_seconds": api_config["timeout_seconds"]},
                    }
                    planning_config = {**api_config, "api_key": key, "help_context": help_context,
                                       "conversation_history": history, "dynamic_context": dynamic_context}
                    result, usage = plan_conversation(planning_config, dispatch["content"])
                    if result["kind"] == "help_answer":
                        answer = result["help_answer"]
                        value = conversation_db().finish_api_help_turn(conversation_id, dispatch["request_id"], answer["content"], answer["source_ids"], {item["source_id"] for item in help_context}, usage)
                    else:
                        planned_runtime = controlled_runtime(result["runtime"], dispatch["config"], dispatch["planning_calls"])
                        value = conversation_db().finish_api_turn(conversation_id, dispatch["request_id"], spec=result["research_spec"], runtime=planned_runtime, usage=usage)
                except InvestigationError as exc:
                    value = conversation_db().finish_api_turn(conversation_id, dispatch["request_id"], error_code=exc.code)
            else:
                value = conversation_db().submit_turn(conversation_id, body.get("request_id", ""), body.get("content", ""), spec, runtime)
            return pack({"conversation": value})
        except ConversationError as exc:
            raise HTTPException(404 if exc.code.endswith("NOT_FOUND") else 400, f"{exc.code}:{exc.message}") from exc

    @app.post("/api/v1/conversations/{conversation_id}/execute")
    def execute_conversation(conversation_id: str, body: dict, idempotency_key: str | None = Header(None)):
        if not isinstance(body, dict) or set(body) - {"scenario", "confirm_api_execution"} or not idempotency_key:
            raise HTTPException(400, "RH_GUI_CONVERSATION_EXECUTION: execution request and idempotency key are required")
        with active_write_lock:
            try:
                existing = conversation_db().get(conversation_id)
                if existing["run_id"]:
                    if conversation_db().execution_key(conversation_id) != idempotency_key:
                        raise HTTPException(409, "RH_GUI_CONVERSATION_EXECUTION_CONFLICT: conversation is already bound to a run under another execution request")
                    return pack({"conversation": existing, "run_id": existing["run_id"], "command_id": existing["command_id"], "replayed": True})
                current, spec, runtime = conversation_db().ready(conversation_id)
            except ConversationError as exc:
                raise HTTPException(409, f"{exc.code}:{exc.message}") from exc
            scenario = body.get("scenario")
            executor = current["executor"]
            if executor == "scripted":
                if runtime.get("mode") != "host" or runtime.get("data_mode") != "synthetic":
                    raise HTTPException(400, "RH_GUI_SCRIPTED_RUNTIME: scripted executor requires host synthetic runtime")
                if body.get("scenario") is not None:
                    raise HTTPException(400, "RH_GUI_SCRIPTED_FIXTURE: scripted executor only uses its verified bundled fixture")
                _, _, scenario = load_scripted_fixture(current["fixture_id"], spec["research_question"])
            elif executor == "api":
                if runtime.get("mode") != "api" or body.get("confirm_api_execution") is not True:
                    raise HTTPException(400, "RH_GUI_API_CONFIRMATION: API execution requires an API runtime and explicit confirmation")
                if not isinstance(scenario, dict):
                    raise HTTPException(409, "RH_GUI_API_PLANNING_PENDING: API execution needs an approved structured scenario")
            else:
                raise HTTPException(400, "RH_GUI_CONVERSATION_EXECUTOR: conversation executor is not supported")
            with service() as svc:
                created = svc.create_investigation(spec, runtime, scenario)
            operation = "conversation-scripted" if executor == "scripted" else "conversation-api"
            command = enqueue(operation, created["run_id"], {"conversation_id": conversation_id}, idempotency_key)
            conversation_db().bind_execution(conversation_id, created["run_id"], command["command_id"], "queued", idempotency_key)
            conversation_db().tool_result(conversation_id, "execution", operation, "queued", {"run_id": created["run_id"], "command_id": command["command_id"]})
        if command["status"] == "queued": start_queue_worker()
        return pack({"conversation": conversation_db().get(conversation_id), "run_id": created["run_id"], "command_id": command["command_id"], "synthetic_fixture": executor == "scripted"})

    @app.post("/api/v1/conversations/{conversation_id}/stop")
    def stop_conversation(conversation_id: str, body: dict, idempotency_key: str | None = Header(None)):
        if not isinstance(body, dict) or body.get("kind") not in {"reply", "investigation"} or not idempotency_key:
            raise HTTPException(400, "RH_GUI_CONVERSATION_STOP: stop kind and idempotency key are required")
        try:
            value = conversation_db().get(conversation_id)
            if body["kind"] == "reply":
                stopped_reply_conversations.add(conversation_id)
                return pack({"conversation": conversation_db().set_status(conversation_id, "reply_stopped")})
            if not value["run_id"]:
                return pack({"conversation": conversation_db().set_status(conversation_id, "stopped")})
            result = stop(value["run_id"], {}, idempotency_key)
            conversation_db().set_status(conversation_id, "stop_requested")
            return pack({"conversation": conversation_db().get(conversation_id), "stop": result})
        except ConversationError as exc:
            raise HTTPException(404, f"{exc.code}:{exc.message}") from exc

    @app.post("/api/v1/workspaces")
    def create_workspace(body: dict, idempotency_key: str | None = Header(None)):
        allowed = {"name", "description", "reference_library_ids"}
        if not isinstance(body, dict) or set(body) - allowed or "name" not in body or not isinstance(body["name"], str):
            raise HTTPException(400, "RH_GUI_WORKSPACE_REQUEST:workspace request is invalid")
        name = body["name"].strip()
        description = body.get("description", "")
        reference_ids = body.get("reference_library_ids", [])
        if not idempotency_key:
            raise HTTPException(400, "RH_GUI_IDEMPOTENCY_REQUIRED:idempotency-key is required")
        if not 1 <= len(name) <= 80 or "\0" in name or not isinstance(description, str) or len(description) > 500:
            raise HTTPException(400, "RH_GUI_WORKSPACE_REQUEST:workspace name or description is invalid")
        if not isinstance(reference_ids, list) or len(reference_ids) > 1 or any(not isinstance(value, str) for value in reference_ids):
            raise HTTPException(400, "RH_GUI_WORKSPACE_REQUEST:reference_library_ids is invalid")
        reference_id = reference_ids[0] if reference_ids else None
        if reference_id and reference_id not in libraries:
            raise HTTPException(404, "RH_GUI_LIBRARY_UNKNOWN:library is not registered")
        normalized = {"name": name, "description": description, "reference_library_ids": reference_ids}
        digest = hashlib.sha256(json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        with registry_lock:
            prior = runtime_registry["idempotency"].get(idempotency_key)
            if prior:
                if prior.get("digest") != digest:
                    raise HTTPException(409, "RH_GUI_IDEMPOTENCY_CONFLICT:idempotency key conflicts with an existing workspace request")
                return prior["response"]
            workspace_id = "ws-" + uuid.uuid4().hex
            library_id = reference_id or "lib-" + uuid.uuid4().hex
            workspace_dir = (workspace_data_root / workspace_id).resolve()
            library_dir = (library_data_root / library_id).resolve()
            created_workspace = created_library = False
            try:
                workspace_data_root.mkdir(parents=True, exist_ok=True)
                workspace_dir.mkdir()
                created_workspace = True
                if not reference_id:
                    library_data_root.mkdir(parents=True, exist_ok=True)
                    library_dir.mkdir()
                    created_library = True
                workspace_record = {"name": name, "description": description, "default_library_id": library_id}
                if reference_id:
                    workspace_record["reference_library_id"] = reference_id
                next_registry = json.loads(json.dumps(runtime_registry))
                next_registry["workspaces"][workspace_id] = workspace_record
                if not reference_id:
                    next_registry["libraries"][library_id] = {"name": f"{name} library", "workspace_ids": [workspace_id]}
                workspaces[workspace_id] = {**workspace_record, "path": workspace_dir}
                if reference_id:
                    libraries[reference_id]["workspace_ids"] = list(dict.fromkeys([*libraries[reference_id]["workspace_ids"], workspace_id]))
                    libraries[reference_id].setdefault("read_only_workspace_ids", []).append(workspace_id)
                else:
                    libraries[library_id] = {"name": f"{name} library", "path": library_dir, "workspace_ids": [workspace_id], "collections": {}, "runtime_empty": True, "runtime_created": True}
                default_library_for[workspace_id] = library_id
                response = {"schema_version": "1", **workspace_public(workspace_id)}
                next_registry["idempotency"][idempotency_key] = {"digest": digest, "response": response}
                write_runtime_registry(next_registry)
                runtime_registry.clear(); runtime_registry.update(next_registry)
                return response
            except Exception:
                workspaces.pop(workspace_id, None)
                default_library_for.pop(workspace_id, None)
                if reference_id:
                    if reference_id in libraries:
                        libraries[reference_id]["workspace_ids"] = [wid for wid in libraries[reference_id]["workspace_ids"] if wid != workspace_id]
                        libraries[reference_id]["read_only_workspace_ids"] = [wid for wid in libraries[reference_id].get("read_only_workspace_ids", []) if wid != workspace_id]
                else:
                    libraries.pop(library_id, None)
                if created_library:
                    library_dir.rmdir()
                if created_workspace:
                    workspace_dir.rmdir()
                raise

    @app.get("/api/v1/registry")
    def registry():
        return {"schema_version":"1","workspaces":[{**workspace_public(ident), "libraries":[{**library_public(lid, lib, ident), "collections":[{"collection_id":"all","name":"All documents"},*[{"collection_id":cid,"name":c.get("name",cid)} for cid,c in lib["collections"].items()]]} for lid,lib in libraries.items() if ident in lib["workspace_ids"]]} for ident in workspaces]}

    @app.get("/api/v1/workspaces/{workspace_id}/libraries")
    def workspace_libraries(workspace_id: str):
        if workspace_id not in workspaces: raise HTTPException(404,"workspace is not registered")
        return pack({"items":[{**library_public(ident, item, workspace_id),"default":ident==default_library_for[workspace_id]} for ident,item in libraries.items() if workspace_id in item["workspace_ids"]]})

    @app.post("/api/v1/libraries")
    def create_library(body: dict, idempotency_key: str | None = Header(None)):
        if not isinstance(body, dict) or set(body) != {"name"} or not isinstance(body["name"], str):
            raise HTTPException(400, "RH_GUI_LIBRARY_REQUEST:library request is invalid")
        name = body["name"].strip()
        if not 1 <= len(name) <= 80 or "\0" in name:
            raise HTTPException(400, "RH_GUI_LIBRARY_REQUEST:library name is invalid")
        if not idempotency_key:
            raise HTTPException(400, "RH_GUI_IDEMPOTENCY_REQUIRED:idempotency-key is required")
        wid = active_workspace_id()
        normalized = {"operation": "create-library", "workspace_id": wid, "name": name}
        digest = hashlib.sha256(json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        with registry_lock:
            prior = runtime_registry["idempotency"].get(idempotency_key)
            if prior:
                if prior.get("digest") != digest:
                    raise HTTPException(409, "RH_GUI_IDEMPOTENCY_CONFLICT:idempotency key conflicts with an existing request")
                return prior["response"]
            ident = "lib-" + uuid.uuid4().hex
            directory = (library_data_root / ident).resolve()
            if directory.parent != library_data_root.resolve():
                raise HTTPException(400, "RH_GUI_LIBRARY_PATH:library path is invalid")
            try:
                library_data_root.mkdir(parents=True, exist_ok=True)
                directory.mkdir()
                next_registry = json.loads(json.dumps(runtime_registry))
                next_registry["libraries"][ident] = {"name": name, "workspace_ids": [wid]}
                response = {"schema_version": "1", **library_public(ident, {"name": name, "path": directory, "workspace_ids": [wid], "collections": {}, "runtime_empty": True, "runtime_created": True}, wid)}
                next_registry["idempotency"][idempotency_key] = {"digest": digest, "response": response}
                write_runtime_registry(next_registry)
                runtime_registry.clear(); runtime_registry.update(next_registry)
                libraries[ident] = {"name": name, "path": directory, "workspace_ids": [wid], "collections": {}, "runtime_empty": True, "runtime_created": True}
                return response
            except Exception:
                if ident not in libraries and directory.exists():
                    directory.rmdir()
                raise

    @app.put("/api/v1/library/import")
    async def import_library_file(request: Request, filename: str):
        library = libraries[active_library_id()]
        library_root = library["path"]
        if library_public(active_library_id(), library, active_workspace_id())["read_only"] or (library_root / "rag.sqlite").is_file():
            raise HTTPException(403, "RH_GUI_LIBRARY_READ_ONLY:the selected library is read-only")
        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit() and int(content_length) > local_library.MAX_UPLOAD_BYTES:
            raise HTTPException(413, "RH_GUI_LIBRARY_TOO_LARGE:file exceeds the 20 MiB limit")
        chunks = bytearray()
        async for part in request.stream():
            if len(chunks) + len(part) > local_library.MAX_UPLOAD_BYTES:
                raise HTTPException(413, "RH_GUI_LIBRARY_TOO_LARGE:file exceeds the 20 MiB limit")
            chunks.extend(part)
        if not active_write_lock.acquire(blocking=False):
            raise HTTPException(409, "RH_GUI_BUSY:another write is active")
        try:
            try:
                result = await asyncio.to_thread(local_library.import_file, library_root, filename, bytes(chunks))
            except local_library.LocalLibraryError as exc:
                status = 413 if exc.code == "RH_GUI_LIBRARY_TOO_LARGE" else 400
                raise HTTPException(status, f"{exc.code}:{exc}") from exc
        finally:
            active_write_lock.release()
        return pack({**result, "index_mode": "basic"})

    @app.get("/api/v1/libraries/{library_id}/collections")
    def library_collections(library_id: str):
        if library_id not in libraries: raise HTTPException(404,"library is not registered")
        if active_workspace_id() not in libraries[library_id]["workspace_ids"]: raise HTTPException(403,"library is not associated with this workspace")
        record=libraries[library_id]
        items=[{"collection_id":"all","name":"All documents","member_count":None}]
        for ident,item in record["collections"].items():
            members=item.get("document_ids",item.get("members",[])); members=list(members) if not isinstance(members,dict) else list(members)
            items.append({"collection_id":ident,"name":item.get("name",ident),"member_count":len(members)})
        return pack({"items":items})

    @app.get("/api/v1/capabilities")
    def capabilities():
        with service() as svc:
            doctor = svc.doctor()
        return pack({"capabilities": {**doctor["capabilities"], "stop": True, "events": True, "api_model_step": True, "api_auto_advance": False,
                                      "desktop_shutdown": desktop_shutdown is not None}, "credential_status":"not_checked"})

    @app.get("/api/v1/model-credentials")
    def model_credentials():
        with lock:
            wid=active_workspace_id()
            return pack({"providers": {name: "session" if (wid,name) in session_model_keys else "environment" if os.environ.get(env_name) else "missing" for name, env_name in MODEL_KEY_ENV.items()}})

    @app.get("/api/v1/source-credentials")
    def source_credentials():
        with lock:
            wid=active_workspace_id()
            return pack({"sources": {name: "session" if (wid,name) in session_source_keys else "environment" if os.environ.get(env_name) else "missing" for name, env_name in SOURCE_KEY_ENV.items()}})

    @app.post("/api/v1/source-credentials/{name}")
    def set_source_credential(name: str, body: dict):
        if name not in SOURCE_KEY_ENV:
            raise HTTPException(400, "unsupported source credential")
        key = body.get("api_key")
        if not isinstance(key, str) or not key.strip() or len(key) > 4096 or any(ch in key for ch in "\r\n\x00"):
            raise HTTPException(400, "invalid API key")
        with lock:
            session_source_keys[(active_workspace_id(),name)] = key.strip()
        return pack({"name": name, "status": "session"})

    @app.delete("/api/v1/source-credentials/{name}")
    def clear_source_credential(name: str):
        if name not in SOURCE_KEY_ENV:
            raise HTTPException(400, "unsupported source credential")
        with lock:
            session_source_keys.pop((active_workspace_id(),name), None)
        return pack({"name": name, "status": "environment" if os.environ.get(SOURCE_KEY_ENV[name]) else "missing"})

    @app.get("/api/v1/mcp-setup")
    def mcp_setup():
        python_path = Path(mcp_python).resolve() if mcp_python else None
        return pack({"python": str(python_path) if python_path and python_path.is_file() else None,
                     "library_workspace": str(active_library_root()), "investigation_workspace": str(active_root()),
                     "model_cache": os.environ.get("RAG_MODEL_CACHE"),
                     "python_ready": bool(python_path and python_path.is_file())})

    @app.post("/api/v1/model-credentials/{provider}")
    def set_model_credential(provider: str, body: dict):
        if provider not in MODEL_KEY_ENV:
            raise HTTPException(400, "unsupported model provider")
        key = body.get("api_key")
        if not isinstance(key, str) or not key.strip() or len(key) > 4096 or any(ch in key for ch in "\r\n\x00"):
            raise HTTPException(400, "invalid API key")
        with lock:
            session_model_keys[(active_workspace_id(),provider)] = key.strip()
        return pack({"provider": provider, "status": "session"})

    @app.delete("/api/v1/model-credentials/{provider}")
    def clear_model_credential(provider: str):
        if provider not in MODEL_KEY_ENV:
            raise HTTPException(400, "unsupported model provider")
        with lock:
            session_model_keys.pop((active_workspace_id(),provider), None)
        return pack({"provider": provider, "status": "environment" if os.environ.get(MODEL_KEY_ENV[provider]) else "missing"})

    if desktop_shutdown is not None:
        @app.post("/api/v1/desktop/quit")
        def desktop_quit():
            threading.Timer(0.2, desktop_shutdown).start()
            return pack({"stopping": True})

    @app.get("/api/v1/runs")
    def runs(limit: int = 20, cursor: str | None = None):
        with service() as svc:
            values = svc.status()["runs"]
        return pack(_page(values, limit, cursor))

    golden_demo_facade = GoldenDemoFacade(root)

    @app.get("/api/v1/overview")
    def overview():
        workspace = workspaces[active_workspace_id()]
        library = libraries[active_library_id()]
        try:
            index_status = library_status(library)
        except Exception:
            index_status = None
        document_count = None
        try:
            library_root = active_library_root()
            if (library_root / "rag.sqlite").is_file() and (library_root / "qdrant").is_dir():
                with RagLibrary(library_root, read_only=True) as rag:
                    library_state = rag.get_library_status()
                    allowed = validate_collection_members([item["document_id"] for item in library_state["documents"]])
                    document_count = len(library_state["documents"]) if allowed is None else len(allowed)
            elif local_library.has_index(library_root) or library.get("runtime_created", False):
                listed = local_library.list_documents(library_root, limit=100, document_ids=collection_ids())
                document_count = listed.get("document_count")
        except Exception:
            document_count = None

        recent = []
        open_issue_count = 0
        issue_count_known = True
        with service() as svc:
            runs = svc.status()["runs"][:5]
            for item in runs:
                run_id = item.get("run_id")
                result = report = spec = None
                try:
                    result = svc.get_result(run_id)
                except Exception:
                    pass
                try:
                    report = svc.build_report_data(run_id)
                except Exception:
                    pass
                try:
                    spec = json.loads(svc._run(run_id)["spec"])
                except Exception:
                    pass
                claims = report.get("claims") if isinstance(report, dict) else None
                if isinstance(claims, list):
                    verified_count = sum(1 for claim in claims if claim.get("verification") in (True, "verified") or isinstance(claim.get("verification"), dict) and claim["verification"].get("status") == "verified")
                else:
                    verified_count = None
                issues = result.get("issues") if isinstance(result, dict) else None
                if isinstance(issues, list):
                    run_open_issues = sum(1 for issue in issues if issue.get("status") == "open")
                    open_issue_count += run_open_issues
                else:
                    run_open_issues = None
                    issue_count_known = False
                coverage = result.get("coverage") if isinstance(result, dict) else item.get("coverage")
                coverage_complete = coverage.get("complete") if isinstance(coverage, dict) and isinstance(coverage.get("complete"), bool) else None
                recent.append({
                    "run_id": run_id,
                    "project_id": spec.get("project_id") if isinstance(spec, dict) else None,
                    "research_question": (report or {}).get("research_question") if isinstance(report, dict) else spec.get("research_question") if isinstance(spec, dict) else None,
                    "outcome": result.get("outcome") if isinstance(result, dict) else item.get("outcome"),
                    "stage": item.get("stage"),
                    "synthetic": result.get("synthetic", item.get("synthetic")) if isinstance(result, dict) else item.get("synthetic"),
                    "verified_claim_count": verified_count,
                    "open_issue_count": run_open_issues,
                    "coverage_complete": coverage_complete,
                })
        return pack({
            "workspace": {"workspace_id": active_workspace_id(), "name": workspace["name"]},
            "library": {"library_id": active_library_id(), "name": library["name"], "index_status": index_status, "document_count": document_count},
            "recent_runs": recent,
            "review_summary": {"open_run_issue_count": open_issue_count if issue_count_known else None},
            "golden_demo": {"available": _golden_demo_available()},
        })

    @app.get("/api/v1/review-inbox")
    def review_inbox(limit: int = 50, cursor: str | None = None):
        """Read-only workspace projection of run issues; monitor reviews stay separate."""
        try:
            with service() as svc:
                runs_page = _page(svc.status()["runs"], limit, cursor)
                items = []
                unavailable_runs = []
                for run in runs_page["items"]:
                    run_id = run.get("run_id") if isinstance(run, dict) else None
                    if not run_id:
                        continue
                    try:
                        result = svc.get_result(run_id)
                    except Exception:
                        unavailable_runs.append({"run_id": run_id, "run_status": run.get("status"), "issue_count": None})
                        continue
                    issues = result.get("issues") if isinstance(result, dict) else None
                    if not isinstance(issues, list):
                        unavailable_runs.append({"run_id": run_id, "run_status": run.get("status"), "issue_count": None})
                        continue
                    for index, issue in enumerate(issues):
                        entry = issue if isinstance(issue, dict) else {}
                        items.append({
                            "kind": "run_issue",
                            "actionable": False,
                            "decision_actions": [],
                            "run_id": run_id,
                            "run_status": run.get("status"),
                            "outcome": result.get("outcome"),
                            "synthetic": result.get("synthetic", run.get("synthetic")),
                            "issue_index": index,
                            "issue_id": entry.get("issue_id"),
                            "title": entry.get("title"),
                            "code": entry.get("code"),
                            "status": entry.get("status"),
                            "message": entry.get("message"),
                            "reason": entry.get("reason"),
                            "document_id": entry.get("document_id"),
                            "source": entry.get("source"),
                            "impact": entry.get("impact"),
                        })
        except ValueError as exc:
            raise HTTPException(400, f"RH_GUI_REVIEW_INBOX_PAGE:{exc}") from exc
        return pack({
            "items": items,
            "next_cursor": runs_page["next_cursor"],
            "workspace_id": active_workspace_id(),
            "monitor_reviews_included": False,
            "unavailable_runs": unavailable_runs,
        })

    @app.get("/api/v1/golden-demo")
    def golden_demo_read():
        return golden_demo_facade.read()

    @app.get("/api/v1/golden-demo/runs/{run_id}")
    def golden_demo_run_read(run_id: str):
        return golden_demo_facade.read(run_id)

    @app.post("/api/v1/golden-demo")
    def golden_demo_create(body: dict, idempotency_key: str | None = Header(None)):
        if body:
            raise HTTPException(400, "golden demo request body must be empty")
        return write(idempotency_key, body, lambda: {"demo": golden_demo_facade.run()["demo"]})

    @app.post("/api/v1/demos/golden")
    def golden_demo(body: dict, idempotency_key: str | None = Header(None)):
        if body != {}:
            raise HTTPException(400, "RH_GUI_GOLDEN_DEMO_ARGUMENT:request body must be empty")
        def action():
            with service() as svc:
                result = run_golden_demo(str(active_root()), svc)
            return {key: result[key] for key in ("run_id", "outcome", "synthetic", "candidate_count", "evidence_document_count", "verified_claim_count", "open_issue_count")}
        return write(idempotency_key, body, action)

    @app.get("/api/v1/runs/{run_id}")
    def run(run_id: str):
        with service() as svc:
            status = svc.status(run_id)
        observe(run_id,status)
        return pack(status)

    @app.get("/api/v1/runs/{run_id}/result")
    def result(run_id: str):
        with service() as svc:
            return pack({"result":svc.get_result(run_id)})

    @app.get("/api/v1/runs/{run_id}/report-data")
    def report_data(run_id: str):
        with service() as svc:
            return pack({"report_data":svc.build_report_data(run_id)})

    @app.get("/api/v1/runs/{run_id}/tasks")
    def tasks(run_id: str):
        with service() as svc:
            return pack({"items":svc.get_pending_tasks(run_id)})

    @app.post("/api/v1/runs")
    def create(body: dict, idempotency_key: str | None = Header(None)):
        def action():
            snapshot=None
            if body.get("reference_scope") is not None:
                request_scope=body["reference_scope"]
                if request_scope.get("library_id")!=active_library_id() or request_scope.get("collection_id",active_collection_id())!=active_collection_id():
                    raise HTTPException(409,"reference scope changed before creation")
                snapshot=freeze_reference_snapshot(body["spec"]["research_question"])
            with service() as svc:
                with model_key_for(body["runtime"]):
                    with source_keys_for():
                        scenario=dict(body.get("scenario") or {})
                        if snapshot is not None:
                            policies={item.get("document_id"):item for item in body["spec"].get("references",[]) if isinstance(item,dict)}
                            evidence=[]
                            for item in snapshot["reference_evidence"]:
                                policy=policies.get(item["document_id"],{})
                                evidence.append({**item,"visibility":"public" if policy.get("visibility")=="public" else "confidential","company_id":policy.get("company_id")})
                            scenario["registered_reference_snapshot"]={key:snapshot[key] for key in ("workspace_id","library_id","collection_id","member_document_versions","index_snapshot")}
                            scenario["reference_evidence"]=evidence
                            scenario["reference_rag_diagnostics"]=snapshot["reference_rag_diagnostics"]
                        created=svc.create_investigation(body["spec"], body["runtime"], scenario)
            if snapshot is not None:
                context_db().execute("INSERT OR REPLACE INTO run_references VALUES (?,?)",(created["run_id"],json.dumps(snapshot,ensure_ascii=False))); context_db().commit()
            return created
        return write(idempotency_key, body, action)

    @app.post("/api/v1/runs/{run_id}/model-step")
    def model_step(run_id: str, body: dict, idempotency_key: str | None = Header(None)):
        def action():
            with service() as svc:
                runtime = json.loads(svc._run(run_id)["runtime"])
                if runtime.get("mode") != "api":
                    raise HTTPException(400, "run is not configured for model API execution")
                provider=runtime.get("model_api",{}).get("provider"); env_name=MODEL_KEY_ENV.get(provider)
                if not session_model_keys.get((active_workspace_id(),provider)) and not os.environ.get(env_name or ""):
                    raise InvestigationError("RH_GUI_WAITING_CREDENTIALS","This workspace needs its configured model credential before the command can run.")
                with model_key_for(runtime):
                    with source_keys_for():
                        pending = svc.get_pending_tasks(run_id)
                        if pending:
                            run_model_task(svc, run_id, pending[0])
                        else:
                            svc.advance_investigation(run_id)
                return svc.status(run_id)
        return write(idempotency_key, {"run_id":run_id, **body}, action, "model-step", run_id)

    @app.post("/api/v1/runs/{run_id}/advance")
    def advance(run_id: str, body: dict, idempotency_key: str | None = Header(None)):
        def action():
            with service() as svc:
                with source_keys_for():
                    return svc.advance_investigation(run_id)
        return write(idempotency_key, {"run_id":run_id,**body}, action, "advance", run_id)

    @app.post("/api/v1/runs/{run_id}/tasks/{task_id}")
    def submit(run_id: str, task_id: str, body: dict, idempotency_key: str | None = Header(None)):
        def action():
            with service() as svc:
                return svc.submit_model_result(run_id, task_id, body["result"], body["task_version"])
        return write(idempotency_key, {"run_id":run_id,"task_id":task_id,**body}, action)

    @app.post("/api/v1/runs/{run_id}/stop")
    def stop(run_id: str, body: dict, idempotency_key: str | None = Header(None)):
        def action():
            with service() as svc:
                return svc.request_stop(run_id)
        if not idempotency_key: raise HTTPException(400,"idempotency_key required")
        with queue_lock:
            pending=queue_db.execute("SELECT 1 FROM commands WHERE status IN ('queued','running','waiting_credentials','waiting_external_lock') UNION ALL SELECT 1 FROM stop_intents WHERE status IN ('queued','running') LIMIT 1").fetchone()
            busy=active_write_lock.locked() or bool(pending)
            if busy:
                for item in queue_db.execute("SELECT command_id FROM commands WHERE workspace_id=? AND run_id=? AND operation IN ('advance','model-step','resume') AND status IN ('queued','waiting_credentials','waiting_external_lock')",(active_workspace_id(),run_id)).fetchall():
                    queue_db.execute("UPDATE commands SET status='cancelled',updated=? WHERE command_id=?",(time.time(),item[0]))
                queue_db.commit()
        if busy:
            command=enqueue_stop_intent(run_id,idempotency_key)
            start_queue_worker()
            return pack({"command_id":command["command_id"],"status":command["status"],"queued":True,"accepted":True})
        return write(idempotency_key, {"run_id":run_id,**body}, action)

    @app.post("/api/v1/runs/{run_id}/resume")
    def resume(run_id: str, body: dict, idempotency_key: str | None = Header(None)):
        def action():
            with service() as svc:
                return svc.resume_investigation(run_id)
        return write(idempotency_key, {"run_id":run_id,**body}, action, "resume", run_id)

    @app.get("/api/v1/runs/{run_id}/artifacts")
    def artifacts(run_id: str):
        with service() as svc:
            values = svc.get_artifacts(run_id)
        return pack({"items":[{**item,"artifact_id":hashlib.sha256((run_id+":"+item["path"]).encode()).hexdigest(),"name":Path(item["path"]).name,"path":None} for item in values]})

    @app.post("/api/v1/runs/{run_id}/export")
    def export(run_id: str, body: dict, idempotency_key: str | None = Header(None)):
        def action():
            with service() as svc:
                exported = svc.export_report(run_id, body.get("languages"))
            return {"artifacts":[{**item,"artifact_id":hashlib.sha256((run_id+":"+item["path"]).encode()).hexdigest(),"name":Path(item["path"]).name,"path":None} for item in exported["artifacts"]]}
        return write(idempotency_key, {"run_id":run_id,**body}, action, "export", run_id, {"languages":body.get("languages")})

    @app.get("/api/v1/artifacts/{artifact_id}")
    def artifact(artifact_id: str):
        with service() as svc:
            runs = svc.status()["runs"]
            for row in runs:
                try:
                    items = svc.get_artifacts(row["run_id"])
                except Exception:
                    continue
                for item in items:
                    path = item.get("path", "")
                    if hashlib.sha256((row["run_id"]+":"+path).encode()).hexdigest() == artifact_id:
                        root=active_root(); target = (root / path).resolve()
                        if not target.is_relative_to(root / "reports") or not target.is_file():
                            raise HTTPException(404, "artifact unavailable")
                        return FileResponse(target, filename=target.name)
        raise HTTPException(404, "artifact unavailable")

    @app.get("/api/v1/library")
    def library(limit: int = 20, cursor: str | None = None):
        library_root=active_library_root()
        if (library_root / "rag.sqlite").is_file() or (library_root / "qdrant").exists():
            if not (library_root / "rag.sqlite").is_file() or not (library_root / "qdrant").is_dir():
                return pack({"items":[],"next_cursor":None,"index_status":"not_indexed","document_count":None,"reason":"RH_RAG_NOT_FOUND"})
            with RagLibrary(library_root, read_only=True) as rag:
                status = rag.get_library_status()
                allowed=validate_collection_members([d["document_id"] for d in status["documents"]])
                values = [_document_projection(rag.get_document(d["document_id"])) for d in status["documents"] if allowed is None or d["document_id"] in allowed]
            return pack({**_page(values,limit,cursor),"index_status":status["index_status"],"index_mode":"hybrid","document_count":len(values)})
        if not local_library.has_index(library_root) and not libraries[active_library_id()].get("runtime_created", False):
            return pack({"items": [], "next_cursor": None, "index_status": "not_indexed", "document_count": None, "reason": "RH_RAG_NOT_FOUND"})
        try:
            selected=collection_ids()
            result = local_library.list_documents(library_root, limit=max(1, min(limit, 100)), cursor=cursor, document_ids=set(selected) if selected is not None else None)
        except local_library.LocalLibraryError as exc:
            raise HTTPException(400, f"{exc.code}:{exc}") from exc
        return pack(result)

    @app.get("/api/v1/library/search")
    async def library_search(q: str, top_k: int = 8):
        if not q.strip() or len(q) > 500 or not 1 <= top_k <= 20:
            raise HTTPException(400, "query or top_k is invalid")
        library_root=active_library_root()
        if not (library_root / "rag.sqlite").is_file() and not (library_root / "qdrant").exists():
            selected=collection_ids()
            return pack(local_library.search(library_root, q, top_k=top_k, document_ids=set(selected) if selected is not None else None))
        if not (library_root / "rag.sqlite").is_file() or not (library_root / "qdrant").is_dir():
            raise HTTPException(409, "RH_RAG_NOT_FOUND:legacy literature index is incomplete; no basic-index fallback was attempted")
        with RagLibrary(library_root,read_only=True) as rag: available=[d["document_id"] for d in rag.get_library_status()["documents"]]
        ids=validate_collection_members(available); filters={"document_ids":ids} if ids is not None else {}
        if ids is not None and not ids: return pack({"query":q,"items":[],"diagnostics":{"mode":"hybrid","coverage_limits":["empty registered collection"]}})
        result = await asyncio.get_running_loop().run_in_executor(rag_search_executor, search_rag, active_library_id(), library_root, q, top_k, filters)
        public = [{k: value for k, value in item.items() if k != "source_path"} for item in result["items"]]
        return pack({"query": q, "items": public, "diagnostics": result["diagnostics"]})

    def _document_projection(document):
        return {**{k:v for k,v in document.items() if k != "source_path"}, "versions":[{**{k:v for k,v in version.items() if k != "source_path"},"file_url":f"/api/v1/library/documents/{document['document_id']}/versions/{version['version_id']}/file"} for version in document["versions"]]}

    @app.get("/api/v1/library/documents/{document_id}")
    def library_document(document_id: str):
        check_document_scope(document_id)
        library_root=active_library_root()
        if not (library_root / "rag.sqlite").is_file():
            try:
                return pack({"document": local_library.get_document(library_root, document_id)})
            except local_library.LocalLibraryError as exc:
                raise HTTPException(404, f"{exc.code}:{exc}") from exc
        with RagLibrary(library_root, read_only=True) as rag:
            return pack({"document":_document_projection(rag.get_document(document_id))})

    @app.get("/api/v1/library/documents/{document_id}/versions/{version_id}/file")
    def library_file(document_id: str, version_id: str):
        target, source = library_source(document_id, version_id)
        return FileResponse(target, filename=source.name, content_disposition_type="inline" if target.suffix.lower() == ".pdf" else "attachment")

    def library_source(document_id: str, version_id: str):
        check_document_scope(document_id)
        library_root=active_library_root()
        if not (library_root / "rag.sqlite").is_file():
            try:
                target = local_library.source_file(library_root, document_id, version_id)
                return target, target
            except local_library.LocalLibraryError as exc:
                raise HTTPException(404, f"{exc.code}:{exc}") from exc
        with RagLibrary(library_root, read_only=True) as rag:
            document = rag.get_document(document_id)
        version = next((item for item in document["versions"] if item["version_id"] == version_id), None)
        if not version:
            raise HTTPException(404, "document version unavailable")
        source = Path(version["source_path"])
        target = (library_root / "raw" / f"{version_id}{source.suffix.casefold()}").resolve()
        if not target.is_relative_to(library_root / "raw") or not target.is_file():
            raise HTTPException(404, "document file unavailable")
        return target, source

    def pdf_preview_html(pdf_source, page: int, base: str):
        import pypdfium2 as pdfium
        with pdfium.PdfDocument(pdf_source) as pdf:
            total = len(pdf)
        if not 1 <= page <= total:
            raise HTTPException(404, "PDF page unavailable")
        safe_base = html.escape(base, quote=True)
        image_url = html.escape(f"{base}/image?page={page}", quote=True)
        prev_link = f'<a href="{safe_base}?page={page-1}">Previous</a>' if page > 1 else ""
        next_link = f'<a href="{safe_base}?page={page+1}">Next</a>' if page < total else ""
        file_link = html.escape(base.removesuffix("/preview") + "/file", quote=True)
        body = f'<html><head><meta charset="utf-8"><title>PDF page {page}</title><style>body{{margin:0;background:#eee;font:16px sans-serif}}nav{{position:sticky;top:0;background:white;padding:12px;display:flex;gap:16px}}img{{display:block;max-width:100%;margin:16px auto;box-shadow:0 2px 12px #aaa}}</style></head><body><nav><a href="/">Workbench</a><span>Page {page} / {total}</span>{prev_link}{next_link}<a href="{file_link}" download>Download original PDF</a></nav><img alt="PDF page {page}" src="{image_url}"></body></html>'
        return HTMLResponse(body, headers={"Cache-Control": "no-store"})

    def pdf_preview_image(pdf_source, page: int):
        import pypdfium2 as pdfium
        with pdfium.PdfDocument(pdf_source) as pdf:
            if not 1 <= page <= len(pdf):
                raise HTTPException(404, "PDF page unavailable")
            bitmap = pdf[page - 1].render(scale=1.5)
            image = bitmap.to_pil()
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
        return Response(buffer.getvalue(), media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})

    @app.get("/api/v1/library/documents/{document_id}/versions/{version_id}/preview")
    def library_preview(document_id: str, version_id: str, page: int = 1):
        target, _ = library_source(document_id, version_id)
        if target.suffix.lower() != ".pdf":
            raise HTTPException(400, "PDF preview is unavailable")
        base = f"/api/v1/library/documents/{document_id}/versions/{version_id}/preview"
        return pdf_preview_html(str(target), page, base)

    @app.get("/api/v1/library/documents/{document_id}/versions/{version_id}/preview/image")
    def library_preview_image(document_id: str, version_id: str, page: int = 1):
        target, _ = library_source(document_id, version_id)
        if target.suffix.lower() != ".pdf":
            raise HTTPException(400, "PDF preview is unavailable")
        return pdf_preview_image(str(target), page)

    @app.get("/api/v1/runs/{run_id}/documents/{document_id}")
    def discovery_document(run_id: str, document_id: str):
        with service() as svc:
            item = svc.get_discovery_document(run_id,document_id)
        public = {k:v for k,v in item.items() if k not in {"source_xml","raw_xml_path","source_path","base64_bytes"}}
        public["file_url"] = f"/api/v1/runs/{run_id}/documents/{document_id}/file" if item.get("content_type") == "application/pdf" and item.get("base64_bytes") else None
        public["originals"] = [{"section":entry.get("section"),"original_id":_original_id(run_id,document_id,entry),"url":f"/api/v1/runs/{run_id}/documents/{document_id}/originals/{_original_id(run_id,document_id,entry)}"} for entry in item.get("source_xml",[]) if entry.get("raw_xml_path")]
        return pack({"document":public})

    def _original_id(run_id, document_id, entry):
        return hashlib.sha256(json.dumps([run_id,document_id,entry.get("section"),entry.get("raw_xml_path")],ensure_ascii=False).encode()).hexdigest()

    @app.get("/api/v1/runs/{run_id}/documents/{document_id}/originals/{original_id}")
    def discovery_original(run_id: str, document_id: str, original_id: str):
        with service() as svc:
            item = svc.get_discovery_document(run_id,document_id)
        entry = next((entry for entry in item.get("source_xml",[]) if entry.get("raw_xml_path") and _original_id(run_id,document_id,entry)==original_id),None)
        if not entry:
            raise HTTPException(404, "original unavailable")
        root=active_root(); target = (root / entry["raw_xml_path"]).resolve()
        if not target.is_relative_to(root / "epo" / run_id) or not target.is_file():
            raise HTTPException(404, "original unavailable")
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if entry.get("sha256") and entry["sha256"] != digest:
            raise HTTPException(409, "original checksum mismatch")
        return FileResponse(target, media_type="application/xml", filename=target.name)

    @app.get("/api/v1/runs/{run_id}/documents/{document_id}/locate")
    def discovery_locate(run_id: str, document_id: str, kind: str, value: str):
        with service() as svc:
            item = svc.get_discovery_document(run_id,document_id)
        match = next((part for part in item.get("epo_sections",[]) if part.get("locator",{}).get("kind")==kind and str(part.get("locator",{}).get("value"))==value),None)
        if not match:
            raise HTTPException(404, "locator unavailable")
        return pack({"locator":match["locator"],"section":match.get("section"),"text":match.get("text"),"content_scope":item.get("content_scope","registered_original")})

    @app.get("/api/v1/runs/{run_id}/documents/{document_id}/file")
    def discovery_file(run_id: str, document_id: str):
        with service() as svc:
            item = svc.get_discovery_document(run_id,document_id)
        if item.get("content_type") != "application/pdf" or not item.get("base64_bytes"):
            raise HTTPException(404, "document file unavailable")
        return Response(base64.b64decode(item["base64_bytes"]), media_type="application/pdf")

    def discovery_pdf(run_id: str, document_id: str):
        with service() as svc:
            item = svc.get_discovery_document(run_id, document_id)
        if item.get("content_type") != "application/pdf" or not item.get("base64_bytes"):
            raise HTTPException(404, "document file unavailable")
        return base64.b64decode(item["base64_bytes"])

    @app.get("/api/v1/runs/{run_id}/documents/{document_id}/preview")
    def discovery_preview(run_id: str, document_id: str, page: int = 1):
        payload = discovery_pdf(run_id, document_id)
        base = f"/api/v1/runs/{run_id}/documents/{document_id}/preview"
        return pdf_preview_html(payload, page, base)

    @app.get("/api/v1/runs/{run_id}/documents/{document_id}/preview/image")
    def discovery_preview_image(run_id: str, document_id: str, page: int = 1):
        return pdf_preview_image(discovery_pdf(run_id, document_id), page)

    @app.get("/api/v1/evidence/{evidence_id}")
    def evidence(evidence_id: str, run_id: str | None = None):
        item=None
        if run_id:
            with service() as svc:
                svc.status(run_id)
                snapshot=context_db().execute("SELECT snapshot FROM run_references WHERE run_id=?",(run_id,)).fetchone()
                frozen_scope=json.loads(snapshot[0]) if snapshot else None
                report=svc.build_report_data(run_id)
                item=next((entry for entry in report.get("evidence",[]) if entry.get("evidence_id")==evidence_id),None)
            if item is None:
                raise HTTPException(404,"evidence is not registered for this run")
            if frozen_scope and frozen_scope["library_id"] in libraries:
                library_id=frozen_scope["library_id"]
                library_ids=libraries[library_id]["collections"].get(frozen_scope["collection_id"],{}).get("document_ids")
                if library_ids is not None and item.get("document_id") not in library_ids:
                    raise HTTPException(404,"evidence is outside the frozen reference scope")
            return pack({"evidence":item,"locator_insufficient":not bool(item.get("locator")),"source_scope":frozen_scope})
        with service() as svc:
            try: item=svc.get_discovery_evidence(evidence_id)
            except Exception as exc:
                if getattr(exc,"code","")!="RH_NOT_FOUND": raise
        if item is None:
            library_root = active_library_root()
            if not (library_root / "rag.sqlite").is_file():
                try:
                    item = local_library.evidence_context(library_root, evidence_id)
                    check_document_scope(item["document_id"])
                except local_library.LocalLibraryError as exc:
                    raise HTTPException(404, f"{exc.code}:{exc}") from exc
            else:
                with RagLibrary(library_root, read_only=True) as rag:
                    item=rag.get_evidence_context(evidence_id)
                    item["items"]=[{k:v for k,v in row.items() if k!="source_path"} for row in item["items"]]
        return pack({"evidence":item,"locator_insufficient":not bool(item.get("locator"))})

    @app.get("/api/v1/reviews")
    def reviews(monitor_id: str, limit: int = 20, cursor: str | None = None):
        with service() as svc:
            values = svc.review_list(monitor_id)
        return pack(_page(values,limit,cursor))

    @app.post("/api/v1/reviews/{issue_id}/decision")
    def decide(issue_id: str, body: dict, idempotency_key: str | None = Header(None)):
        def action():
            with service() as svc:
                return svc.review_decide(issue_id,body["decision"],body.get("note",""))
        return write(idempotency_key, {"issue_id":issue_id,**body}, action)

    @app.get("/api/v1/runs/{run_id}/events")
    def events(run_id: str, after: int = 0, limit: int = 100):
        if after < 0 or not 1 <= limit <= 100:
            raise HTTPException(400, "invalid event cursor or limit")
        with service() as svc:
            snapshot = svc.status(run_id)
        observe(run_id,snapshot)
        with lock:
            db=event_db(); bounds = db.execute("SELECT MIN(seq),MAX(seq) FROM observations WHERE run_id=?", (run_id,)).fetchone()
            if after > bounds[1] or after < bounds[0]-1 and after != 0:
                raise HTTPException(409, "event cursor gap; refetch run snapshot")
            rows = db.execute("SELECT seq,run_id,type,time,payload FROM observations WHERE run_id=? AND seq>? ORDER BY seq LIMIT ?", (run_id,after,limit)).fetchall()
        return pack({"snapshot":snapshot,"events":[{"seq":r[0],"run_id":r[1],"type":r[2],"time":r[3],"payload":json.loads(r[4])} for r in rows],"next_seq":rows[-1][0] if rows else after,"transport":"poll"})

    def check_external_refs(refs: dict):
        """Only retain IDs that this GUI service can resolve in the current scope."""
        if not isinstance(refs, dict) or set(refs) - {"run_id", "command_id", "evidence_id"}:
            raise HTTPException(400, "RH_GUI_EXTERNAL_REFS: external object references are invalid")
        run_id = refs.get("run_id")
        command_id = refs.get("command_id")
        evidence_id = refs.get("evidence_id")
        if run_id is not None:
            if not isinstance(run_id, str): raise HTTPException(400, "RH_GUI_EXTERNAL_REFS: run_id is invalid")
            with service() as svc: svc.status(run_id)
        if command_id is not None:
            if not isinstance(command_id, str): raise HTTPException(400, "RH_GUI_EXTERNAL_REFS: command_id is invalid")
            with queue_lock:
                command = queue_db.execute("SELECT workspace_id,library_id,collection_id FROM commands WHERE command_id=?", (command_id,)).fetchone()
            if not command or (command["workspace_id"], command["library_id"], command["collection_id"]) != (active_workspace_id(), active_library_id(), active_collection_id()):
                raise HTTPException(404, "RH_GUI_EXTERNAL_REFS: command is not available in this scope")
        if evidence_id is not None:
            if not isinstance(evidence_id, str) or not isinstance(run_id, str):
                raise HTTPException(400, "RH_GUI_EXTERNAL_REFS: evidence_id requires a run_id")
            evidence(evidence_id, run_id)

    @app.post("/api/v1/control")
    def control(body: dict):
        """Single managed entrypoint; all mutations delegate to the GUI routes above."""
        action = body.get("action")
        actor = body.get("actor")
        request_id = body.get("request_id")
        scope = body.get("scope", {})
        if not isinstance(action, str) or not isinstance(actor, str) or not actor or not isinstance(request_id, str) or not request_id:
            raise HTTPException(400, "RH_GUI_CONTROL_IDENTITY: action, actor, and request_id are required")
        if not isinstance(scope, dict) or any(scope.get(key) not in (None, value) for key, value in (("workspace_id", active_workspace_id()), ("library_id", active_library_id()), ("collection_id", active_collection_id()))):
            raise HTTPException(403, "RH_GUI_CONTROL_SCOPE: request scope does not match the connected GUI scope")
        payload = body.get("payload", {})
        if not isinstance(payload, dict): raise HTTPException(400, "RH_GUI_CONTROL_INPUT: payload must be an object")
        key = body.get("idempotency_key")
        writes = {"workspace.create", "run.create", "run.submit", "run.advance", "run.stop", "run.resume", "run.export", "queue.cancel", "queue.resume"}
        if action in writes and (not isinstance(key, str) or not key):
            raise HTTPException(400, "RH_GUI_CONTROL_IDEMPOTENCY: idempotency_key is required for writes")
        if action == "workspace.list": return pack(_page([{"workspace_id": ident, "name": value["name"], "description": value.get("description", "")} for ident, value in workspaces.items()], payload.get("limit", 20), payload.get("cursor")))
        if action == "help.search":
            if set(payload) - {"query", "limit"}:
                raise HTTPException(400, "RH_GUI_HELP_INPUT: help search payload is invalid")
            try:
                return pack({"items": help_library.search(payload.get("query"), payload.get("limit", 5))})
            except ValueError as exc:
                raise HTTPException(400, "RH_GUI_HELP_INPUT: help query is invalid") from exc
        if action == "help.read":
            if set(payload) != {"source_id"}:
                raise HTTPException(400, "RH_GUI_HELP_INPUT: help read payload is invalid")
            try:
                return pack({"item": help_library.read(payload.get("source_id"))})
            except (ValueError, KeyError) as exc:
                raise HTTPException(404, "RH_GUI_HELP_NOT_FOUND: help passage is unavailable") from exc
        external_actions = {"conversation.list_pending", "conversation.claim", "conversation.context", "conversation.progress", "conversation.reply", "conversation.ack"}
        if action in external_actions:
            conversation_id = payload.get("conversation_id")
            turn_id = payload.get("turn_id")
            if action == "conversation.list_pending":
                return pack({"items": conversation_db().list_pending_external()})
            if not isinstance(conversation_id, str) or not isinstance(turn_id, str):
                raise HTTPException(400, "RH_GUI_EXTERNAL_TURN: conversation_id and turn_id are required")
            try:
                conversation_db().get(conversation_id)
                if action == "conversation.claim":
                    if set(payload) - {"conversation_id", "turn_id", "lease_seconds"}:
                        raise HTTPException(400, "RH_GUI_EXTERNAL_INPUT: external claim payload is invalid")
                    return pack(conversation_db().claim_external(conversation_id, turn_id, actor, request_id, payload.get("lease_seconds", 30)))
                claim_id = payload.get("claim_id")
                if not isinstance(claim_id, str):
                    raise HTTPException(400, "RH_GUI_EXTERNAL_CLAIM: claim_id is required")
                if action == "conversation.context":
                    if set(payload) - {"conversation_id", "turn_id", "claim_id"}:
                        raise HTTPException(400, "RH_GUI_EXTERNAL_INPUT: external context payload is invalid")
                    return pack(conversation_db().external_context(conversation_id, turn_id, actor, claim_id))
                if action in {"conversation.progress", "conversation.reply"}:
                    if set(payload) - {"conversation_id", "turn_id", "claim_id", "content", "object_refs"}:
                        raise HTTPException(400, "RH_GUI_EXTERNAL_INPUT: external message payload is invalid")
                    refs = payload.get("object_refs", {})
                    check_external_refs(refs)
                    if action == "conversation.progress":
                        return pack(conversation_db().external_progress(conversation_id, turn_id, actor, claim_id, request_id, payload.get("content"), refs))
                    return pack(conversation_db().external_reply(conversation_id, turn_id, actor, claim_id, request_id, payload.get("content"), refs))
                if action == "conversation.ack":
                    if set(payload) - {"conversation_id", "turn_id", "claim_id"}:
                        raise HTTPException(400, "RH_GUI_EXTERNAL_INPUT: external acknowledgement payload is invalid")
                    return pack(conversation_db().external_ack(conversation_id, turn_id, actor, claim_id, request_id))
            except ConversationError as exc:
                code = exc.code
                raise HTTPException(409 if "CONFLICT" in code or "LEASE" in code or "PENDING" in code else 404 if "NOT_FOUND" in code else 400, f"{code}:{exc.message}") from exc
        if action == "workspace.create": return create_workspace(payload, key)
        if action == "library.list": return workspace_libraries(active_workspace_id())
        if action == "collection.list": return library_collections(active_library_id())
        if action == "run.create": return create(payload, key)
        run_id = payload.get("run_id")
        if action in {"run.status", "run.tasks", "run.advance", "run.stop", "run.resume", "run.export", "report.read"} and not isinstance(run_id, str):
            raise HTTPException(400, "RH_GUI_CONTROL_RUN: run_id is required")
        if action == "run.status": return run(run_id)
        if action == "run.tasks": return tasks(run_id)
        if action == "run.submit":
            task_id = payload.get("task_id")
            if not isinstance(run_id, str) or not isinstance(task_id, str) or "result" not in payload or not isinstance(payload.get("task_version"), int):
                raise HTTPException(400, "RH_GUI_CONTROL_TASK: run_id, task_id, result, and task_version are required")
            return submit(run_id, task_id, {"result": payload["result"], "task_version": payload["task_version"]}, key)
        if action == "run.advance": return advance(run_id, {}, key)
        if action == "run.stop": return stop(run_id, {}, key)
        if action == "run.resume": return resume(run_id, {}, key)
        if action == "run.export": return export(run_id, {"languages": payload.get("languages")}, key)
        if action == "queue.list": return command_queue()
        if action == "queue.detail":
            command_id = payload.get("command_id")
            if not isinstance(command_id, str): raise HTTPException(400, "RH_GUI_CONTROL_COMMAND: command_id is required")
            return command_detail(command_id)
        if action == "queue.cancel":
            command_id = payload.get("command_id")
            if not isinstance(command_id, str): raise HTTPException(400, "RH_GUI_CONTROL_COMMAND: command_id is required")
            return cancel_command(command_id)
        if action == "queue.resume": return resume_queue(payload)
        if action == "evidence.read":
            evidence_id = payload.get("evidence_id")
            if not isinstance(evidence_id, str): raise HTTPException(400, "RH_GUI_CONTROL_EVIDENCE: evidence_id is required")
            return evidence(evidence_id, payload.get("run_id"))
        if action == "report.read": return report_data(run_id)
        if action == "view.subscribe":
            client_id = payload.get("client_id")
            if not isinstance(client_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", client_id): raise HTTPException(400, "RH_GUI_CONTROL_CLIENT: client_id is invalid")
            control_clients[client_id] = {"workspace_id": active_workspace_id(), "library_id": active_library_id(), "collection_id": active_collection_id(), "events": []}
            return pack({"client_id": client_id, "connected": True})
        if action == "view.open":
            client_id = payload.get("client_id")
            page = payload.get("page")
            if not isinstance(client_id, str) or page not in {"run", "report", "evidence", "queue"}: raise HTTPException(400, "RH_GUI_CONTROL_VIEW: client_id and page are invalid")
            target = {"page": page, "workspace_id": active_workspace_id(), "run_id": payload.get("run_id"), "evidence_id": payload.get("evidence_id")}
            if target["run_id"] is not None:
                if not isinstance(target["run_id"], str): raise HTTPException(400, "RH_GUI_CONTROL_RUN: run_id is invalid")
                with service() as svc: svc.status(target["run_id"])
            if target["evidence_id"] is not None:
                if not isinstance(target["evidence_id"], str): raise HTTPException(400, "RH_GUI_CONTROL_EVIDENCE: evidence_id is invalid")
                evidence(target["evidence_id"], target["run_id"])
            client = control_clients.get(client_id)
            if not client:
                return pack({"target": target, "navigated": False, "reason": "client_not_connected"})
            if any(client[key] != active_workspace_id() if key == "workspace_id" else client[key] != active_library_id() if key == "library_id" else client[key] != active_collection_id() for key in ("workspace_id", "library_id", "collection_id")):
                raise HTTPException(403, "RH_GUI_CONTROL_CLIENT_SCOPE: client is registered for another scope")
            client["events"].append({"type": "navigate", "target": target, "request_id": request_id})
            return pack({"target": target, "queued": True, "navigated": False})
        raise HTTPException(404, "RH_GUI_CONTROL_ACTION: action is not supported")

    @app.get("/api/v1/control/clients/{client_id}/events")
    def control_client_events(client_id: str, after: int = 0):
        client = control_clients.get(client_id)
        if client is None: raise HTTPException(404, "RH_GUI_CONTROL_CLIENT: client is not connected")
        if (client["workspace_id"], client["library_id"], client["collection_id"]) != (active_workspace_id(), active_library_id(), active_collection_id()):
            raise HTTPException(403, "RH_GUI_CONTROL_CLIENT_SCOPE: client is registered for another scope")
        if after < 0: raise HTTPException(400, "RH_GUI_CONTROL_EVENT_CURSOR: cursor is invalid")
        values = [{"seq": index, **event} for index, event in enumerate(client["events"], 1) if index > after]
        return pack({"client_id": client_id, "events": values, "next_seq": len(client["events"])})

    if static_dir and Path(static_dir).is_dir():
        @app.get("/", include_in_schema=False)
        def frontend_index():
            index = Path(static_dir) / "index.html"
            html = index.read_text(encoding="utf-8")
            marker = '<meta name="rh-session-token" content="' + secret + '">'
            html = html.replace("<head>", "<head>" + marker, 1)
            return HTMLResponse(html, headers={"Cache-Control": "no-store"})
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")
    with queue_lock:
        pending_stop=bool(queue_db.execute("SELECT 1 FROM stop_intents WHERE status='queued' LIMIT 1").fetchone())
    if pending_stop: start_queue_worker()
    app.state.session_token = secret
    return app
