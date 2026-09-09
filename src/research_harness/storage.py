from __future__ import annotations
import hashlib, json, sqlite3, time, uuid
from pathlib import Path
from .errors import BusyError

class Store:
    def __init__(self, workspace: str | Path):
        self.root = Path(workspace); self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "raw").mkdir(exist_ok=True); (self.root / "reports").mkdir(exist_ok=True)
        self.db = sqlite3.connect(self.root / "research.sqlite")
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS specs (project_id TEXT, revision INTEGER, fingerprint TEXT, content TEXT, created REAL, PRIMARY KEY(project_id,revision));
        CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, sha256 TEXT UNIQUE, kind TEXT, collection_name TEXT, filename TEXT, raw_path TEXT, content TEXT, parse_status TEXT DEFAULT 'unknown', parse_errors TEXT DEFAULT '[]', created REAL);
        CREATE TABLE IF NOT EXISTS evidence (id TEXT PRIMARY KEY, document_id TEXT, quote TEXT, locator TEXT, role TEXT, FOREIGN KEY(document_id) REFERENCES documents(id));
        CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, project_id TEXT, revision INTEGER, status TEXT, mode TEXT, manifest TEXT, report_data TEXT, created REAL, updated REAL);
        CREATE TABLE IF NOT EXISTS issues (id TEXT PRIMARY KEY, document_id TEXT, rule_id TEXT, issue_type TEXT, evidence_fingerprint TEXT, status TEXT, machine_disposition TEXT, human_decision TEXT, note TEXT, events TEXT, UNIQUE(document_id,rule_id,issue_type));
        """)
        columns={r[1] for r in self.db.execute("PRAGMA table_info(runs)")}
        if "report_data" not in columns: self.db.execute("ALTER TABLE runs ADD COLUMN report_data TEXT")
        doc_columns={r[1] for r in self.db.execute("PRAGMA table_info(documents)")}
        if "parse_status" not in doc_columns: self.db.execute("ALTER TABLE documents ADD COLUMN parse_status TEXT DEFAULT 'unknown'")
        if "parse_errors" not in doc_columns: self.db.execute("ALTER TABLE documents ADD COLUMN parse_errors TEXT DEFAULT '[]'")
        self.db.commit()
    def close(self): self.db.close()
    def save_spec(self, spec: dict, fp: str) -> None:
        row = self.db.execute("SELECT fingerprint FROM specs WHERE project_id=? AND revision=?", (spec["project_id"], spec["revision"])).fetchone()
        if row and row["fingerprint"] != fp: raise BusyError("revision conflict: manual edit requires a new revision")
        self.db.execute("INSERT OR IGNORE INTO specs VALUES (?,?,?,?,?)", (spec["project_id"], spec["revision"], fp, json.dumps(spec,ensure_ascii=False), time.time())); self.db.commit()
    def import_file(self, path: str | Path, collection: str, kind: str) -> str:
        raw = Path(path).read_bytes(); digest = hashlib.sha256(raw).hexdigest(); ident = "doc-" + digest[:16]
        target = self.root / "raw" / digest; target.write_bytes(raw) if not target.exists() else None
        text = raw.decode("utf-8", errors="replace") if Path(path).suffix.lower() in {".txt", ".xml"} else ""
        self.db.execute("INSERT OR IGNORE INTO documents (id,sha256,kind,collection_name,filename,raw_path,content,created) VALUES (?,?,?,?,?,?,?,?)", (ident,digest,kind,collection,Path(path).name,str(target.relative_to(self.root)),text,time.time())); self.db.commit(); return ident
    def documents(self): return [dict(x) for x in self.db.execute("SELECT * FROM documents ORDER BY created")]
    def add_evidence(self, document_id: str, values: list[dict]) -> None:
        for n,value in enumerate(values,1):
            ident=f"{document_id}-ev-{n}"; self.db.execute("INSERT OR IGNORE INTO evidence VALUES (?,?,?,?,?)",(ident,document_id,value["quote"],value["locator"],value["role"]))
        self.db.commit()
    def evidence(self, document_id: str): return [dict(x) for x in self.db.execute("SELECT * FROM evidence WHERE document_id=? ORDER BY id",(document_id,))]
    def create_run(self, spec: dict, mode: str, manifest: dict) -> str:
        ident = "run-" + uuid.uuid4().hex[:12]; now=time.time(); self.db.execute("INSERT INTO runs (id,project_id,revision,status,mode,manifest,created,updated) VALUES (?,?,?,?,?,?,?,?)",(ident,spec["project_id"],spec["revision"],"running",mode,json.dumps(manifest,ensure_ascii=False),now,now));self.db.commit();return ident
    def finish_run(self, ident: str, status: str, manifest: dict, report_data: dict): self.db.execute("UPDATE runs SET status=?,manifest=?,report_data=?,updated=? WHERE id=?",(status,json.dumps(manifest,ensure_ascii=False),json.dumps(report_data,ensure_ascii=False),time.time(),ident));self.db.commit()
    def run(self, ident):
        row=self.db.execute("SELECT * FROM runs WHERE id=?",(ident,)).fetchone(); return dict(row) if row else None
    def runs(self): return [dict(x) for x in self.db.execute("SELECT * FROM runs ORDER BY created DESC")]
    def decide(self, issue_id, decision, note):
        if decision not in {"include","exclude","watch","request_more_evidence"}: raise ValueError("invalid decision")
        row=self.db.execute("SELECT * FROM issues WHERE id=?",(issue_id,)).fetchone()
        if not row: raise KeyError(issue_id)
        events=json.loads(row["events"]); events.append({"at":time.time(),"decision":decision,"note":note})
        state="open" if decision=="request_more_evidence" else "resolved"
        self.db.execute("UPDATE issues SET status=?,human_decision=?,note=?,events=? WHERE id=?",(state,decision,note,json.dumps(events,ensure_ascii=False),issue_id));self.db.commit()
    def issues(self): return [dict(x) for x in self.db.execute("SELECT * FROM issues ORDER BY id")]
