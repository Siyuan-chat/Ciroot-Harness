"""Small, offline text index used by GUI-created libraries.

This intentionally does not read or mutate the legacy Docling/Qdrant index.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
DB_NAME = "gui-local-library.sqlite"
_WORDS = re.compile(r"[\w-]+", re.UNICODE)


class LocalLibraryError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _connect(root: Path) -> sqlite3.Connection:
    root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(root / DB_NAME, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
      CREATE TABLE IF NOT EXISTS documents(
        document_id TEXT PRIMARY KEY,title TEXT NOT NULL,filename TEXT NOT NULL,
        document_type TEXT NOT NULL,current_version_id TEXT NOT NULL,
        parse_status TEXT NOT NULL,coverage TEXT NOT NULL,errors TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS versions(
        version_id TEXT PRIMARY KEY,document_id TEXT NOT NULL,content_sha256 TEXT NOT NULL,
        source_name TEXT NOT NULL,source_path TEXT NOT NULL,page_count INTEGER,
        coverage TEXT NOT NULL,errors TEXT NOT NULL,created REAL NOT NULL,
        UNIQUE(document_id,content_sha256),FOREIGN KEY(document_id) REFERENCES documents(document_id)
      );
      CREATE TABLE IF NOT EXISTS evidence(
        evidence_id TEXT PRIMARY KEY,document_id TEXT NOT NULL,version_id TEXT NOT NULL,
        ordinal INTEGER NOT NULL,text TEXT NOT NULL,locator TEXT NOT NULL,
        section TEXT,role TEXT NOT NULL,quality TEXT NOT NULL,
        FOREIGN KEY(document_id) REFERENCES documents(document_id),
        FOREIGN KEY(version_id) REFERENCES versions(version_id)
      );
      CREATE INDEX IF NOT EXISTS evidence_version_ordinal ON evidence(version_id,ordinal);
      CREATE INDEX IF NOT EXISTS version_digest ON versions(content_sha256);
    """)
    db.commit()
    return db


def has_index(root: Path) -> bool:
    return (root / DB_NAME).is_file()


def _chunks_text(text: str) -> list[dict[str, Any]]:
    lines = text.splitlines()
    out: list[dict[str, Any]] = []
    pending: list[str] = []
    start = 1
    size = 0
    for number, line in enumerate(lines, 1):
        value = line.strip()
        if not value:
            continue
        if pending and size + len(value) > 1800:
            out.append({"text": "\n".join(pending), "locator": {"kind": "line_range", "value": f"{start}-{number-1}", "line_start": start, "line_end": number-1}})
            pending, size = [], 0
        if not pending:
            start = number
        pending.append(value)
        size += len(value)
    if pending:
        out.append({"text": "\n".join(pending), "locator": {"kind": "line_range", "value": f"{start}-{len(lines)}", "line_start": start, "line_end": len(lines)}})
    return out


def _extract(filename: str, payload: bytes) -> tuple[list[dict[str, Any]], int | None, str, list[str]]:
    suffix = Path(filename).suffix.casefold()
    if suffix not in {".pdf", ".txt"}:
        raise LocalLibraryError("RH_GUI_LIBRARY_FILE_TYPE", "仅支持 PDF 和 TXT 文件")
    if not payload:
        raise LocalLibraryError("RH_GUI_LIBRARY_EMPTY_FILE", "文件内容为空")
    if len(payload) > MAX_UPLOAD_BYTES:
        raise LocalLibraryError("RH_GUI_LIBRARY_TOO_LARGE", "文件超过 20 MiB 大小限制")
    if suffix == ".txt":
        try:
            text = payload.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise LocalLibraryError("RH_GUI_LIBRARY_TEXT_ENCODING", "TXT 必须使用 UTF-8 编码") from exc
        chunks = _chunks_text(text)
        if not chunks:
            raise LocalLibraryError("RH_GUI_LIBRARY_NO_TEXT", "TXT 中没有可索引的文本")
        return chunks, None, "complete", []
    if not payload.startswith(b"%PDF-"):
        raise LocalLibraryError("RH_GUI_LIBRARY_PDF_INVALID", "文件扩展名为 PDF，但内容不是有效 PDF")
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(payload)
        chunks: list[dict[str, Any]] = []
        empty_pages: list[int] = []
        total = len(pdf)
        for index in range(total):
            page_number = index + 1
            page = pdf[index]
            text_page = page.get_textpage()
            text = text_page.get_text_range().strip()
            text_page.close()
            page.close()
            if not text:
                empty_pages.append(page_number)
                continue
            for chunk in _chunks_text(text):
                chunks.append({"text": chunk["text"], "locator": {"kind": "pdf_page", "value": str(page_number), "page": page_number, "pages": [page_number]}})
        pdf.close()
    except LocalLibraryError:
        raise
    except Exception as exc:
        raise LocalLibraryError("RH_GUI_LIBRARY_PDF_PARSE", "PDF 无法读取或解析") from exc
    if not chunks:
        raise LocalLibraryError("RH_GUI_LIBRARY_PDF_NO_TEXT", "PDF 没有可提取的文字；扫描件或图片 PDF 未建立索引")
    errors = [f"page {page} contains no extractable text" for page in empty_pages]
    return chunks, total, "partial" if empty_pages else "complete", errors


