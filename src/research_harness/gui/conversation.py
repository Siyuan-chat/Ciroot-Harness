"""Workspace-local, credential-free persistence for the GUI conversation API."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from research_harness.investigation_contracts import validate_runtime, validate_spec
from research_harness.errors import ValidationError


class ConversationError(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)


class ConversationStore:
    """Stores only UI turns and stable object references, never secrets or source bodies."""

    def __init__(self, root: str | Path):
        self.db = sqlite3.connect(Path(root) / "gui-conversations.sqlite", check_same_thread=False)
        self._lock = threading.RLock()
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE IF NOT EXISTS conversations(
            conversation_id TEXT PRIMARY KEY, library_id TEXT NOT NULL, collection_id TEXT NOT NULL,
            executor TEXT NOT NULL, fixture_id TEXT, status TEXT NOT NULL, spec_json TEXT, runtime_json TEXT,
            run_id TEXT, command_id TEXT, execution_key TEXT, api_config_json TEXT, created REAL NOT NULL, updated REAL NOT NULL)""")
        self.db.execute("CREATE TABLE IF NOT EXISTS conversation_replays(key TEXT PRIMARY KEY, digest TEXT NOT NULL, result_json TEXT NOT NULL)")
        self.db.execute("""CREATE TABLE IF NOT EXISTS conversation_messages(
            message_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, turn_id TEXT NOT NULL,
            request_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, refs_json TEXT NOT NULL,
            created REAL NOT NULL, digest TEXT NOT NULL DEFAULT '', UNIQUE(conversation_id, request_id))""")
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(conversations)")}
        if "fixture_id" not in columns: self.db.execute("ALTER TABLE conversations ADD COLUMN fixture_id TEXT")
        if "execution_key" not in columns: self.db.execute("ALTER TABLE conversations ADD COLUMN execution_key TEXT")
        if "api_config_json" not in columns: self.db.execute("ALTER TABLE conversations ADD COLUMN api_config_json TEXT")
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(conversation_messages)")}
        if "digest" not in columns: self.db.execute("ALTER TABLE conversation_messages ADD COLUMN digest TEXT NOT NULL DEFAULT ''")
        self.db.execute("""CREATE TABLE IF NOT EXISTS conversation_tools(
            tool_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, turn_id TEXT NOT NULL,
            operation TEXT NOT NULL, status TEXT NOT NULL, object_refs_json TEXT NOT NULL,
            error_code TEXT, created REAL NOT NULL)""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS external_turns(
            conversation_id TEXT NOT NULL, turn_id TEXT NOT NULL, state TEXT NOT NULL,
            actor TEXT, lease_until REAL, claim_id TEXT, reply_message_id TEXT,
            acked_at REAL, updated REAL NOT NULL,
            PRIMARY KEY(conversation_id, turn_id))""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS external_replays(
            conversation_id TEXT NOT NULL, turn_id TEXT NOT NULL, action TEXT NOT NULL,
            request_id TEXT NOT NULL, digest TEXT NOT NULL, result_json TEXT NOT NULL,
            PRIMARY KEY(conversation_id, turn_id, action, request_id))""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS conversation_planning_calls(
            conversation_id TEXT NOT NULL, request_id TEXT NOT NULL, status TEXT NOT NULL,
            usage_json TEXT, error_code TEXT, created REAL NOT NULL, updated REAL NOT NULL,
            PRIMARY KEY(conversation_id, request_id))""")
        self.db.commit()

    def close(self):
        self.db.close()

    @staticmethod
    def _idempotency_digest(body: dict) -> str:
        return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()

    def _public(self, row: sqlite3.Row) -> dict:
        return {"conversation_id": row["conversation_id"], "library_id": row["library_id"],
                "collection_id": row["collection_id"], "executor": row["executor"], "fixture_id": row["fixture_id"],
                "status": row["status"], "run_id": row["run_id"], "command_id": row["command_id"],
                "api": self._api_public(row),
                "created_at": row["created"], "updated_at": row["updated"]}

    def _api_public(self, row: sqlite3.Row) -> dict | None:
        if not row["api_config_json"]:
            return None
        config = json.loads(row["api_config_json"])
        rows = self.db.execute("SELECT status,usage_json FROM conversation_planning_calls WHERE conversation_id=?", (row["conversation_id"],)).fetchall()
        used = sum(1 for item in rows if item["status"] in {"reserved", "accepted", "unknown", "failed"})
        usage_known = bool(rows) and all(item["status"] == "accepted" and item["usage_json"] is not None for item in rows)
        return {"provider": config["provider"], "model": config["model"], "planning_calls": used,
                "max_planning_calls": config["max_planning_calls"], "total_model_calls": config["total_model_calls"],
                "remaining_model_calls": max(0, config["total_model_calls"] - used),
                "usage": "known" if usage_known else "UNKNOWN"}

    def create(self, library_id: str, collection_id: str, executor: str, fixture_id: str | None, key: str, body: dict, api_config: dict | None = None) -> dict:
        if executor not in {"scripted", "api", "external"}:
            raise ConversationError("RH_GUI_CONVERSATION_EXECUTOR", "conversation executor is not supported")
        if not isinstance(key, str) or not key:
            raise ConversationError("RH_GUI_CONVERSATION_IDEMPOTENCY", "idempotency key is required")
        digest = self._idempotency_digest(body)
        prior = self.db.execute("SELECT digest,result_json FROM conversation_replays WHERE key=?", (key,)).fetchone()
        if prior:
            if prior["digest"] != digest:
                raise ConversationError("RH_GUI_IDEMPOTENCY_CONFLICT", "idempotency key conflict")
            return json.loads(prior["result_json"])
        ident, now = "con-" + uuid.uuid4().hex, time.time()
        self.db.execute("INSERT INTO conversations(conversation_id,library_id,collection_id,executor,fixture_id,status,spec_json,runtime_json,run_id,command_id,execution_key,api_config_json,created,updated) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (ident, library_id, collection_id, executor, fixture_id, "awaiting_input", None, None, None, None, None, json.dumps(api_config, ensure_ascii=False) if api_config else None, now, now))
        result = self._public(self.db.execute("SELECT * FROM conversations WHERE conversation_id=?", (ident,)).fetchone())
        self.db.execute("INSERT INTO conversation_replays VALUES (?,?,?)", (key, digest, json.dumps(result, ensure_ascii=False)))
        self.db.commit()
        return result

    def list(self) -> list[dict]:
        return [self._public(row) for row in self.db.execute("SELECT * FROM conversations ORDER BY updated DESC,conversation_id DESC")]

    def get(self, ident: str) -> dict:
        row = self.db.execute("SELECT * FROM conversations WHERE conversation_id=?", (ident,)).fetchone()
        if not row:
            raise ConversationError("RH_GUI_CONVERSATION_NOT_FOUND", "conversation is not available in this workspace")
        result = self._public(row)
        result["messages"] = [{"message_id": item["message_id"], "turn_id": item["turn_id"], "request_id": item["request_id"], "role": item["role"], "content": item["content"], "refs": json.loads(item["refs_json"]), "created_at": item["created"]}
                              # rowid is SQLite's persisted insertion sequence. Use it
                              # as the tie-breaker because one turn writes its user
                              # and assistant messages with the same timestamp.
                              for item in self.db.execute("SELECT * FROM conversation_messages WHERE conversation_id=? ORDER BY created,rowid", (ident,))]
        result["tool_results"] = [{"tool_id": item["tool_id"], "turn_id": item["turn_id"], "operation": item["operation"], "status": item["status"], "object_refs": json.loads(item["object_refs_json"]), "error_code": item["error_code"], "created_at": item["created"]}
                                for item in self.db.execute("SELECT * FROM conversation_tools WHERE conversation_id=? ORDER BY created,tool_id", (ident,))]
        return result

    @staticmethod
    def _api_config_is_not_expanded(previous: dict, candidate: dict) -> bool:
        if previous["provider"] != candidate["provider"] or previous["model"] != candidate["model"]:
            return False
        for name in ("max_planning_calls", "max_output_tokens", "timeout_seconds", "total_model_calls"):
            if candidate[name] > previous[name]:
                return False
        old_runtime, new_runtime = previous["runtime_template"], candidate["runtime_template"]
        if any(old_runtime.get(name) != new_runtime.get(name) for name in ("data_mode", "sources", "allow_network")):
            return False
        return not any(value > old_runtime["budget"].get(name, -1) for name, value in new_runtime["budget"].items())

    def switch_executor(self, ident: str, executor: str, fixture_id: str | None, api_config: dict | None, key: str, body: dict, *, execution_busy: bool) -> dict:
        """Change delivery mode while retaining the conversation transcript and accounting links."""
        if executor not in {"scripted", "api", "external"}:
            raise ConversationError("RH_GUI_CONVERSATION_EXECUTOR", "conversation executor is not supported")
        if executor == "scripted" and fixture_id != "synthetic-d19":
            raise ConversationError("RH_GUI_SCRIPTED_FIXTURE", "scripted conversations require the synthetic-d19 fixture")
        if executor in {"api", "external"} and fixture_id is not None:
            raise ConversationError("RH_GUI_CONVERSATION_REQUEST", "selected executor does not accept a scripted fixture")
        if executor == "api" and api_config is None:
            raise ConversationError("RH_GUI_API_CONFIG", "API executor requires a complete API configuration")
        if executor != "api" and api_config is not None:
            raise ConversationError("RH_GUI_CONVERSATION_REQUEST", "only API executor accepts API configuration")
        if not isinstance(key, str) or not key:
            raise ConversationError("RH_GUI_CONVERSATION_IDEMPOTENCY", "idempotency key is required")
        replay_key = "executor:" + ident + ":" + key
        digest = self._idempotency_digest(body)
        with self._lock:
            prior = self.db.execute("SELECT digest,result_json FROM conversation_replays WHERE key=?", (replay_key,)).fetchone()
            if prior:
                if prior["digest"] != digest:
                    raise ConversationError("RH_GUI_IDEMPOTENCY_CONFLICT", "idempotency key conflict")
                return json.loads(prior["result_json"])
            row = self.db.execute("SELECT * FROM conversations WHERE conversation_id=?", (ident,)).fetchone()
            if not row:
                raise ConversationError("RH_GUI_CONVERSATION_NOT_FOUND", "conversation is not available in this workspace")
            pending = self.db.execute("SELECT 1 FROM external_turns WHERE conversation_id=? AND state != 'acked'", (ident,)).fetchone()
            if pending:
                raise ConversationError("RH_GUI_EXECUTOR_SWITCH_EXTERNAL_PENDING", "external turn must be acknowledged before changing executor")
            if execution_busy or row["status"] in {"queued", "running", "stop_requested"}:
                raise ConversationError("RH_GUI_EXECUTOR_SWITCH_BUSY", "conversation has an active or queued command")
            previous = json.loads(row["api_config_json"]) if row["api_config_json"] else None
            if executor == "api" and previous and not self._api_config_is_not_expanded(previous, api_config):
                raise ConversationError("RH_GUI_API_CONFIG_EXPANSION", "API executor configuration cannot expand a conversation's prior limits or scope")
            now = time.time()
            self.db.execute("UPDATE conversations SET executor=?,fixture_id=?,api_config_json=COALESCE(?,api_config_json),updated=? WHERE conversation_id=?", (executor, fixture_id, json.dumps(api_config, ensure_ascii=False) if api_config else None, now, ident))
            value = self._public(self.db.execute("SELECT * FROM conversations WHERE conversation_id=?", (ident,)).fetchone())
            self.db.execute("INSERT INTO conversation_replays VALUES (?,?,?)", (replay_key, digest, json.dumps(value, ensure_ascii=False)))
            self.db.commit()
            return value

    def submit_turn(self, ident: str, request_id: str, content: str, spec: dict | None, runtime: dict | None, *, reply: str | None = None, forced_status: str | None = None) -> dict:
        if not isinstance(request_id, str) or not request_id or len(request_id) > 256:
            raise ConversationError("RH_GUI_TURN_IDENTITY", "turn request identity is invalid")
        if not isinstance(content, str) or not content.strip() or len(content) > 20000:
            raise ConversationError("RH_GUI_TURN_CONTENT", "turn content is invalid")
        row = self.db.execute("SELECT * FROM conversations WHERE conversation_id=?", (ident,)).fetchone()
        if not row: raise ConversationError("RH_GUI_CONVERSATION_NOT_FOUND", "conversation is not available in this workspace")
        digest = self._idempotency_digest({"content": content.strip(), "research_spec": spec, "runtime": runtime})
        existing = self.db.execute("SELECT digest FROM conversation_messages WHERE conversation_id=? AND request_id=? AND role='user'", (ident, request_id)).fetchone()
        if existing:
            if existing["digest"] != digest: raise ConversationError("RH_GUI_TURN_CONFLICT", "turn request identity was reused with different content or research inputs")
            return self.get(ident)
        turn_id, now = "turn-" + uuid.uuid4().hex, time.time()
        self.db.execute("INSERT INTO conversation_messages(message_id,conversation_id,turn_id,request_id,role,content,refs_json,created,digest) VALUES (?,?,?,?,?,?,?,?,?)", ("msg-" + uuid.uuid4().hex, ident, turn_id, request_id, "user", content.strip(), "[]", now, digest))
        missing = []
        if not isinstance(spec, dict): missing.append("research_spec")
        if not isinstance(runtime, dict): missing.append("runtime")
        if not missing:
            try:
                validate_spec(spec); validate_runtime(runtime)
            except ValidationError:
                missing.append("valid research_spec/runtime")
        if forced_status:
            status = forced_status
            reply = reply or "当前执行器尚未形成可执行研究规格。"
        elif missing:
            status, reply = "awaiting_clarification", "需要补充：" + "、".join(missing) + "。仅讨论不会创建调查任务。"
        else:
            status, reply = "ready", "研究规格已通过本地校验。请显式执行后才会创建调查任务。"
            self.db.execute("UPDATE conversations SET spec_json=?,runtime_json=? WHERE conversation_id=?", (json.dumps(spec, ensure_ascii=False), json.dumps(runtime, ensure_ascii=False), ident))
        self.db.execute("INSERT INTO conversation_messages(message_id,conversation_id,turn_id,request_id,role,content,refs_json,created,digest) VALUES (?,?,?,?,?,?,?,?,?)", ("msg-" + uuid.uuid4().hex, ident, turn_id, "assistant:" + request_id, "assistant", reply, "[]", now, ""))
        self.db.execute("UPDATE conversations SET status=?,updated=? WHERE conversation_id=?", (status, now, ident)); self.db.commit()
        return self.get(ident)

    def begin_api_turn(self, ident: str, request_id: str, content: str) -> tuple[dict, dict | None]:
        """Persist and reserve one paid planning attempt before any HTTP request."""
        if not isinstance(request_id, str) or not request_id or len(request_id) > 256:
            raise ConversationError("RH_GUI_TURN_IDENTITY", "turn request identity is invalid")
        if not isinstance(content, str) or not content.strip() or len(content) > 20000:
            raise ConversationError("RH_GUI_TURN_CONTENT", "turn content is invalid")
        with self._lock:
            row = self.db.execute("SELECT * FROM conversations WHERE conversation_id=?", (ident,)).fetchone()
            if not row:
                raise ConversationError("RH_GUI_CONVERSATION_NOT_FOUND", "conversation is not available in this workspace")
            if row["executor"] != "api" or not row["api_config_json"]:
                raise ConversationError("RH_GUI_CONVERSATION_EXECUTOR", "conversation does not use an API executor")
            digest = self._idempotency_digest({"content": content.strip()})
            existing = self.db.execute("SELECT digest FROM conversation_messages WHERE conversation_id=? AND request_id=? AND role='user'", (ident, request_id)).fetchone()
            if existing:
                if existing["digest"] != digest:
                    raise ConversationError("RH_GUI_TURN_CONFLICT", "turn request identity was reused with different content")
                return self.get(ident), None
            config = json.loads(row["api_config_json"])
            calls = self.db.execute("SELECT count(*) FROM conversation_planning_calls WHERE conversation_id=? AND status IN ('reserved','accepted','unknown','failed')", (ident,)).fetchone()[0]
            now = time.time(); turn_id = "turn-" + uuid.uuid4().hex
            self.db.execute("INSERT INTO conversation_messages(message_id,conversation_id,turn_id,request_id,role,content,refs_json,created,digest) VALUES (?,?,?,?,?,?,?,?,?)", ("msg-" + uuid.uuid4().hex, ident, turn_id, request_id, "user", content.strip(), "[]", now, digest))
            if calls >= config["max_planning_calls"] or calls >= config["total_model_calls"]:
                self.db.execute("UPDATE conversations SET status=?,updated=? WHERE conversation_id=?", ("waiting_budget", now, ident))
                self.db.execute("INSERT INTO conversation_messages(message_id,conversation_id,turn_id,request_id,role,content,refs_json,created,digest) VALUES (?,?,?,?,?,?,?,?,?)", ("msg-" + uuid.uuid4().hex, ident, turn_id, "assistant:" + request_id, "assistant", "模型规划额度已用尽；没有发送新的模型请求。", "[]", now, ""))
                self.db.commit()
                return self.get(ident), None
            self.db.execute("INSERT INTO conversation_planning_calls VALUES (?,?,?,?,?,?,?)", (ident, request_id, "reserved", None, None, now, now))
            self.db.execute("UPDATE conversations SET status=?,updated=? WHERE conversation_id=?", ("planning", now, ident))
            self.db.commit()
            return self.get(ident), {"config": config, "content": content.strip(), "request_id": request_id, "planning_calls": calls + 1}

    def finish_api_turn(self, ident: str, request_id: str, *, spec: dict | None = None, runtime: dict | None = None,
                        usage: dict | None = None, error_code: str | None = None, reply: str | None = None) -> dict:
        with self._lock:
            row = self.db.execute("SELECT * FROM conversations WHERE conversation_id=?", (ident,)).fetchone()
            call = self.db.execute("SELECT * FROM conversation_planning_calls WHERE conversation_id=? AND request_id=?", (ident, request_id)).fetchone()
            if not row or not call:
                raise ConversationError("RH_GUI_CONVERSATION_NOT_FOUND", "planning call is not available")
            if call["status"] != "reserved":
                return self.get(ident)
            now = time.time()
            if error_code:
                status = "planning_failed"
                text = reply or "模型规划失败；请求用量保持 UNKNOWN，未形成可执行研究规格。"
                call_status, usage_json = "unknown", None
            else:
                try:
                    validate_spec(spec); validate_runtime(runtime)
                except (ValidationError, TypeError):
                    status, text, call_status, usage_json, error_code = "planning_failed", "模型输出未通过本地 schema 校验。", "accepted", json.dumps(usage, ensure_ascii=False) if usage is not None else None, "RH_GUI_API_PLAN_INVALID"
                else:
                    status, text, call_status, usage_json = "ready", "研究规格已通过本地校验。请显式执行后才会创建调查任务。", "accepted", json.dumps(usage, ensure_ascii=False) if usage is not None else None
                    self.db.execute("UPDATE conversations SET spec_json=?,runtime_json=? WHERE conversation_id=?", (json.dumps(spec, ensure_ascii=False), json.dumps(runtime, ensure_ascii=False), ident))
            self.db.execute("UPDATE conversation_planning_calls SET status=?,usage_json=?,error_code=?,updated=? WHERE conversation_id=? AND request_id=?", (call_status, usage_json, error_code, now, ident, request_id))
            self.db.execute("INSERT INTO conversation_messages(message_id,conversation_id,turn_id,request_id,role,content,refs_json,created,digest) VALUES (?,?,?,?,?,?,?,?,?)", ("msg-" + uuid.uuid4().hex, ident, "turn-" + request_id, "assistant:" + request_id, "assistant", text, "[]", now, ""))
            self.db.execute("UPDATE conversations SET status=?,updated=? WHERE conversation_id=?", (status, now, ident)); self.db.commit()
            return self.get(ident)

    def finish_api_help_turn(self, ident: str, request_id: str, content: str, source_ids: list[str], allowed_source_ids: set[str], usage: dict | None) -> dict:
        """Save a bounded product-help reply without creating a research specification."""
        if not isinstance(content, str) or not content.strip() or len(content) > 20000 or not isinstance(source_ids, list) or not source_ids or not all(isinstance(value, str) for value in source_ids):
            raise ConversationError("RH_GUI_API_HELP_INVALID", "help answer is invalid")
        if any(value not in allowed_source_ids for value in source_ids):
            raise ConversationError("RH_GUI_API_HELP_SCOPE", "help answer cited material outside the retrieved help context")
        with self._lock:
            call = self.db.execute("SELECT status FROM conversation_planning_calls WHERE conversation_id=? AND request_id=?", (ident, request_id)).fetchone()
            user = self.db.execute("SELECT turn_id FROM conversation_messages WHERE conversation_id=? AND request_id=? AND role='user'", (ident, request_id)).fetchone()
            if not call or not user:
                raise ConversationError("RH_GUI_CONVERSATION_NOT_FOUND", "planning call is not available")
            if call["status"] != "reserved":
                return self.get(ident)
            now = time.time()
            self.db.execute("UPDATE conversation_planning_calls SET status=?,usage_json=?,updated=? WHERE conversation_id=? AND request_id=?", ("accepted", json.dumps(usage, ensure_ascii=False) if usage is not None else None, now, ident, request_id))
            self.db.execute("INSERT INTO conversation_messages(message_id,conversation_id,turn_id,request_id,role,content,refs_json,created,digest) VALUES (?,?,?,?,?,?,?,?,?)", ("msg-" + uuid.uuid4().hex, ident, user["turn_id"], "assistant:" + request_id, "assistant", content.strip(), json.dumps({"help_source_ids": source_ids}, ensure_ascii=False), now, ""))
            self.db.execute("UPDATE conversations SET status=?,updated=? WHERE conversation_id=?", ("awaiting_input", now, ident)); self.db.commit()
            return self.get(ident)

    def submit_external_turn(self, ident: str, request_id: str, content: str) -> dict:
        """Persist a GUI turn for a connected external executor without inventing a reply."""
        if not isinstance(request_id, str) or not request_id or len(request_id) > 256:
            raise ConversationError("RH_GUI_TURN_IDENTITY", "turn request identity is invalid")
        if not isinstance(content, str) or not content.strip() or len(content) > 20000:
            raise ConversationError("RH_GUI_TURN_CONTENT", "turn content is invalid")
        row = self.db.execute("SELECT * FROM conversations WHERE conversation_id=?", (ident,)).fetchone()
        if not row:
            raise ConversationError("RH_GUI_CONVERSATION_NOT_FOUND", "conversation is not available in this workspace")
        if row["executor"] != "external":
            raise ConversationError("RH_GUI_CONVERSATION_EXECUTOR", "conversation does not use an external executor")
        digest = self._idempotency_digest({"content": content.strip()})
        existing = self.db.execute("SELECT digest FROM conversation_messages WHERE conversation_id=? AND request_id=? AND role='user'", (ident, request_id)).fetchone()
        if existing:
            if existing["digest"] != digest:
                raise ConversationError("RH_GUI_TURN_CONFLICT", "turn request identity was reused with different content")
            return self.get(ident)
        outstanding = self.db.execute("SELECT 1 FROM external_turns WHERE conversation_id=? AND state != 'acked'", (ident,)).fetchone()
        if outstanding:
            raise ConversationError("RH_GUI_EXTERNAL_TURN_PENDING", "an external executor turn is still awaiting acknowledgement")
        turn_id, now = "turn-" + uuid.uuid4().hex, time.time()
        self.db.execute("INSERT INTO conversation_messages(message_id,conversation_id,turn_id,request_id,role,content,refs_json,created,digest) VALUES (?,?,?,?,?,?,?,?,?)", ("msg-" + uuid.uuid4().hex, ident, turn_id, request_id, "user", content.strip(), "[]", now, digest))
        self.db.execute("INSERT INTO external_turns(conversation_id,turn_id,state,actor,lease_until,claim_id,reply_message_id,acked_at,updated) VALUES (?,?,?,NULL,NULL,NULL,NULL,NULL,?)", (ident, turn_id, "pending", now))
        self.db.execute("UPDATE conversations SET status=?,updated=? WHERE conversation_id=?", ("waiting_external", now, ident))
        self.db.commit()
        return self.get(ident)

    def _external_replay(self, ident: str, turn_id: str, action: str, request_id: str, body: dict):
        if not isinstance(request_id, str) or not request_id or len(request_id) > 256:
            raise ConversationError("RH_GUI_EXTERNAL_IDENTITY", "external request identity is invalid")
        digest = self._idempotency_digest(body)
        prior = self.db.execute("SELECT digest,result_json FROM external_replays WHERE conversation_id=? AND turn_id=? AND action=? AND request_id=?", (ident, turn_id, action, request_id)).fetchone()
        if prior:
            if prior["digest"] != digest:
                raise ConversationError("RH_GUI_EXTERNAL_CONFLICT", "external request identity was reused with different input")
            return digest, json.loads(prior["result_json"])
        return digest, None

    def _save_external_replay(self, ident: str, turn_id: str, action: str, request_id: str, digest: str, result: dict) -> dict:
        self.db.execute("INSERT INTO external_replays VALUES (?,?,?,?,?,?)", (ident, turn_id, action, request_id, digest, json.dumps(result, ensure_ascii=False)))
        self.db.commit()
        return result

    def list_pending_external(self, now: float | None = None) -> list[dict]:
        now = time.time() if now is None else now
        rows = self.db.execute("""SELECT t.*, c.library_id,c.collection_id,m.content,m.request_id
            FROM external_turns t JOIN conversations c ON c.conversation_id=t.conversation_id
            JOIN conversation_messages m ON m.conversation_id=t.conversation_id AND m.turn_id=t.turn_id AND m.role='user'
            WHERE t.state='pending' OR (t.state='claimed' AND t.lease_until <= ?) ORDER BY t.updated,t.turn_id""", (now,))
        return [{"conversation_id": r["conversation_id"], "turn_id": r["turn_id"], "request_id": r["request_id"], "content": r["content"], "library_id": r["library_id"], "collection_id": r["collection_id"], "state": "pending" if r["state"] == "pending" else "lease_expired"} for r in rows]

    def claim_external(self, ident: str, turn_id: str, actor: str, request_id: str, lease_seconds: int = 30) -> dict:
        if not isinstance(actor, str) or not actor or len(actor) > 256:
            raise ConversationError("RH_GUI_EXTERNAL_ACTOR", "external actor is invalid")
        if not isinstance(lease_seconds, int) or not 5 <= lease_seconds <= 300:
            raise ConversationError("RH_GUI_EXTERNAL_LEASE", "lease duration is invalid")
        with self._lock:
            digest, replay = self._external_replay(ident, turn_id, "claim", request_id, {"actor": actor, "lease_seconds": lease_seconds})
            if replay is not None: return replay
            row = self.db.execute("SELECT * FROM external_turns WHERE conversation_id=? AND turn_id=?", (ident, turn_id)).fetchone()
            if not row: raise ConversationError("RH_GUI_EXTERNAL_TURN_NOT_FOUND", "external turn is not available")
            now = time.time()
            if row["state"] in {"acked", "replied"}:
                raise ConversationError("RH_GUI_EXTERNAL_TURN_ACKED", "external turn is no longer available for a claim")
            if row["state"] == "claimed" and row["lease_until"] > now and row["actor"] != actor:
                raise ConversationError("RH_GUI_EXTERNAL_LEASE_HELD", "external turn is currently leased to another actor")
            claim_id = "claim-" + uuid.uuid4().hex
            until = now + lease_seconds
            self.db.execute("UPDATE external_turns SET state='claimed',actor=?,lease_until=?,claim_id=?,updated=? WHERE conversation_id=? AND turn_id=?", (actor, until, claim_id, now, ident, turn_id))
            self.db.execute("UPDATE conversations SET status=?,updated=? WHERE conversation_id=?", ("external_working", now, ident))
            return self._save_external_replay(ident, turn_id, "claim", request_id, digest, {"conversation_id": ident, "turn_id": turn_id, "claim_id": claim_id, "lease_until": until, "state": "claimed"})

    def _claimed_external(self, ident: str, turn_id: str, actor: str, claim_id: str):
        row = self.db.execute("SELECT * FROM external_turns WHERE conversation_id=? AND turn_id=?", (ident, turn_id)).fetchone()
        if not row: raise ConversationError("RH_GUI_EXTERNAL_TURN_NOT_FOUND", "external turn is not available")
        if row["state"] not in {"claimed", "replied"} or row["actor"] != actor or row["claim_id"] != claim_id or row["lease_until"] <= time.time():
            raise ConversationError("RH_GUI_EXTERNAL_LEASE", "external claim is absent, expired, or belongs to another actor")
        return row

    def external_context(self, ident: str, turn_id: str, actor: str, claim_id: str) -> dict:
        self._claimed_external(ident, turn_id, actor, claim_id)
        value = self.get(ident)
        return {"conversation_id": ident, "turn_id": turn_id, "conversation": value}

    def external_progress(self, ident: str, turn_id: str, actor: str, claim_id: str, request_id: str, content: str, refs: dict) -> dict:
        if not isinstance(content, str) or not content.strip() or len(content) > 20000 or not isinstance(refs, dict):
            raise ConversationError("RH_GUI_EXTERNAL_PROGRESS", "external progress is invalid")
        with self._lock:
            digest, replay = self._external_replay(ident, turn_id, "progress", request_id, {"actor": actor, "claim_id": claim_id, "content": content.strip(), "refs": refs})
            if replay is not None: return replay
            self._claimed_external(ident, turn_id, actor, claim_id)
            now = time.time()
            message_id = "msg-" + uuid.uuid4().hex
            self.db.execute("INSERT INTO conversation_messages(message_id,conversation_id,turn_id,request_id,role,content,refs_json,created,digest) VALUES (?,?,?,?,?,?,?,?,?)", (message_id, ident, turn_id, "progress:" + request_id, "progress", content.strip(), json.dumps(refs, ensure_ascii=False), now, digest))
            return self._save_external_replay(ident, turn_id, "progress", request_id, digest, {"message_id": message_id, "state": "claimed"})

    def external_reply(self, ident: str, turn_id: str, actor: str, claim_id: str, request_id: str, content: str, refs: dict) -> dict:
        if not isinstance(content, str) or not content.strip() or len(content) > 20000 or not isinstance(refs, dict):
            raise ConversationError("RH_GUI_EXTERNAL_REPLY", "external reply is invalid")
        with self._lock:
            digest, replay = self._external_replay(ident, turn_id, "reply", request_id, {"actor": actor, "claim_id": claim_id, "content": content.strip(), "refs": refs})
            if replay is not None: return replay
            self._claimed_external(ident, turn_id, actor, claim_id)
            now = time.time(); message_id = "msg-" + uuid.uuid4().hex
            self.db.execute("INSERT INTO conversation_messages(message_id,conversation_id,turn_id,request_id,role,content,refs_json,created,digest) VALUES (?,?,?,?,?,?,?,?,?)", (message_id, ident, turn_id, "reply:" + request_id, "assistant", content.strip(), json.dumps(refs, ensure_ascii=False), now, digest))
            self.db.execute("UPDATE external_turns SET state='replied',reply_message_id=?,updated=? WHERE conversation_id=? AND turn_id=?", (message_id, now, ident, turn_id))
            self.db.execute("UPDATE conversations SET status=?,updated=? WHERE conversation_id=?", ("external_reply_ready", now, ident))
            return self._save_external_replay(ident, turn_id, "reply", request_id, digest, {"message_id": message_id, "state": "replied"})

    def external_ack(self, ident: str, turn_id: str, actor: str, claim_id: str, request_id: str) -> dict:
        with self._lock:
            digest, replay = self._external_replay(ident, turn_id, "ack", request_id, {"actor": actor, "claim_id": claim_id})
            if replay is not None: return replay
            row = self._claimed_external(ident, turn_id, actor, claim_id)
            if row["state"] != "replied": raise ConversationError("RH_GUI_EXTERNAL_ACK", "external reply must be submitted before acknowledgement")
            now = time.time()
            self.db.execute("UPDATE external_turns SET state='acked',acked_at=?,updated=? WHERE conversation_id=? AND turn_id=?", (now, now, ident, turn_id))
            self.db.execute("UPDATE conversations SET status=?,updated=? WHERE conversation_id=?", ("awaiting_input", now, ident))
            return self._save_external_replay(ident, turn_id, "ack", request_id, digest, {"conversation_id": ident, "turn_id": turn_id, "state": "acked"})

    def ready(self, ident: str) -> tuple[dict, dict, dict]:
        row = self.db.execute("SELECT * FROM conversations WHERE conversation_id=?", (ident,)).fetchone()
        if not row: raise ConversationError("RH_GUI_CONVERSATION_NOT_FOUND", "conversation is not available in this workspace")
        if row["status"] != "ready" or not row["spec_json"] or not row["runtime_json"]:
            raise ConversationError("RH_GUI_CONVERSATION_NOT_READY", "conversation needs a validated research spec before execution")
        return self._public(row), json.loads(row["spec_json"]), json.loads(row["runtime_json"])

    def execution_key(self, ident: str) -> str | None:
        row = self.db.execute("SELECT execution_key FROM conversations WHERE conversation_id=?", (ident,)).fetchone()
        if not row: raise ConversationError("RH_GUI_CONVERSATION_NOT_FOUND", "conversation is not available in this workspace")
        return row["execution_key"]

    def bind_execution(self, ident: str, run_id: str, command_id: str | None, status: str, execution_key: str | None = None) -> None:
        self.db.execute("UPDATE conversations SET run_id=?,command_id=?,status=?,execution_key=COALESCE(?,execution_key),updated=? WHERE conversation_id=?", (run_id, command_id, status, execution_key, time.time(), ident)); self.db.commit()

    def set_status(self, ident: str, status: str) -> dict:
        if not self.db.execute("SELECT 1 FROM conversations WHERE conversation_id=?", (ident,)).fetchone():
            raise ConversationError("RH_GUI_CONVERSATION_NOT_FOUND", "conversation is not available in this workspace")
        self.db.execute("UPDATE conversations SET status=?,updated=? WHERE conversation_id=?", (status, time.time(), ident)); self.db.commit()
        return self.get(ident)

    def tool_result(self, ident: str, turn_id: str, operation: str, status: str, refs: dict, error_code: str | None = None) -> None:
        self.db.execute("INSERT INTO conversation_tools VALUES (?,?,?,?,?,?,?,?)", ("tool-" + uuid.uuid4().hex, ident, turn_id, operation, status, json.dumps(refs, ensure_ascii=False), error_code, time.time())); self.db.commit()
