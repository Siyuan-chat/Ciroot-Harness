"""Durable, local human-review queue for investigation monitoring."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any
from .errors import NotFoundError, ValidationError

_RELEVANCE = {"relevant", "irrelevant", "uncertain"}


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class ReviewStore:
    def __init__(self, workspace: str | Path):
        self.root = Path(workspace)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / "investigation-review.sqlite")
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS review_issues (
          issue_id TEXT PRIMARY KEY, monitor_id TEXT NOT NULL, company_id TEXT NOT NULL,
          document_id TEXT NOT NULL, status TEXT NOT NULL, effective_judgment TEXT,
          human_decision TEXT, note TEXT NOT NULL DEFAULT '', created REAL NOT NULL, updated REAL NOT NULL,
          UNIQUE(monitor_id, company_id, document_id)
        );
        CREATE TABLE IF NOT EXISTS review_judgments (
          id INTEGER PRIMARY KEY, issue_id TEXT NOT NULL, fingerprint TEXT NOT NULL UNIQUE,
          document_version TEXT NOT NULL, rule_version TEXT NOT NULL, judgment TEXT NOT NULL,
          evidence_refs TEXT NOT NULL, forced_reasons TEXT NOT NULL, created REAL NOT NULL,
          FOREIGN KEY(issue_id) REFERENCES review_issues(issue_id)
        );
        CREATE TABLE IF NOT EXISTS review_events (
          id INTEGER PRIMARY KEY, issue_id TEXT NOT NULL, kind TEXT NOT NULL,
          decision TEXT, note TEXT NOT NULL DEFAULT '', created REAL NOT NULL,
          UNIQUE(issue_id, kind, decision, note, created),
          FOREIGN KEY(issue_id) REFERENCES review_issues(issue_id)
        );
        """)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def record_judgment(self, monitor_id: str, company_id: str, document_id: str,
                        document_version: str, rule_version: str, judgment: dict[str, Any],
                        evidence_refs: list[Any], forced_reasons: list[str] | None = None) -> dict[str, Any]:
        relevance = judgment.get("relevance")
        human = judgment.get("human_review_required")
        reason = judgment.get("reason", "")
        if not monitor_id or not company_id or not document_id or not document_version or not rule_version:
            raise ValidationError("review identity and versions are required")
        if relevance not in _RELEVANCE or not isinstance(human, bool) or not isinstance(reason, str) or not reason:
            raise ValidationError("invalid judgment")
        forced = list(forced_reasons or [])
        if not all(isinstance(x, str) and x for x in forced):
            raise ValidationError("invalid forced_reasons")
        effective_human = human or relevance == "uncertain" or bool(forced)
        issue_id = "issue-" + _digest([monitor_id, company_id, document_id])[:20]
        now = time.time()
        row = self.db.execute("SELECT * FROM review_issues WHERE issue_id=?", (issue_id,)).fetchone()
        if row is None:
            self.db.execute("INSERT INTO review_issues(issue_id,monitor_id,company_id,document_id,status,effective_judgment,created,updated) VALUES(?,?,?,?,?,?,?,?)",
                            (issue_id, monitor_id, company_id, document_id, "open" if effective_human else "resolved", json.dumps(judgment, ensure_ascii=False), now, now))
        fingerprint = _digest([issue_id, document_version, rule_version, judgment, evidence_refs, forced])
        existing = self.db.execute("SELECT id FROM review_judgments WHERE fingerprint=?", (fingerprint,)).fetchone()
        if existing is None:
            self.db.execute("INSERT INTO review_judgments(issue_id,fingerprint,document_version,rule_version,judgment,evidence_refs,forced_reasons,created) VALUES(?,?,?,?,?,?,?,?)",
                            (issue_id, fingerprint, document_version, rule_version, json.dumps(judgment, ensure_ascii=False), json.dumps(evidence_refs, ensure_ascii=False), json.dumps(forced, ensure_ascii=False), now))
            current = self.db.execute("SELECT * FROM review_issues WHERE issue_id=?", (issue_id,)).fetchone()
            latest = self.db.execute("SELECT document_version,rule_version FROM review_judgments WHERE issue_id=? AND fingerprint<>? ORDER BY id DESC LIMIT 1", (issue_id, fingerprint)).fetchone()
            same_revision = bool(latest and latest["document_version"] == document_version and latest["rule_version"] == rule_version)
            if current and current["human_decision"] and same_revision:
                status = current["status"]
                effective = json.loads(current["effective_judgment"])
                required = bool(effective.get("human_review_required"))
            else:
                required = effective_human or bool(current and current["status"] == "open")
                effective = {**judgment, "human_review_required": required}
                if current and current["status"] == "open" and not effective_human:
                    effective["reason"] = f"{reason}; existing_open"
                status = "open" if required else "resolved"
            self.db.execute("UPDATE review_issues SET status=?,effective_judgment=?,updated=? WHERE issue_id=?", (status, json.dumps(effective, ensure_ascii=False), now, issue_id))
        self.db.commit()
        current = self.db.execute("SELECT * FROM review_issues WHERE issue_id=?", (issue_id,)).fetchone()
        effective = json.loads(current["effective_judgment"])
        latest = self.db.execute("SELECT judgment,forced_reasons FROM review_judgments WHERE issue_id=? ORDER BY id DESC LIMIT 1", (issue_id,)).fetchone()
        original = json.loads(latest["judgment"])
        reasons = json.loads(latest["forced_reasons"]) or [original.get("reason", "")]
        return {"issue_id": issue_id, "status": current["status"], "relevance": effective["relevance"], "human_review_required": bool(effective.get("human_review_required")), "original_judgment": original, "reasons": reasons, "effective_judgment": effective}

    def review_list(self, monitor_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM review_issues"; args: tuple[Any, ...] = ()
        if monitor_id is not None: query += " WHERE monitor_id=?"; args = (monitor_id,)
        rows = self.db.execute(query + " ORDER BY issue_id", args).fetchall()
        result = []
        for r in rows:
            events = [dict(x) for x in self.db.execute("SELECT kind,decision,note,created FROM review_events WHERE issue_id=? ORDER BY id", (r["issue_id"],)).fetchall()]
            models = [dict(x) for x in self.db.execute("SELECT document_version,rule_version,judgment,evidence_refs,forced_reasons,created FROM review_judgments WHERE issue_id=? ORDER BY id", (r["issue_id"],)).fetchall()]
            for event in models:
                event["judgment"] = json.loads(event["judgment"]); event["evidence_refs"] = json.loads(event["evidence_refs"]); event["forced_reasons"] = json.loads(event["forced_reasons"]); event["kind"] = "model"
            result.append({"issue_id": r["issue_id"], "monitor_id": r["monitor_id"], "company_id": r["company_id"], "document_id": r["document_id"], "status": r["status"], "effective_judgment": json.loads(r["effective_judgment"]), "human_decision": r["human_decision"], "note": r["note"], "events": sorted(models + events, key=lambda e: e["created"])})
        return result

    def review_decide(self, issue_id: str, decision: str, note: str = "") -> dict[str, Any]:
        if decision not in {"relevant", "irrelevant", "uncertain", "defer"}: raise ValidationError("invalid decision")
        row = self.db.execute("SELECT * FROM review_issues WHERE issue_id=?", (issue_id,)).fetchone()
        if row is None: raise NotFoundError("review issue not found")
        status = "open" if decision in {"uncertain", "defer"} else "resolved"
        now = time.time()
        if row["human_decision"] == decision and row["note"] == note and row["status"] == status:
            return {"issue_id": issue_id, "status": status, "human_decision": decision, "note": note}
        effective = json.loads(row["effective_judgment"])
        if decision in {"relevant", "irrelevant", "uncertain"}:
            effective["relevance"] = decision
        effective["human_review_required"] = status == "open"
        self.db.execute("UPDATE review_issues SET status=?,human_decision=?,note=?,effective_judgment=?,updated=? WHERE issue_id=?", (status, decision, note, json.dumps(effective, ensure_ascii=False), now, issue_id))
        self.db.execute("INSERT INTO review_events(issue_id,kind,decision,note,created) VALUES(?,?,?,?,?)", (issue_id, "human", decision, note, now))
        self.db.commit()
        return {"issue_id": issue_id, "status": status, "human_decision": decision, "note": note}