def import_file(root: Path, filename: str, payload: bytes) -> dict[str, Any]:
    name = Path(filename.replace("\\", "/")).name.strip()
    if not name or len(name) > 240 or "\0" in name:
        raise LocalLibraryError("RH_GUI_LIBRARY_FILENAME", "文件名无效")
    if len(payload) > MAX_UPLOAD_BYTES:
        raise LocalLibraryError("RH_GUI_LIBRARY_TOO_LARGE", "文件超过 20 MiB 大小限制")
    chunks, pages, coverage, errors = _extract(name, payload)
    digest = hashlib.sha256(payload).hexdigest()
    version_id = "ver-" + digest[:32]
    title = Path(name).stem[:240]
    doc_identity = re.sub(r"\s+", " ", title).strip().casefold() or name.casefold()
    document_id = "doc-" + hashlib.sha256(doc_identity.encode("utf-8")).hexdigest()[:24]
    raw = (root / "raw").resolve()
    raw.mkdir(parents=True, exist_ok=True)
    destination = (raw / f"{version_id}{Path(name).suffix.casefold()}").resolve()
    if not destination.is_relative_to(raw):
        raise LocalLibraryError("RH_GUI_LIBRARY_FILENAME", "文件路径无效")
    db = _connect(root)
    temporary: Path | None = None
    try:
        prior = db.execute("SELECT d.document_id,d.current_version_id,d.title FROM versions v JOIN documents d ON d.document_id=v.document_id WHERE v.content_sha256=?", (digest,)).fetchone()
        if prior:
            return {"document_id": prior["document_id"], "version_id": prior["current_version_id"], "title": prior["title"], "duplicate": True, "parse_status": "completed"}
        fd, temp_name = tempfile.mkstemp(prefix=".upload-", suffix=Path(name).suffix.casefold(), dir=raw)
        temporary = Path(temp_name)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM documents WHERE document_id=?", (document_id,)).fetchone():
            old = db.execute("SELECT current_version_id FROM documents WHERE document_id=?", (document_id,)).fetchone()[0]
            db.execute("UPDATE documents SET title=?,filename=?,document_type=?,current_version_id=?,parse_status=?,coverage=?,errors=? WHERE document_id=?", (title, name, "paper", version_id, "partial" if coverage == "partial" else "completed", coverage, json.dumps(errors), document_id))
        else:
            old = None
            db.execute("INSERT INTO documents VALUES (?,?,?,?,?,?,?,?)", (document_id, title, name, "paper", version_id, "partial" if coverage == "partial" else "completed", coverage, json.dumps(errors)))
        os.replace(temporary, destination)
        temporary = None
        db.execute("INSERT INTO versions VALUES (?,?,?,?,?,?,?,?,strftime('%s','now'))", (version_id, document_id, digest, name, str(destination), pages, coverage, json.dumps(errors)))
        for ordinal, item in enumerate(chunks):
            evidence_id = "ev-" + hashlib.sha256(f"{document_id}\0{version_id}\0{ordinal}".encode()).hexdigest()[:28]
            db.execute("INSERT INTO evidence VALUES (?,?,?,?,?,?,?,?,?)", (evidence_id, document_id, version_id, ordinal, item["text"], json.dumps(item["locator"], ensure_ascii=False), None, "text", "basic-extraction"))
        db.commit()
        return {"document_id": document_id, "version_id": version_id, "title": title, "duplicate": False, "parse_status": "partial" if coverage == "partial" else "completed", "coverage": coverage, "errors": errors}
    except Exception:
        db.rollback()
        if destination.exists() and not db.execute("SELECT 1 FROM versions WHERE version_id=?", (version_id,)).fetchone():
            destination.unlink()
        raise
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
        db.close()


