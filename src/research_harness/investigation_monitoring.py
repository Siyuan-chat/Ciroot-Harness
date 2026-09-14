"""Offline durable state for monitor cycles; this module schedules no work."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from .errors import BusyError, NotFoundError, PreflightError, ValidationError


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


class MonitorStore:
    """SQLite-backed monitor facts, watermarks, and cross-cycle task budget."""

    def __init__(self, workspace: str | Path):
        root = Path(workspace); root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(root / "monitoring.sqlite", isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS monitors (
          id TEXT PRIMARY KEY, profile TEXT NOT NULL, monitor_spec TEXT NOT NULL, runtime TEXT NOT NULL,
          fingerprint TEXT NOT NULL, status TEXT NOT NULL, profile_revision INTEGER NOT NULL,
          rule_version TEXT NOT NULL, task_reserved INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, updated REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS profile_versions (
          monitor_id TEXT NOT NULL, revision INTEGER NOT NULL, profile TEXT NOT NULL, monitor_spec TEXT NOT NULL,
          runtime TEXT NOT NULL, created REAL NOT NULL, PRIMARY KEY(monitor_id, revision));
        CREATE TABLE IF NOT EXISTS cycles (
          id TEXT PRIMARY KEY, monitor_id TEXT NOT NULL, cycle_key TEXT NOT NULL, window_start TEXT NOT NULL,
          window_end TEXT NOT NULL, rule_version TEXT NOT NULL, status TEXT NOT NULL, complete INTEGER NOT NULL DEFAULT 0, watermark TEXT,
          coverage TEXT, run_id TEXT, created REAL NOT NULL, updated REAL NOT NULL, UNIQUE(monitor_id, cycle_key));
        CREATE TABLE IF NOT EXISTS documents (
          monitor_id TEXT NOT NULL, document_id TEXT NOT NULL, document_version TEXT NOT NULL,
          content_sha256 TEXT NOT NULL, published_at TEXT, first_seen REAL NOT NULL,
          PRIMARY KEY(monitor_id, document_id, document_version, content_sha256));
        CREATE TABLE IF NOT EXISTS cycle_documents (
          cycle_id TEXT NOT NULL, document_id TEXT NOT NULL, document_version TEXT NOT NULL, content_sha256 TEXT NOT NULL,
          is_new_publication INTEGER NOT NULL, first_discovery INTEGER NOT NULL,
          PRIMARY KEY(cycle_id, document_id, document_version, content_sha256));
        CREATE TABLE IF NOT EXISTS judgments (
          monitor_id TEXT NOT NULL, document_id TEXT NOT NULL, content_sha256 TEXT NOT NULL,
          rule_version TEXT NOT NULL, judgment_ref TEXT NOT NULL, judged_at REAL NOT NULL,
          PRIMARY KEY(monitor_id, document_id, content_sha256, rule_version));
        """)

    def close(self) -> None:
        self.db.close()

    def __enter__(self): return self
    def __exit__(self, *_: Any) -> None: self.close()

    def _monitor(self, monitor_id: str) -> sqlite3.Row:
        row = self.db.execute("SELECT * FROM monitors WHERE id=?", (monitor_id,)).fetchone()
        if not row: raise NotFoundError()
        return row

    def _budget(self, row: sqlite3.Row) -> dict[str, Any]:
        runtime = json.loads(row["runtime"]); budget = runtime.get("budget", runtime.get("monitor_budget", {}))
        return {"max_cycles": budget.get("max_cycles"), "max_total_tasks": budget.get("max_total_tasks"), "task_reserved": row["task_reserved"]}

    def create(self, profile: dict[str, Any], monitor_spec: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
        if not all(isinstance(value, dict) for value in (profile, monitor_spec, runtime)):
            raise ValidationError("profile, monitor_spec and runtime must be objects")
        rule_version = profile.get("rule_version")
        if not rule_version: raise ValidationError("profile.rule_version is required")
        monitor_id = monitor_spec.get("monitor_id") or "mon-" + uuid.uuid4().hex[:12]
        fingerprint = _fingerprint({"profile": profile, "monitor_spec": monitor_spec, "runtime": runtime})
        prior = self.db.execute("SELECT * FROM monitors WHERE id=?", (monitor_id,)).fetchone()
        if prior:
            if prior["fingerprint"] != fingerprint: raise ValidationError("monitor_id already exists with different facts")
            return self.status(monitor_id)
        now = time.time()
        self.db.execute("INSERT INTO monitors VALUES (?,?,?,?,?,?,?,?,?,?,?)", (monitor_id, _json(profile), _json(monitor_spec), _json(runtime), fingerprint, "active", 1, str(rule_version), 0, now, now))
        self.db.execute("INSERT INTO profile_versions VALUES (?,?,?,?,?,?)", (monitor_id, 1, _json(profile), _json(monitor_spec), _json(runtime), now))
        return self.status(monitor_id)

    def update_profile(self, monitor_id: str, profile: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(profile, dict) or not profile.get("rule_version"): raise ValidationError("profile.rule_version is required")
        row = self._monitor(monitor_id)
        if _json(profile) == row["profile"]: return self.status(monitor_id)
        revision, now = row["profile_revision"] + 1, time.time()
        self.db.execute("UPDATE monitors SET profile=?,rule_version=?,profile_revision=?,updated=? WHERE id=?", (_json(profile), str(profile["rule_version"]), revision, now, monitor_id))
        self.db.execute("INSERT INTO profile_versions VALUES (?,?,?,?,?,?)", (monitor_id, revision, _json(profile), row["monitor_spec"], row["runtime"], now))
        return self.status(monitor_id)

    def get_configuration(self, monitor_id: str, revision: int | None = None) -> dict[str, Any]:
        row = self._monitor(monitor_id); revision = row["profile_revision"] if revision is None else revision
        saved = self.db.execute("SELECT * FROM profile_versions WHERE monitor_id=? AND revision=?", (monitor_id, revision)).fetchone()
        if not saved: raise NotFoundError()
        return {"monitor_id": monitor_id, "profile_revision": revision, "profile": json.loads(saved["profile"]), "monitor_spec": json.loads(saved["monitor_spec"]), "runtime": json.loads(saved["runtime"])}

    def status(self, monitor_id: str | None = None) -> dict[str, Any]:
        if monitor_id is None:
            return {"monitors": [self.status(row["id"]) for row in self.db.execute("SELECT id FROM monitors ORDER BY created")]}
        row = self._monitor(monitor_id); cycles = []
        for cycle in self.db.execute("SELECT * FROM cycles WHERE monitor_id=? ORDER BY created", (monitor_id,)):
            pending = self.db.execute("""SELECT cd.document_id,cd.document_version FROM cycle_documents cd
                WHERE cd.cycle_id=? AND NOT EXISTS (SELECT 1 FROM judgments j WHERE j.monitor_id=? AND j.document_id=cd.document_id AND j.content_sha256=cd.content_sha256 AND j.rule_version=?)
                ORDER BY cd.document_id,cd.document_version""", (cycle["id"], monitor_id, cycle["rule_version"])).fetchall()
            documents = self.db.execute("""SELECT cd.document_id,cd.document_version,cd.is_new_publication,cd.first_discovery,d.published_at
                FROM cycle_documents cd JOIN documents d ON d.monitor_id=? AND d.document_id=cd.document_id AND d.document_version=cd.document_version AND d.content_sha256=cd.content_sha256
                WHERE cd.cycle_id=? ORDER BY cd.document_id,cd.document_version""", (monitor_id, cycle["id"])).fetchall()
            cycles.append({"cycle_id": cycle["id"], "cycle_key": cycle["cycle_key"], "rule_version": cycle["rule_version"], "status": cycle["status"], "complete": bool(cycle["complete"]), "window_start": cycle["window_start"], "window_end": cycle["window_end"], "watermark": json.loads(cycle["watermark"]) if cycle["watermark"] else None, "coverage": json.loads(cycle["coverage"]) if cycle["coverage"] else None, "run_id": cycle["run_id"], "judgment_backlog": [dict(item) for item in pending], "documents": [{**dict(item), "published_at": item["published_at"] if item["published_at"] is not None else "unknown"} for item in documents]})
        gaps = [{"cycle_id": item["cycle_id"], "window_start": item["window_start"], "window_end": item["window_end"], "status": item["status"]} for item in cycles if not item["complete"]]
        return {"monitor_id": row["id"], "status": row["status"], "profile_revision": row["profile_revision"], "rule_version": row["rule_version"], "budget": self._budget(row), "cycles": cycles, "uncovered_windows": gaps}

    def pause(self, monitor_id: str) -> dict[str, Any]:
        self._monitor(monitor_id); self.db.execute("UPDATE monitors SET status='paused',updated=? WHERE id=?", (time.time(), monitor_id)); return self.status(monitor_id)
    def resume(self, monitor_id: str) -> dict[str, Any]:
        self._monitor(monitor_id); self.db.execute("UPDATE monitors SET status='active',updated=? WHERE id=?", (time.time(), monitor_id)); return self.status(monitor_id)

    def begin_cycle(self, monitor_id: str, cycle_key: str, window_start: str, window_end: str) -> dict[str, Any]:
        row = self._monitor(monitor_id)
        existing = self.db.execute("SELECT * FROM cycles WHERE monitor_id=? AND cycle_key=?", (monitor_id, cycle_key)).fetchone()
        if existing:
            if existing["window_start"] != window_start or existing["window_end"] != window_end: raise ValidationError("cycle_key already has a different window")
            return {"cycle_id": existing["id"], "monitor_id": monitor_id, "cycle_key": cycle_key, "status": existing["status"], "window_start": existing["window_start"], "window_end": existing["window_end"], "reused": True}
        if row["status"] != "active": raise PreflightError("monitor is paused")
        if window_start >= window_end: raise ValidationError("cycle window must increase")
        overlap = self.db.execute("SELECT 1 FROM cycles WHERE monitor_id=? AND status='collecting' AND window_start<? AND window_end>?", (monitor_id, window_end, window_start)).fetchone()
        if overlap: raise BusyError("collection window overlaps an active cycle")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            same = self.db.execute("SELECT * FROM cycles WHERE monitor_id=? AND cycle_key=?", (monitor_id, cycle_key)).fetchone()
            if same:
                if same["window_start"] != window_start or same["window_end"] != window_end: raise ValidationError("cycle_key already has a different window")
                self.db.execute("COMMIT")
                return {"cycle_id": same["id"], "monitor_id": monitor_id, "cycle_key": cycle_key, "status": same["status"], "window_start": same["window_start"], "window_end": same["window_end"], "reused": True}
            row = self._monitor(monitor_id); maximum = self._budget(row)["max_cycles"]
            count = self.db.execute("SELECT COUNT(*) FROM cycles WHERE monitor_id=?", (monitor_id,)).fetchone()[0]
            if maximum is not None and count >= maximum: raise PreflightError("max_cycles budget exhausted")
            cycle_id, now = "cyc-" + uuid.uuid4().hex[:12], time.time()
            self.db.execute("INSERT INTO cycles VALUES (?,?,?,?,?,?, 'collecting',0,NULL,NULL,NULL,?,?)", (cycle_id, monitor_id, cycle_key, window_start, window_end, row["rule_version"], now, now)); self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK"); raise
        return {"cycle_id": cycle_id, "monitor_id": monitor_id, "cycle_key": cycle_key, "status": "collecting", "window_start": window_start, "window_end": window_end, "reused": False}

    def record_collection(self, cycle_id: str, documents: list[dict[str, Any]], complete: bool, coverage: dict[str, Any]) -> dict[str, Any]:
        cycle = self.db.execute("SELECT * FROM cycles WHERE id=?", (cycle_id,)).fetchone()
        if not cycle: raise NotFoundError()
        if not isinstance(complete, bool): raise ValidationError("complete must be a boolean")
        if not isinstance(documents, list) or not isinstance(coverage, dict): raise ValidationError("documents and coverage have invalid shape")
        if cycle["status"] == "completed":
            incoming = {(str(item.get("document_id")), str(item.get("version")), str(item.get("content_sha256"))) for item in documents if isinstance(item, dict)}
            existing = {(row["document_id"], row["document_version"], row["content_sha256"]) for row in self.db.execute("SELECT document_id,document_version,content_sha256 FROM cycle_documents WHERE cycle_id=?", (cycle_id,))}
            if not complete or incoming != existing or _json(coverage) != cycle["coverage"]: raise ValidationError("completed cycle cannot be changed")
            item = next(value for value in self.status(cycle["monitor_id"])["cycles"] if value["cycle_id"] == cycle_id)
            return {"cycle_id": cycle_id, "status": "completed", "complete": True, "watermark": item["watermark"], "coverage": coverage, "documents": {"stored": len(existing), "new_publications": sum(document["is_new_publication"] for document in item["documents"]), "first_discoveries": sum(document["first_discovery"] for document in item["documents"]), "reused": len(existing), "judgment_backlog": len(item["judgment_backlog"])}}
        if cycle["status"] not in {"collecting", "partial"}: raise PreflightError("cycle is not collecting")
        monitor = self._monitor(cycle["monitor_id"]); stored = new_publications = first_discoveries = reused = 0
        self.db.execute("BEGIN IMMEDIATE")
        try:
            live = self.db.execute("SELECT * FROM cycles WHERE id=?", (cycle_id,)).fetchone()
            if live["status"] == "completed":
                self.db.execute("ROLLBACK")
                return self.record_collection(cycle_id, documents, complete, coverage)
            cycle = live
            for document in documents:
                if not isinstance(document, dict) or not all(document.get(key) for key in ("document_id", "version", "content_sha256")): raise ValidationError("document identity is required")
                doc_id, version, content = str(document["document_id"]), str(document["version"]), str(document["content_sha256"])
                present = self.db.execute("SELECT 1 FROM cycle_documents WHERE cycle_id=? AND document_id=? AND document_version=? AND content_sha256=?", (cycle_id, doc_id, version, content)).fetchone()
                if present: reused += 1; continue
                prior = self.db.execute("SELECT 1 FROM documents WHERE monitor_id=? AND document_id=?", (monitor["id"], doc_id)).fetchone()
                first = prior is None; published = document.get("published_at")
                is_new = bool(published and cycle["window_start"] <= str(published) < cycle["window_end"])
                self.db.execute("INSERT OR IGNORE INTO documents VALUES (?,?,?,?,?,?)", (monitor["id"], doc_id, version, content, published, time.time()))
                self.db.execute("INSERT INTO cycle_documents VALUES (?,?,?,?,?,?)", (cycle_id, doc_id, version, content, int(is_new), int(first)))
                stored += 1; new_publications += int(is_new); first_discoveries += int(first)
            watermark = {"window_end": cycle["window_end"], "coverage": coverage} if complete else None
            self.db.execute("UPDATE cycles SET status=?,complete=?,watermark=COALESCE(?,watermark),coverage=?,updated=? WHERE id=?", ("completed" if complete else "partial", int(complete), _json(watermark) if watermark else None, _json(coverage), time.time(), cycle_id))
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK"); raise
        current = next(item for item in self.status(monitor["id"])["cycles"] if item["cycle_id"] == cycle_id)
        backlog = len(current["judgment_backlog"])
        return {"cycle_id": cycle_id, "status": "completed" if complete else "partial", "complete": complete, "watermark": watermark, "coverage": coverage, "documents": {"stored": stored, "new_publications": new_publications, "first_discoveries": first_discoveries, "reused": reused, "judgment_backlog": backlog}}

    def mark_judged(self, cycle_id: str, document_id: str, document_version: str, judgment_ref: str) -> dict[str, Any]:
        cycle = self.db.execute("SELECT * FROM cycles WHERE id=?", (cycle_id,)).fetchone()
        if not cycle: raise NotFoundError()
        doc = self.db.execute("SELECT * FROM cycle_documents WHERE cycle_id=? AND document_id=? AND document_version=?", (cycle_id, document_id, document_version)).fetchone()
        if not doc: raise NotFoundError()
        monitor = self._monitor(cycle["monitor_id"])
        prior = self.db.execute("SELECT judgment_ref FROM judgments WHERE monitor_id=? AND document_id=? AND content_sha256=? AND rule_version=?", (monitor["id"], document_id, doc["content_sha256"], cycle["rule_version"])).fetchone()
        if prior:
            if prior["judgment_ref"] != judgment_ref: raise ValidationError("conflicting judgment for frozen rule and content")
            return {"cycle_id": cycle_id, "document_id": document_id, "document_version": document_version, "status": "reused", "reused": True}
        self.db.execute("INSERT INTO judgments VALUES (?,?,?,?,?,?)", (monitor["id"], document_id, doc["content_sha256"], cycle["rule_version"], judgment_ref, time.time()))
        return {"cycle_id": cycle_id, "document_id": document_id, "document_version": document_version, "status": "judged", "reused": False}

    def bind_run(self, cycle_id: str, run_id: str) -> dict[str, Any]:
        cycle = self.db.execute("SELECT * FROM cycles WHERE id=?", (cycle_id,)).fetchone()
        if not cycle: raise NotFoundError()
        if cycle["run_id"] and cycle["run_id"] != run_id: raise ValidationError("cycle is already bound to another run")
        self.db.execute("UPDATE cycles SET run_id=?,updated=? WHERE id=?", (run_id, time.time(), cycle_id))
        return {"cycle_id": cycle_id, "run_id": run_id, "reused": bool(cycle["run_id"])}

    def reserve_tasks(self, monitor_id: str, count: int) -> dict[str, Any]:
        if not isinstance(count, int) or count <= 0: raise ValidationError("task count must be positive")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self._monitor(monitor_id); budget = self._budget(row); maximum = budget["max_total_tasks"]
            if maximum is not None and row["task_reserved"] + count > maximum: raise PreflightError("max_total_tasks budget exhausted")
            total = row["task_reserved"] + count
            self.db.execute("UPDATE monitors SET task_reserved=?,updated=? WHERE id=?", (total, time.time(), monitor_id)); self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK"); raise
        return {"monitor_id": monitor_id, "reserved": count, "total_reserved": total, "remaining": None if maximum is None else maximum - total}
