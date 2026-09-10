"""Local, provenance-preserving library for the D18 evidence RAG boundary."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import argparse
import sys
from importlib.metadata import version as package_version
import uuid
from collections import Counter
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Iterable, Iterator


DEFAULT_EMBEDDING_MODEL = "intfloat/multilingual-e5-small"
_LEGACY_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
_ALLOWED_FILTERS = {"document_ids", "version_ids", "doi", "year_min", "year_max", "types"}
_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff]")
_WORD_RE = re.compile(r"[\w-]+", re.UNICODE)
_CHUNK_SIZE = 200
_CHUNK_OVERLAP = 30
_PARSER_FINGERPRINT = "docling-pypdfium2-no-ocr-table-structure-no-cell-match-visible-provenance-v3"
_EMBEDDING_DIMENSION = 384
_EMBEDDING_THREADS = 2
_EMBEDDING_BATCH_SIZE = 16


class RagError(Exception):
    """A safe RAG application-boundary error."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


def _safe_error(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _tokens(text: str) -> Counter[str]:
    normalized = text.casefold()
    tokens = _WORD_RE.findall(normalized)
    cjk = "".join(_CJK_RE.findall(normalized))
    tokens.extend(cjk[index : index + 2] for index in range(max(0, len(cjk) - 1)))
    return Counter(token for token in tokens if len(token) > 1)


class RagLibrary(AbstractContextManager["RagLibrary"]):
    """A workspace-scoped, local evidence library.

    Imports deliberately retain the original source location and extracted
    provenance. The index contains only derived vectors and metadata.
    """

    def __init__(self, workspace: str | Path, *, embedding_model: str | None = None):
        self.root = Path(workspace).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "raw").mkdir(exist_ok=True)
        self.embedding_model = embedding_model or DEFAULT_EMBEDDING_MODEL
        self._db = sqlite3.connect(self.root / "rag.sqlite")
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS rag_documents (
              document_id TEXT PRIMARY KEY, title TEXT NOT NULL, doi TEXT,
              year INTEGER, document_type TEXT, source_path TEXT NOT NULL,
              current_version_id TEXT, parse_status TEXT NOT NULL,
              coverage TEXT NOT NULL, errors TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS rag_versions (
              version_id TEXT PRIMARY KEY, document_id TEXT NOT NULL,
              content_sha256 TEXT NOT NULL, parser TEXT NOT NULL, page_count INTEGER,
              coverage TEXT NOT NULL, errors TEXT NOT NULL, source_path TEXT NOT NULL, created REAL NOT NULL,
              UNIQUE(document_id, content_sha256),
              FOREIGN KEY(document_id) REFERENCES rag_documents(document_id)
            );
            CREATE TABLE IF NOT EXISTS rag_evidence (
              evidence_id TEXT PRIMARY KEY, document_id TEXT NOT NULL,
              version_id TEXT NOT NULL, ordinal INTEGER NOT NULL, text TEXT NOT NULL,
              locator TEXT NOT NULL, section TEXT, role TEXT NOT NULL, quality TEXT NOT NULL,
              FOREIGN KEY(document_id) REFERENCES rag_documents(document_id),
              FOREIGN KEY(version_id) REFERENCES rag_versions(version_id)
            );
            CREATE INDEX IF NOT EXISTS rag_evidence_version ON rag_evidence(version_id, ordinal);
            CREATE TABLE IF NOT EXISTS rag_config (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """
        )
        version_columns = {row[1] for row in self._db.execute("PRAGMA table_info(rag_versions)")}
        if "source_path" not in version_columns:
            self._db.execute("ALTER TABLE rag_versions ADD COLUMN source_path TEXT")
        self._db.commit()
        self._embedder: Any | None = None
        self._qdrant: Any | None = None
        self._converter: Any | None = None

    def __exit__(self, *_: Any) -> None:
        self.close()

    def close(self) -> None:
        if self._qdrant is not None:
            self._qdrant.close()
            self._qdrant = None
        self._db.close()

    def _components(self, *, enforce_config: bool = True) -> tuple[Any, Any, Any]:
        if enforce_config:
            self._ensure_index_config()
        try:
            from fastembed import TextEmbedding
            from fastembed.common.model_description import ModelSource, PoolingType
            from llama_index.core.node_parser import SentenceSplitter
            from qdrant_client import QdrantClient
        except ImportError as exc:
            raise RagError("RH_RAG_DEPENDENCY", "RAG dependencies are not installed") from exc
        if self._embedder is None:
            cache_dir = Path(os.environ.get("RAG_MODEL_CACHE", self.root.parent / "rag-runtime" / "models"))
            cache_dir.mkdir(parents=True, exist_ok=True)
            if self.embedding_model == DEFAULT_EMBEDDING_MODEL and not any(model.get("model", "").casefold() == DEFAULT_EMBEDDING_MODEL.casefold() for model in TextEmbedding.list_supported_models()):
                TextEmbedding.add_custom_model(
                    model=DEFAULT_EMBEDDING_MODEL,
                    pooling=PoolingType.MEAN,
                    normalization=True,
                    sources=ModelSource(hf=DEFAULT_EMBEDDING_MODEL),
                    dim=_EMBEDDING_DIMENSION,
                    model_file="onnx/model.onnx",
                    license="mit",
                )
            self._embedder = TextEmbedding(model_name=self.embedding_model, cache_dir=str(cache_dir), threads=_EMBEDDING_THREADS)
        if self._qdrant is None:
            try:
                self._qdrant = QdrantClient(path=str(self.root / "qdrant"))
            except RuntimeError as exc:
                raise RagError("RH_RAG_BUSY", "RAG workspace index is in use") from exc
        return self._embedder, self._qdrant, SentenceSplitter

    def _index_fingerprint(self) -> str:
        preprocessing = "fastembed-0.8-mean-pooling-normalized-e5-query-passage" if self.embedding_model == DEFAULT_EMBEDDING_MODEL else "fastembed-0.8-mean-pooling"
        return json.dumps({"embedding_model": self.embedding_model, "embedding_dimension": _EMBEDDING_DIMENSION, "embedding_preprocessing": preprocessing, "fastembed": package_version("fastembed"), "docling": package_version("docling"), "llama_index_core": package_version("llama-index-core"), "chunk_size": _CHUNK_SIZE, "chunk_overlap": _CHUNK_OVERLAP, "parser": _PARSER_FINGERPRINT}, sort_keys=True)

    def _active_collection(self) -> str:
        row = self._db.execute("SELECT value FROM rag_config WHERE key='active_collection'").fetchone()
        return row["value"] if row else "evidence"

    def _stored_embedding_model(self) -> str:
        row = self._db.execute("SELECT value FROM rag_config WHERE key='index_fingerprint'").fetchone()
        if not row:
            return self.embedding_model
        try:
            return str(json.loads(row["value"])["embedding_model"])
        except (KeyError, TypeError, ValueError):
            return self.embedding_model

    def _ensure_index_config(self) -> None:
        fingerprint = self._index_fingerprint()
        saved = self._db.execute("SELECT value FROM rag_config WHERE key='index_fingerprint'").fetchone()
        if saved and saved["value"] != fingerprint and self._db.execute("SELECT COUNT(*) FROM rag_evidence").fetchone()[0]:
            raise RagError("RH_RAG_CONFIG_MISMATCH", "index configuration differs from the existing evidence")
        if not saved:
            self._db.execute("INSERT INTO rag_config VALUES ('index_fingerprint', ?)", (fingerprint,))
        if not self._db.execute("SELECT 1 FROM rag_config WHERE key='active_collection'").fetchone():
            self._db.execute("INSERT INTO rag_config VALUES ('active_collection', 'evidence')")
        self._db.commit()

    @staticmethod
    def _catalog(catalog_path: str | Path) -> tuple[Path, list[dict[str, Any]]]:
        path = Path(catalog_path).resolve()
        try:
            content = json.loads(path.read_text(encoding="utf-8"))
            records = content["records"]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise RagError("RH_RAG_INVALID_INPUT", "catalog could not be read") from exc
        if not isinstance(records, list):
            raise RagError("RH_RAG_INVALID_INPUT", "catalog records must be a list")
        return path.parent, [record for record in records if isinstance(record, dict)]

    @staticmethod
    def _document_id(record: dict[str, Any], path: Path) -> str:
        doi = record.get("doi")
        identity = doi.strip().casefold() if isinstance(doi, str) and doi.strip() else str(path.resolve()).casefold()
        return "doc-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _item_text(document: Any, item: Any) -> tuple[str, str, str | None]:
        label = str(getattr(item, "label", "text"))
        if "table" in label.casefold():
            caption = getattr(item, "caption_text", lambda _doc: "")(document)
            table = getattr(item, "export_to_markdown", lambda _doc: "")(document)
            return "\n".join(part for part in (caption, table) if isinstance(part, str) and part.strip()), "table", caption or None
        text = getattr(item, "text", "")
        return (text if isinstance(text, str) else ""), "text", None

    @staticmethod
    def _locator(item: Any, valid_pages: set[int]) -> dict[str, Any]:
        provenance = getattr(item, "prov", None) or []
        locations = []
        for value in provenance:
            page = getattr(value, "page_no", None)
            bbox = getattr(value, "bbox", None)
            coordinates = {key: getattr(bbox, key, None) for key in ("l", "t", "r", "b", "coord_origin")} if bbox is not None else None
            visible = isinstance(page, int) and page in valid_pages and coordinates is not None and all(isinstance(coordinates[key], (int, float)) for key in ("l", "t", "r", "b")) and abs(coordinates["r"] - coordinates["l"]) > 0 and abs(coordinates["b"] - coordinates["t"]) > 0
            if visible:
                locations.append({"page": page, "bbox": coordinates})
        pages = sorted({value["page"] for value in locations if value["page"]})
        first = locations[0] if locations else {"page": None, "bbox": None}
        return {"page": first["page"], "bbox": first["bbox"], "printed_page": None, "pages": pages, "provenance": locations}

    def _parse_pdf(self, path: Path) -> tuple[list[dict[str, Any]], int | None, str, list[str]]:
        try:
            from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions, TableStructureOptions
            from docling.document_converter import DocumentConverter, PdfFormatOption
        except ImportError as exc:
            raise RagError("RH_RAG_DEPENDENCY", "Docling is not installed") from exc
        try:
            if self._converter is None:
                options = PdfPipelineOptions()
                options.do_ocr = False
                options.do_table_structure = True
                options.table_structure_options = TableStructureOptions(do_cell_matching=False)
                self._converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options, backend=PyPdfiumDocumentBackend)})
            converted = self._converter.convert(path)
            document = converted.document
            pages = getattr(document, "pages", {})
            page_numbers = set(pages) if isinstance(pages, dict) else set()
            blocks: list[dict[str, Any]] = []
            dropped = 0
            for item, _level in document.iterate_items():
                label = str(getattr(item, "label", "")).casefold()
                if "page_header" in label or "page_footer" in label:
                    continue
                text, role, section = self._item_text(document, item)
                if text.strip():
                    locator = self._locator(item, page_numbers)
                    if not locator["provenance"]:
                        dropped += 1
                        continue
                    blocks.append({"text": text.strip(), "locator": locator, "section": section, "role": role})
            observed = {page for block in blocks for page in block["locator"].get("pages", [])}
            missing = sorted(page_numbers - observed)
            partial = "PARTIAL" in str(getattr(converted, "status", "")).upper()
            errors = [f"no extracted text on physical page {page}" for page in missing]
            if dropped: errors.append(f"{dropped} non-visible extracted blocks were excluded")
            if partial: errors.append("Docling conversion reported partial coverage")
            return blocks, len(pages) if hasattr(pages, "__len__") else None, "partial" if missing or partial or dropped else "full_text", errors
        except RagError:
            raise
        except Exception as exc:
            raise RagError("RH_RAG_PARSE_FAILED", "Docling could not parse this PDF") from exc

    def _parse(self, path: Path) -> tuple[list[dict[str, Any]], int | None, str, list[str]]:
        if path.suffix.casefold() == ".pdf":
            return self._parse_pdf(path)
        if path.suffix.casefold() != ".txt":
            raise RagError("RH_RAG_UNSUPPORTED", "only PDF and TXT files are supported")
        text = path.read_text(encoding="utf-8", errors="replace")
        return ([{"text": text, "locator": {"line_start": 1, "line_end": text.count("\n") + 1}, "section": None, "role": "text"}], None, "full_text", [])

    @staticmethod
    def _docling_version() -> str:
        try:
            return package_version("docling")
        except Exception:
            return "unavailable"

    def _parse_cache_path(self, digest: str) -> tuple[Path, dict[str, str]]:
        key = {"content_sha256": digest, "parser": _PARSER_FINGERPRINT, "docling": self._docling_version()}
        name = hashlib.sha256(json.dumps(key, sort_keys=True).encode("utf-8")).hexdigest()
        return self.root / "parse-cache" / f"{name}.json", key

    @staticmethod
    def _cached_parse_payload(payload: Any, key: dict[str, str]) -> tuple[list[dict[str, Any]], int | None, str, list[str]] | None:
        if not isinstance(payload, dict) or payload.get("key") != key:
            return None
        blocks, pages, coverage, errors = (payload.get(field) for field in ("blocks", "pages", "coverage", "errors"))
        if not isinstance(blocks, list) or not all(isinstance(block, dict) and isinstance(block.get("text"), str) and isinstance(block.get("locator"), dict) and isinstance(block.get("role"), str) for block in blocks):
            return None
        if pages is not None and (not isinstance(pages, int) or isinstance(pages, bool)):
            return None
        if coverage not in {"full_text", "partial"} or not isinstance(errors, list) or not all(isinstance(error, str) for error in errors):
            return None
        return blocks, pages, coverage, errors

    def _parse_with_cache(self, source: Path, digest: str) -> tuple[list[dict[str, Any]], int | None, str, list[str], bool]:
        cache_path, key = self._parse_cache_path(digest)
        cache_invalid = False
        try:
            if cache_path.exists():
                cached = self._cached_parse_payload(json.loads(cache_path.read_text(encoding="utf-8")), key)
                if cached is not None:
                    return (*cached, True)
                cache_invalid = True
        except (OSError, ValueError, TypeError):
            cache_invalid = True
        blocks, pages, coverage, errors = self._parse(source)
        errors = list(errors)
        if cache_invalid:
            errors.append("invalid parse cache was discarded")
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache_path.with_name(f"{cache_path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps({"key": key, "blocks": blocks, "pages": pages, "coverage": coverage, "errors": errors}, ensure_ascii=False), encoding="utf-8")
            temporary.replace(cache_path)
        finally:
            if temporary.exists():
                temporary.unlink()
        return blocks, pages, coverage, errors, False

    @staticmethod
    def _chunks(blocks: list[dict[str, Any]], splitter_cls: Any) -> Iterator[dict[str, Any]]:
        splitter = splitter_cls(chunk_size=_CHUNK_SIZE, chunk_overlap=_CHUNK_OVERLAP)
        for block in blocks:
            if block["role"] == "table":
                yield {**block, "quality": "Docling table extraction; verify merged headers and footnotes in source"}
                continue
            for text in splitter.split_text(block["text"]):
                yield {**block, "text": text, "quality": "Docling layout/provenance extraction; reading order may need source check"}

    def import_library(self, catalog_path: str | Path, *, limit: int | None = None) -> dict[str, Any]:
        if limit is not None and (not isinstance(limit, int) or limit < 1):
            raise RagError("RH_RAG_INVALID_INPUT", "limit must be a positive integer")
        root, records = self._catalog(catalog_path)
        processed = records[:limit] if limit else records
        imported = reused = failed = 0
        documents: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for record in processed:
            file_value = record.get("file")
            if not isinstance(file_value, str):
                failed += 1; errors.append(_safe_error("RH_RAG_INVALID_INPUT", "catalog record has no file")); continue
            source = (root / file_value).resolve()
            document_id = self._document_id(record, source)
            if root not in source.parents or not source.is_file():
                failed += 1; errors.append({"document_id": document_id, **_safe_error("RH_RAG_INVALID_INPUT", "catalog file is unavailable")}); continue
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            old = self._db.execute("SELECT version_id FROM rag_versions WHERE document_id=? AND content_sha256=?", (document_id, digest)).fetchone()
            self._ensure_index_config()
            if old and self._version_is_indexed(old["version_id"]):
                reused += 1; documents.append({"document_id": document_id, "version_id": old["version_id"], "parse_status": "reused"}); continue
            try:
                blocks, pages, coverage, parse_errors, _cache_reused = self._parse_with_cache(source, digest)
                _embedder, qdrant, splitter = self._components()
                chunks = list(self._chunks(blocks, splitter))
                if not chunks:
                    raise RagError("RH_RAG_PARSE_FAILED", "Docling returned no usable evidence")
                version_id = "ver-" + hashlib.sha256(f"{document_id}:{digest}".encode()).hexdigest()[:24]
                evidence = []
                for ordinal, chunk in enumerate(chunks, 1):
                    evidence_id = "ev-" + hashlib.sha256(f"{version_id}:{ordinal}".encode()).hexdigest()[:24]
                    evidence.append({"evidence_id": evidence_id, "ordinal": ordinal, "version_id": version_id, **chunk})
                self._index(evidence, qdrant, _embedder)
                raw_path = self._copy_source(source, version_id)
                self._store_document(record, raw_path, document_id, version_id, digest, pages, coverage, parse_errors, evidence)
                imported += 1; documents.append({"document_id": document_id, "version_id": version_id, "parse_status": "completed", "evidence_count": len(evidence)})
            except RagError as exc:
                self._db.rollback()
                self._record_failure(record, source, document_id, exc)
                failed += 1; errors.append({"document_id": document_id, **exc.to_dict()})
            except Exception:
                self._db.rollback()
                self._record_failure(record, source, document_id, RagError("RH_RAG_FAILED", "document import failed"))
                failed += 1; errors.append({"document_id": document_id, **_safe_error("RH_RAG_FAILED", "document import failed")})
        outcome = "completed" if not failed else "partial" if imported or reused else "failed"
        return {"outcome": outcome, "imported": imported, "reused": reused, "failed": failed, "documents": documents, "errors": errors}

    def prepare_library(self, catalog_path: str | Path, *, limit: int | None = None) -> dict[str, Any]:
        """Populate reusable parse artifacts without creating evidence or vectors."""
        if limit is not None and (not isinstance(limit, int) or limit < 1):
            raise RagError("RH_RAG_INVALID_INPUT", "limit must be a positive integer")
        root, records = self._catalog(catalog_path)
        processed = records[:limit] if limit else records
        prepared = reused = failed = 0
        documents: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for record in processed:
            file_value = record.get("file")
            if not isinstance(file_value, str):
                failed += 1
                errors.append(_safe_error("RH_RAG_INVALID_INPUT", "catalog record has no file"))
                continue
            source = (root / file_value).resolve()
            document_id = self._document_id(record, source)
            if root not in source.parents or not source.is_file():
                failed += 1
                error = _safe_error("RH_RAG_INVALID_INPUT", "catalog file is unavailable")
                errors.append({"document_id": document_id, **error})
                documents.append({"document_id": document_id, "parse_status": "failed"})
                continue
            try:
                digest = hashlib.sha256(source.read_bytes()).hexdigest()
                blocks, pages, coverage, parse_errors, cache_reused = self._parse_with_cache(source, digest)
                if not blocks:
                    raise RagError("RH_RAG_PARSE_FAILED", "Docling returned no usable evidence")
                status = "reused" if cache_reused else "prepared"
                reused += int(cache_reused)
                prepared += int(not cache_reused)
                documents.append({"document_id": document_id, "parse_status": status, "page_count": pages, "coverage": coverage, "errors": parse_errors})
            except RagError as exc:
                failed += 1
                errors.append({"document_id": document_id, **exc.to_dict()})
                documents.append({"document_id": document_id, "parse_status": "failed"})
            except Exception:
                failed += 1
                error = _safe_error("RH_RAG_FAILED", "document preparation failed")
                errors.append({"document_id": document_id, **error})
                documents.append({"document_id": document_id, "parse_status": "failed"})
        outcome = "completed" if not failed else "partial" if prepared or reused else "failed"
        return {"outcome": outcome, "prepared": prepared, "reused": reused, "failed": failed, "documents": documents, "errors": errors}

    def _version_is_indexed(self, version_id: str) -> bool:
        count = self._db.execute("SELECT COUNT(*) FROM rag_evidence WHERE version_id=?", (version_id,)).fetchone()[0]
        if not count:
            return False
        try:
            from qdrant_client import QdrantClient, models
            if self._qdrant is None:
                self._qdrant = QdrantClient(path=str(self.root / "qdrant"))
            if not self._qdrant.collection_exists(self._active_collection()):
                return False
            query_filter = models.Filter(must=[models.FieldCondition(key="version_id", match=models.MatchValue(value=version_id))])
            return self._qdrant.count(self._active_collection(), count_filter=query_filter, exact=True).count == count
        except RagError:
            raise
        except RuntimeError as exc:
            raise RagError("RH_RAG_BUSY", "RAG workspace index is in use") from exc
        except Exception:
            return False

    def _copy_source(self, source: Path, version_id: str) -> Path:
        destination = self.root / "raw" / f"{version_id}{source.suffix.casefold()}"
        if not destination.exists():
            destination.write_bytes(source.read_bytes())
        return destination

    def _record_failure(self, record: dict[str, Any], source: Path, document_id: str, error: RagError) -> None:
        self._db.execute("INSERT OR IGNORE INTO rag_documents VALUES (?,?,?,?,?,?,?,?,?,?)", (document_id, str(record.get("title") or source.name), record.get("doi"), record.get("year"), record.get("type"), str(source), None, "failed", "unknown", json.dumps([error.to_dict()])))
        self._db.execute("UPDATE rag_documents SET parse_status='failed',coverage='unknown',errors=? WHERE document_id=? AND current_version_id IS NULL", (json.dumps([error.to_dict()]), document_id))
        self._db.commit()

    def _store_document(self, record: dict[str, Any], source: Path, document_id: str, version_id: str, digest: str, pages: int | None, coverage: str, errors: list[str], evidence: list[dict[str, Any]]) -> None:
        self._db.execute("INSERT OR IGNORE INTO rag_documents VALUES (?,?,?,?,?,?,?,?,?,?)", (document_id, str(record.get("title") or source.name), record.get("doi"), record.get("year"), record.get("type"), str(source), version_id, "completed", coverage, json.dumps(errors)))
        self._db.execute("UPDATE rag_documents SET title=?,doi=?,year=?,document_type=?,source_path=?,current_version_id=?,parse_status='completed',coverage=?,errors=? WHERE document_id=?", (str(record.get("title") or source.name), record.get("doi"), record.get("year"), record.get("type"), str(source), version_id, coverage, json.dumps(errors), document_id))
        self._db.execute("INSERT INTO rag_versions (version_id,document_id,content_sha256,parser,page_count,coverage,errors,source_path,created) VALUES (?,?,?,?,?,?,?,?,strftime('%s','now'))", (version_id, document_id, digest, _PARSER_FINGERPRINT, pages, coverage, json.dumps(errors), str(source)))
        self._db.executemany("INSERT INTO rag_evidence VALUES (?,?,?,?,?,?,?,?,?)", [(value["evidence_id"], document_id, version_id, value["ordinal"], value["text"], json.dumps(value["locator"]), value["section"], value["role"], value["quality"]) for value in evidence])
        self._db.commit()

    def _embed_inputs(self, texts: list[str], *, query: bool) -> list[str]:
        if self.embedding_model != DEFAULT_EMBEDDING_MODEL:
            return texts
        prefix = "query: " if query else "passage: "
        return [prefix + text for text in texts]

    def _index(self, evidence: list[dict[str, Any]], qdrant: Any, embedder: Any, *, collection: str | None = None) -> None:
        from qdrant_client import models
        collection = collection or self._active_collection()
        ordered = sorted(enumerate(evidence), key=lambda value: len(value[1]["text"]))
        vectors = list(embedder.embed(self._embed_inputs([item["text"] for _, item in ordered], query=False), batch_size=_EMBEDDING_BATCH_SIZE))
        if not vectors:
            raise RagError("RH_RAG_INDEX_FAILED", "embedding returned no vectors")
        by_position = {position: vector for (position, _), vector in zip(ordered, vectors)}
        if not qdrant.collection_exists(collection):
            qdrant.create_collection(collection, vectors_config=models.VectorParams(size=len(vectors[0]), distance=models.Distance.COSINE))
        points = [models.PointStruct(id=str(uuid.UUID(hashlib.sha256(item["evidence_id"].encode()).hexdigest()[:32])), vector=by_position[position].tolist(), payload={"evidence_id": item["evidence_id"], "version_id": item["version_id"] if "version_id" in item else None}) for position, item in enumerate(evidence)]
        qdrant.upsert(collection, points=points, wait=True)

    def rebuild_index(self) -> dict[str, Any]:
        """Build a complete temporary vector collection, then make it active."""
        evidence = [dict(row) for row in self._db.execute("SELECT evidence_id,version_id,text FROM rag_evidence ORDER BY evidence_id")]
        if not evidence:
            return {"outcome": "completed", "indexed": 0, "collection": self._active_collection(), "embedding_model": self._stored_embedding_model()}
        try:
            embedder, qdrant, _splitter = self._components(enforce_config=False)
        except RagError:
            raise
        except Exception as exc:
            raise RagError("RH_RAG_REBUILD_FAILED", "could not initialize the vector rebuild") from exc
        temporary = f"evidence-rebuild-{uuid.uuid4().hex}"

        def discard_temporary() -> None:
            try:
                if qdrant.collection_exists(temporary):
                    qdrant.delete_collection(temporary)
            except Exception:
                pass

        try:
            self._index(evidence, qdrant, embedder, collection=temporary)
            if qdrant.count(temporary, exact=True).count != len(evidence):
                raise RagError("RH_RAG_REBUILD_FAILED", "rebuilt vector count did not match evidence")
            self._db.execute("BEGIN")
            self._db.execute("INSERT OR REPLACE INTO rag_config VALUES ('active_collection', ?)", (temporary,))
            self._db.execute("INSERT OR REPLACE INTO rag_config VALUES ('index_fingerprint', ?)", (self._index_fingerprint(),))
            self._db.commit()
        except RagError:
            self._db.rollback()
            discard_temporary()
            raise
        except Exception as exc:
            self._db.rollback()
            discard_temporary()
            raise RagError("RH_RAG_REBUILD_FAILED", "could not rebuild the vector index") from exc
        return {"outcome": "completed", "indexed": len(evidence), "collection": temporary, "embedding_model": self.embedding_model}

    def _valid_filters(self, filters: dict[str, Any] | None) -> dict[str, Any]:
        if filters is None: return {}
        if not isinstance(filters, dict) or set(filters) - _ALLOWED_FILTERS:
            raise RagError("RH_RAG_INVALID_INPUT", "unsupported search filter")
        list_fields = {"document_ids", "version_ids", "doi", "types"}
        for field in list_fields - {"doi"}:
            if field in filters and (not isinstance(filters[field], list) or not all(isinstance(value, str) and value for value in filters[field])):
                raise RagError("RH_RAG_INVALID_INPUT", "filter values are invalid")
        if "doi" in filters and not (isinstance(filters["doi"], str) and filters["doi"] or isinstance(filters["doi"], list) and filters["doi"] and all(isinstance(value, str) and value for value in filters["doi"])):
            raise RagError("RH_RAG_INVALID_INPUT", "filter values are invalid")
        for field in ("year_min", "year_max"):
            if field in filters and (not isinstance(filters[field], int) or isinstance(filters[field], bool) or not 1000 <= filters[field] <= 3000):
                raise RagError("RH_RAG_INVALID_INPUT", "year filter is invalid")
        return filters

    def _candidates(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        clauses = ["e.version_id=d.current_version_id"] if "version_ids" not in filters else ["1=1"]
        values: list[Any] = []
        mapping = {"document_ids": "e.document_id", "version_ids": "e.version_id", "doi": "d.doi", "types": "d.document_type"}
        for key, column in mapping.items():
            if key in filters:
                item_values = filters[key] if isinstance(filters[key], list) else [filters[key]]
                if not item_values: return []
                clauses.append(f"{column} IN ({','.join('?' for _ in item_values)})"); values.extend(item_values)
        for key, op in (("year_min", ">="), ("year_max", "<=")):
            if key in filters: clauses.append(f"d.year {op} ?"); values.append(filters[key])
        rows = self._db.execute("SELECT e.*,d.title,d.doi,d.year,d.document_type,v.source_path FROM rag_evidence e JOIN rag_documents d ON d.document_id=e.document_id JOIN rag_versions v ON v.version_id=e.version_id WHERE " + " AND ".join(clauses), values).fetchall()
        return [dict(row) for row in rows]

    def search_evidence(self, query: str, *, top_k: int = 8, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        if not isinstance(query, str) or not query.strip() or not isinstance(top_k, int) or not 1 <= top_k <= 30:
            raise RagError("RH_RAG_INVALID_INPUT", "query and top_k are invalid")
        filters = self._valid_filters(filters); candidates = self._candidates(filters)
        if not candidates: return {"query": query, "items": [], "snapshot_version_ids": [], "diagnostics": {"mode": "hybrid", "embedding_model": self._stored_embedding_model(), "lexical_hits": 0, "vector_hits": 0, "coverage_limits": ["no evidence in selected scope"]}}
        embedder, qdrant, _splitter = self._components()
        candidate_versions = sorted({item["version_id"] for item in candidates})
        collection = self._active_collection()
        if not qdrant.collection_exists(collection) or not all(self._version_is_indexed(version_id) for version_id in candidate_versions):
            raise RagError("RH_RAG_INDEX_INCOMPLETE", "selected evidence is not fully indexed")
        query_vector = list(embedder.embed(self._embed_inputs([query], query=True), batch_size=_EMBEDDING_BATCH_SIZE))[0].tolist()
        allowed = {item["evidence_id"] for item in candidates}
        vector_scores: dict[str, float] = {}
        from qdrant_client import models
        query_filter = models.Filter(must=[models.FieldCondition(key="version_id", match=models.MatchAny(any=candidate_versions))])
        hits = qdrant.query_points(collection, query=query_vector, query_filter=query_filter, limit=len(candidates)).points
        vector_scores = {hit.payload["evidence_id"]: float(hit.score) for hit in hits if hit.payload and hit.payload.get("evidence_id") in allowed}
        query_tokens = _tokens(query)
        lexical_scores: dict[str, int] = {}
        for item in candidates:
            item_tokens = _tokens(item["text"])
            lexical_scores[item["evidence_id"]] = sum(
                min(count, item_tokens[token]) for token, count in query_tokens.items()
            )
        scores = {item["evidence_id"]: vector_scores.get(item["evidence_id"], 0.0) + lexical_scores[item["evidence_id"]] / max(1, sum(query_tokens.values())) for item in candidates}
        ranked = sorted(candidates, key=lambda item: (scores[item["evidence_id"]], item["evidence_id"]), reverse=True)[:top_k]
        return {"query": query, "items": [self._item(item, scores[item["evidence_id"]]) for item in ranked], "snapshot_version_ids": sorted({item["version_id"] for item in ranked}), "diagnostics": {"mode": "hybrid", "embedding_model": self._stored_embedding_model(), "lexical_hits": sum(value > 0 for value in lexical_scores.values()), "vector_hits": len(vector_scores), "coverage_limits": ["PDF layout tables retain Docling extraction quality notes"]}}

    @staticmethod
    def _item(row: dict[str, Any], score: float | None = None) -> dict[str, Any]:
        item = {key: row[key] for key in ("evidence_id", "document_id", "version_id", "text", "title", "doi", "year", "document_type", "source_path", "section", "role", "quality")}
        item["locator"] = json.loads(row["locator"])
        if score is not None: item["score"] = score
        return item

    def get_evidence_context(self, evidence_id: str, *, before: int = 1, after: int = 1) -> dict[str, Any]:
        if not isinstance(before, int) or not isinstance(after, int) or not 0 <= before <= 3 or not 0 <= after <= 3:
            raise RagError("RH_RAG_INVALID_INPUT", "context window must be between zero and three")
        hit = self._db.execute("SELECT * FROM rag_evidence WHERE evidence_id=?", (evidence_id,)).fetchone()
        if not hit: raise RagError("RH_RAG_NOT_FOUND", "evidence was not found")
        rows = [dict(row) for row in self._db.execute("SELECT e.*,d.title,d.doi,d.year,d.document_type,v.source_path FROM rag_evidence e JOIN rag_documents d ON d.document_id=e.document_id JOIN rag_versions v ON v.version_id=e.version_id WHERE e.document_id=? AND e.version_id=? ORDER BY e.ordinal", (hit["document_id"], hit["version_id"]))]
        position = next(index for index, row in enumerate(rows) if row["evidence_id"] == evidence_id)
        hit_row = rows[position]
        def duplicate_caption(row: dict[str, Any]) -> bool:
            return hit_row["role"] == "table" and row.get("role") != "table" and bool(hit_row.get("section")) and row["text"].strip() == hit_row["section"].strip()
        left = [row for row in reversed(rows[:position]) if not duplicate_caption(row)][:before]
        right = [row for row in rows[position + 1:] if not duplicate_caption(row)][:after]
        selected = list(reversed(left)) + [hit_row] + right
        return {"evidence_id": evidence_id, "items": [self._item(row) for row in selected]}

    def get_document(self, document_id: str) -> dict[str, Any]:
        row = self._db.execute("SELECT * FROM rag_documents WHERE document_id=?", (document_id,)).fetchone()
        if not row: raise RagError("RH_RAG_NOT_FOUND", "document was not found")
        result = dict(row); result["errors"] = json.loads(result["errors"]); result["versions"] = [dict(version) for version in self._db.execute("SELECT * FROM rag_versions WHERE document_id=? ORDER BY created", (document_id,))]
        for version in result["versions"]: version["errors"] = json.loads(version["errors"])
        return result

    def get_library_status(self) -> dict[str, Any]:
        documents = [dict(row) for row in self._db.execute("SELECT document_id,title,doi,document_type,year,current_version_id,parse_status FROM rag_documents ORDER BY title")]
        indexed = sum(bool(item["current_version_id"]) and self._version_is_indexed(item["current_version_id"]) for item in documents)
        completed = sum(item["parse_status"] == "completed" for item in documents)
        index_status = "empty" if not documents else "ready" if indexed == completed and completed else "partial"
        return {"document_count": len(documents), "version_count": self._db.execute("SELECT COUNT(*) FROM rag_versions").fetchone()[0], "evidence_count": self._db.execute("SELECT COUNT(*) FROM rag_evidence").fetchone()[0], "indexed_document_count": indexed, "failed_document_count": sum(item["parse_status"] == "failed" for item in documents), "embedding_model": self._stored_embedding_model(), "index_status": index_status, "documents": documents}


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="python -m research_harness.rag")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--embedding-model")
    commands = parser.add_subparsers(dest="command", required=True)
    imported = commands.add_parser("import"); imported.add_argument("catalog"); imported.add_argument("--limit", type=int)
    prepared = commands.add_parser("prepare"); prepared.add_argument("catalog"); prepared.add_argument("--limit", type=int)
    commands.add_parser("rebuild")
    searched = commands.add_parser("search"); searched.add_argument("query"); searched.add_argument("--top-k", type=int, default=8); searched.add_argument("--filters")
    context = commands.add_parser("context"); context.add_argument("evidence_id"); context.add_argument("--before", type=int, default=1); context.add_argument("--after", type=int, default=1)
    document = commands.add_parser("document"); document.add_argument("document_id")
    commands.add_parser("status")
    args = parser.parse_args(argv)
    try:
        with RagLibrary(args.workspace, embedding_model=args.embedding_model) as library:
            if args.command == "import": result = library.import_library(args.catalog, limit=args.limit)
            elif args.command == "prepare": result = library.prepare_library(args.catalog, limit=args.limit)
            elif args.command == "rebuild": result = library.rebuild_index()
            elif args.command == "search": result = library.search_evidence(args.query, top_k=args.top_k, filters=json.loads(args.filters) if args.filters else None)
            elif args.command == "context": result = library.get_evidence_context(args.evidence_id, before=args.before, after=args.after)
            elif args.command == "document": result = library.get_document(args.document_id)
            else: result = library.get_library_status()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 4 if result.get("outcome") == "partial" else 3 if result.get("outcome") == "failed" else 0
    except RagError as error:
        print(json.dumps(error.to_dict(), ensure_ascii=False), file=sys.stderr); return 2
    except (json.JSONDecodeError, ValueError):
        print(json.dumps(RagError("RH_RAG_INVALID_INPUT", "invalid RAG command input").to_dict()), file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