def list_documents(root: Path, *, limit: int = 50, cursor: str | None = None, document_ids: set[str] | None = None) -> dict[str, Any]:
    offset = 0
    if cursor:
        try:
            offset = max(0, int(cursor))
        except ValueError as exc:
            raise LocalLibraryError("RH_GUI_LIBRARY_CURSOR", "分页游标无效") from exc
    db = _connect(root)
    try:
        where = ""
        values: list[Any] = []
        if document_ids is not None:
            if not document_ids:
                return {"items": [], "next_cursor": None, "index_status": "not_indexed", "index_mode": "basic", "document_count": 0}
            where = "WHERE document_id IN (" + ",".join("?" for _ in document_ids) + ")"
            values.extend(sorted(document_ids))
        rows = db.execute(f"SELECT document_id,title,filename,document_type,current_version_id,parse_status,coverage,errors FROM documents {where} ORDER BY title COLLATE NOCASE,document_id LIMIT ? OFFSET ?", (*values, limit + 1, offset)).fetchall()
        more = len(rows) > limit
        items = []
        for row in rows[:limit]:
            versions = [dict(v) for v in db.execute("SELECT version_id,document_id,source_name,source_path,page_count,coverage,errors,created FROM versions WHERE document_id=? ORDER BY created", (row["document_id"],))]
            for v in versions:
                v["errors"] = json.loads(v["errors"])
                v["file_url"] = f"/api/v1/library/documents/{row['document_id']}/versions/{v['version_id']}/file"
            items.append({"document_id": row["document_id"], "title": row["title"], "doi": None, "year": None, "document_type": row["document_type"], "current_version_id": row["current_version_id"], "parse_status": row["parse_status"], "coverage": row["coverage"], "errors": json.loads(row["errors"]), "versions": versions})
        count_sql = "SELECT COUNT(*) FROM documents " + where
        count = db.execute(count_sql, values).fetchone()[0]
        return {"items": items, "next_cursor": str(offset + limit) if more else None, "index_status": "basic" if count else "not_indexed", "index_mode": "basic", "document_count": count}
    finally:
        db.close()


def get_document(root: Path, document_id: str) -> dict[str, Any]:
    db = _connect(root)
    try:
        row = db.execute("SELECT * FROM documents WHERE document_id=?", (document_id,)).fetchone()
        if not row:
            raise LocalLibraryError("RH_RAG_NOT_FOUND", "document was not found")
        value = dict(row)
        value["doi"] = None
        value["year"] = None
        value["errors"] = json.loads(value["errors"])
        value["versions"] = []
        for v in db.execute("SELECT version_id,document_id,source_name,source_path,page_count,coverage,errors,created FROM versions WHERE document_id=? ORDER BY created", (document_id,)):
            item = dict(v)
            item["errors"] = json.loads(item["errors"])
            item["file_url"] = f"/api/v1/library/documents/{document_id}/versions/{item['version_id']}/file"
            value["versions"].append(item)
        return value
    finally:
        db.close()


def source_file(root: Path, document_id: str, version_id: str) -> Path:
    db = _connect(root)
    try:
        row = db.execute("SELECT source_path FROM versions WHERE document_id=? AND version_id=?", (document_id, version_id)).fetchone()
        if not row:
            raise LocalLibraryError("RH_RAG_NOT_FOUND", "document version unavailable")
        raw = (root / "raw").resolve()
        path = Path(row["source_path"]).resolve()
        if not path.is_relative_to(raw) or not path.is_file():
            raise LocalLibraryError("RH_RAG_NOT_FOUND", "document file unavailable")
        return path
    finally:
        db.close()


def search(root: Path, query: str, *, top_k: int = 8, document_ids: set[str] | None = None) -> dict[str, Any]:
    terms = [x.casefold() for x in _WORDS.findall(query)]
    cjk = "".join(re.findall(r"[\u3400-\u9fff]", query))
    terms.extend(cjk[i:i+2] for i in range(max(0, len(cjk)-1)))
    db = _connect(root)
    try:
        rows = db.execute("SELECT e.*,d.title,v.content_sha256,v.source_name FROM evidence e JOIN documents d ON d.document_id=e.document_id JOIN versions v ON v.version_id=e.version_id WHERE e.version_id=d.current_version_id").fetchall()
        found = []
        for row in rows:
            if document_ids is not None and row["document_id"] not in document_ids:
                continue
            text = row["text"]
            folded = text.casefold()
            score = sum(folded.count(term) for term in terms if term)
            if score:
                found.append((score, row))
        found.sort(key=lambda pair: (-pair[0], pair[1]["document_id"], pair[1]["ordinal"]))
        items = []
        for score, row in found[:top_k]:
            items.append({"evidence_id": row["evidence_id"], "document_id": row["document_id"], "version_id": row["version_id"], "text": row["text"], "title": row["title"], "doi": None, "year": None, "document_type": "paper", "section": row["section"], "role": row["role"], "quality": row["quality"], "locator": json.loads(row["locator"]), "score": score})
        return {"query": query, "items": items, "snapshot_version_ids": sorted({x["version_id"] for x in items}), "diagnostics": {"mode": "basic", "lexical_hits": len(found), "vector_hits": 0, "embedding_model": None, "coverage_limits": ["offline lexical matching over extracted text; no embeddings, semantic expansion or hybrid ranking"]}}
    finally:
        db.close()


def evidence_context(root: Path, evidence_id: str) -> dict[str, Any]:
    db = _connect(root)
    try:
        row = db.execute("SELECT e.*,d.title FROM evidence e JOIN documents d ON d.document_id=e.document_id WHERE evidence_id=?", (evidence_id,)).fetchone()
        if not row:
            raise LocalLibraryError("RH_RAG_NOT_FOUND", "evidence was not found")
        value = dict(row)
        return {"evidence_id": evidence_id, "document_id": value["document_id"], "version_id": value["version_id"], "text": value["text"], "title": value["title"], "locator": json.loads(value["locator"]), "items": [{"evidence_id": evidence_id, "document_id": value["document_id"], "version_id": value["version_id"], "text": value["text"], "title": value["title"], "locator": json.loads(value["locator"])}]}
    finally:
        db.close()


def reference_snapshot(root: Path, *, workspace_id: str, library_id: str, collection_id: str, query: str, document_ids: set[str] | None = None) -> dict[str, Any]:
    result = search(root, query, top_k=8, document_ids=document_ids)
    docs = list_documents(root, limit=10000)["items"]
    if document_ids is not None:
        docs = [item for item in docs if item["document_id"] in document_ids]
    versions = [{"document_id": item["document_id"], "current_version_id": item["current_version_id"], "versions": [v["version_id"] for v in item["versions"]]} for item in docs]
    allowed = {item["current_version_id"] for item in versions}
    if not set(result["snapshot_version_ids"]).issubset(allowed):
        raise LocalLibraryError("RH_REFERENCE_EVIDENCE", "basic search returned evidence outside the selected library")
    return {"workspace_id": workspace_id, "library_id": library_id, "collection_id": collection_id,
            "member_document_versions": versions,
            "index_snapshot": {"index_status": "basic", "retrieval_mode": "basic", "embedding_model": None, "active_collection": None},
            "reference_evidence": [{**item, "context": [item]} for item in result["items"]],
            "reference_rag_diagnostics": result["diagnostics"]}
