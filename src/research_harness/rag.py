"""Local, provenance-preserving library for the D18 evidence RAG boundary."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import shutil
import tempfile
import argparse
import sys
from xml.etree import ElementTree
from importlib.metadata import PackageNotFoundError, version as package_version
import uuid
from collections import Counter
from contextlib import AbstractContextManager
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Iterator


DEFAULT_EMBEDDING_MODEL = "intfloat/multilingual-e5-small"
_LEGACY_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
_ALLOWED_FILTERS = {"document_ids", "version_ids", "revision_ids", "doi", "year_min", "year_max", "types"}
_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff]")
_WORD_RE = re.compile(r"[\w-]+", re.UNICODE)
_CHUNK_SIZE = 200
_CHUNK_OVERLAP = 30
_PARSER_FINGERPRINT = "docling-pypdfium2-no-ocr-table-structure-no-cell-match-visible-provenance-v3"
_EMBEDDING_DIMENSION = 384
_EMBEDDING_THREADS = 2
_EMBEDDING_BATCH_SIZE = 16
_RRF_K = 60


@lru_cache(maxsize=8192)
def _english_stem(token: str) -> str:
    if not token.isascii() or not token.isalpha():
        return token
    from nltk.stem.snowball import SnowballStemmer
    return SnowballStemmer("english", ignore_stopwords=False).stem(token)


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
    return Counter(_english_stem(token) for token in tokens if len(token) > 1)


class RagLibrary(AbstractContextManager["RagLibrary"]):
    """A workspace-scoped, local evidence library.

    Imports deliberately retain the original source location and extracted
    provenance. The index contains only derived vectors and metadata.
    """

    def __init__(self, workspace: str | Path, *, embedding_model: str | None = None, read_only: bool = False):
        self.root = Path(workspace).resolve()
        self.read_only = read_only
        if read_only:
            if not (self.root / "rag.sqlite").is_file() or not (self.root / "qdrant").is_dir():
                raise RagError("RH_RAG_NOT_FOUND", "read-only RAG index is missing")
        else:
            self.root.mkdir(parents=True, exist_ok=True)
            (self.root / "raw").mkdir(exist_ok=True)
        self.embedding_model = embedding_model or DEFAULT_EMBEDDING_MODEL
        self._db = sqlite3.connect((self.root / "rag.sqlite").as_uri() + "?mode=ro" if read_only else self.root / "rag.sqlite", uri=read_only)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys=ON")
        if not read_only:
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
            CREATE TABLE IF NOT EXISTS rag_parse_revisions (
              parse_revision_id TEXT PRIMARY KEY, version_id TEXT NOT NULL,
              parser_fingerprint TEXT NOT NULL, parser_config TEXT NOT NULL,
              output_sha256 TEXT NOT NULL, page_count INTEGER,
              coverage TEXT NOT NULL, errors TEXT NOT NULL,
              evidence_count INTEGER NOT NULL, created REAL NOT NULL,
              UNIQUE(version_id, parser_fingerprint, output_sha256),
              FOREIGN KEY(version_id) REFERENCES rag_versions(version_id)
            );
            CREATE TABLE IF NOT EXISTS rag_evidence_parse_revisions (
              evidence_id TEXT PRIMARY KEY, parse_revision_id TEXT NOT NULL,
              FOREIGN KEY(evidence_id) REFERENCES rag_evidence(evidence_id),
              FOREIGN KEY(parse_revision_id) REFERENCES rag_parse_revisions(parse_revision_id)
            );
            CREATE INDEX IF NOT EXISTS rag_evidence_parse_revision ON rag_evidence_parse_revisions(parse_revision_id);
            CREATE TABLE IF NOT EXISTS rag_parse_state (
              version_id TEXT PRIMARY KEY, current_revision_id TEXT NOT NULL,
              FOREIGN KEY(version_id) REFERENCES rag_versions(version_id),
              FOREIGN KEY(current_revision_id) REFERENCES rag_parse_revisions(parse_revision_id)
            );
            """
        )
            version_columns = {row[1] for row in self._db.execute("PRAGMA table_info(rag_versions)")}
            if "source_path" not in version_columns:
                self._db.execute("ALTER TABLE rag_versions ADD COLUMN source_path TEXT")
            self._db.commit()
        self._parse_revision_tables = self._tables_exist("rag_parse_revisions", "rag_evidence_parse_revisions", "rag_parse_state")
        self._embedder: Any | None = None
        self._qdrant: Any | None = None
        self._converter: Any | None = None
        self._bm25_cache: dict[tuple[str, ...], tuple[Any, list[list[str]]]] = {}
        self._read_index_copy = None

    def __exit__(self, *_: Any) -> None:
        self.close()

    def close(self) -> None:
        if self._qdrant is not None:
            self._qdrant.close()
            self._qdrant = None
        self._db.close()
        if self._read_index_copy is not None:
            self._read_index_copy.cleanup()

    def _components(self, *, enforce_config: bool = True) -> tuple[Any, Any, Any]:
        if enforce_config and not self.read_only:
            self._ensure_index_config()
        elif enforce_config:
            saved = self._db.execute("SELECT value FROM rag_config WHERE key='index_fingerprint'").fetchone()
            if not saved:
                raise RagError("RH_RAG_INDEX_INCOMPLETE", "read-only RAG index configuration is missing")
            if not self._same_embedding_config(saved["value"], self._index_fingerprint()):
                raise RagError("RH_RAG_CONFIG_MISMATCH", "read-only RAG index configuration differs")
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
                index_path = self.root / "qdrant"
                if self.read_only:
                    self._read_index_copy = tempfile.TemporaryDirectory(prefix="rag-read-index-")
                    index_path = Path(self._read_index_copy.name) / "qdrant"
                    shutil.copytree(self.root / "qdrant", index_path, ignore=shutil.ignore_patterns(".lock"))
                self._qdrant = QdrantClient(path=str(index_path))
            except RuntimeError as exc:
                raise RagError("RH_RAG_BUSY", "RAG workspace index is in use") from exc
        return self._embedder, self._qdrant, SentenceSplitter

    def _index_fingerprint(self) -> str:
        preprocessing = "fastembed-0.8-mean-pooling-normalized-e5-query-passage" if self.embedding_model == DEFAULT_EMBEDDING_MODEL else "fastembed-0.8-mean-pooling"
        try:
            fastembed_version = package_version("fastembed")
        except PackageNotFoundError as exc:
            raise RagError("RH_RAG_DEPENDENCY", "RAG dependencies are not installed") from exc
        return json.dumps({"embedding_model": self.embedding_model, "embedding_dimension": _EMBEDDING_DIMENSION, "embedding_preprocessing": preprocessing, "fastembed": fastembed_version}, sort_keys=True)

    @staticmethod
    def _same_embedding_config(saved: str, current: str) -> bool:
        keys = ("embedding_model", "embedding_dimension", "embedding_preprocessing", "fastembed")
        try:
            previous, requested = json.loads(saved), json.loads(current)
            return all(previous.get(key) == requested.get(key) for key in keys)
        except (TypeError, ValueError):
            return False

    def _tables_exist(self, *names: str) -> bool:
        rows = self._db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        existing = {row["name"] for row in rows}
        return all(name in existing for name in names)

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
        if saved and saved["value"] != fingerprint:
            if self._same_embedding_config(saved["value"], fingerprint):
                self._db.execute("UPDATE rag_config SET value=? WHERE key='index_fingerprint'", (fingerprint,))
            elif self._db.execute("SELECT COUNT(*) FROM rag_evidence").fetchone()[0]:
                raise RagError("RH_RAG_CONFIG_MISMATCH", "embedding configuration differs; rebuild the index before use")
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
        if path.suffix.casefold() == ".xml":
            try:
                root=ElementTree.parse(path).getroot()
            except ElementTree.ParseError as exc:
                raise RagError("RH_RAG_PARSE_FAILED", "invalid patent XML") from exc
            blocks=[]
            for index,node in enumerate(root.iter(),1):
                name=node.tag.rsplit("}",1)[-1]
                if name not in {"p","paragraph","claim"}: continue
                text=" ".join(" ".join(node.itertext()).split())
                if text:
                    blocks.append({"text":text,"locator":{"kind":"xml_node","value":node.get("id") or node.get("num") or str(index)},"section":name,"role":"text"})
            if not blocks: raise RagError("RH_RAG_PARSE_FAILED", "patent XML has no paragraphs or claims")
            return blocks,None,"full_text",[]
        if path.suffix.casefold() != ".txt":
            raise RagError("RH_RAG_UNSUPPORTED", "only PDF, TXT and XML files are supported")
        text = path.read_text(encoding="utf-8", errors="replace")
        return ([{"text": text, "locator": {"line_start": 1, "line_end": text.count("\n") + 1}, "section": None, "role": "text"}], None, "full_text", [])

    @staticmethod
    def _docling_version() -> str:
        try:
            return package_version("docling")
        except Exception:
            return "unavailable"

    def _parser_configuration(self) -> dict[str, Any]:
        try:
            splitter_version = package_version("llama-index-core")
        except Exception:
            splitter_version = "unavailable"
        return {"parser": _PARSER_FINGERPRINT, "docling": self._docling_version(),
                "chunker": "llama-index-sentence-splitter", "chunker_version": splitter_version,
                "chunk_size": _CHUNK_SIZE, "chunk_overlap": _CHUNK_OVERLAP}

    @staticmethod
    def _parse_revision_id(version_id: str, source_sha256: str, parser_config: dict[str, Any], output_sha256: str) -> tuple[str, str]:
        config_sha256 = hashlib.sha256(json.dumps(parser_config, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        identity = json.dumps({"version_id": version_id, "source_sha256": source_sha256,
                               "parser_config_sha256": config_sha256, "output_sha256": output_sha256},
                              sort_keys=True, separators=(",", ":"))
        return "pr-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24], config_sha256

    def _legacy_parse_revision_id(self, version_id: str) -> str:
        version = self._db.execute("SELECT content_sha256,parser FROM rag_versions WHERE version_id=?", (version_id,)).fetchone()
        if self._parse_revision_tables:
            rows = self._db.execute("SELECT e.evidence_id,e.text,e.locator,e.section,e.role,e.quality FROM rag_evidence e LEFT JOIN rag_evidence_parse_revisions p ON p.evidence_id=e.evidence_id WHERE e.version_id=? AND p.evidence_id IS NULL ORDER BY e.ordinal,e.evidence_id", (version_id,)).fetchall()
        else:
            rows = self._db.execute("SELECT evidence_id,text,locator,section,role,quality FROM rag_evidence WHERE version_id=? ORDER BY ordinal,evidence_id", (version_id,)).fetchall()
        if not version or not version["parser"] or not version["content_sha256"] or not rows:
            return "pr-unresolved-" + hashlib.sha256(version_id.encode("utf-8")).hexdigest()[:24]
        output_sha = hashlib.sha256(json.dumps([tuple(row) for row in rows], ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
        identity = json.dumps({"legacy": True, "version_id": version_id, "source_sha256": version["content_sha256"],
                               "parser": version["parser"], "evidence_output_sha256": output_sha}, sort_keys=True, separators=(",", ":"))
        return "pr-legacy-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]

    def _revision_for_evidence(self, evidence_id: str, version_id: str) -> str:
        if self._parse_revision_tables:
            row = self._db.execute("SELECT parse_revision_id FROM rag_evidence_parse_revisions WHERE evidence_id=?", (evidence_id,)).fetchone()
            if row:
                return row["parse_revision_id"]
        return self._legacy_parse_revision_id(version_id)

    def _current_parse_revision_id(self, version_id: str) -> str:
        if self._parse_revision_tables:
            row = self._db.execute("SELECT current_revision_id FROM rag_parse_state WHERE version_id=?", (version_id,)).fetchone()
            if row:
                return row["current_revision_id"]
        return self._legacy_parse_revision_id(version_id)

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

    def _build_parse_revision(self, source: Path, document_id: str, version_id: str, digest: str) -> tuple[dict[str, Any], list[dict[str, Any]], Any, Any]:
        blocks, pages, coverage, parse_errors, _cache_reused = self._parse_with_cache(source, digest)
        embedder, qdrant, splitter = self._components()
        chunks = list(self._chunks(blocks, splitter))
        if not chunks:
            raise RagError("RH_RAG_PARSE_FAILED", "parser returned no usable evidence")
        parser_config = self._parser_configuration()
        output_sha256 = hashlib.sha256(json.dumps(chunks, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        parse_revision_id, parser_fingerprint = self._parse_revision_id(version_id, digest, parser_config, output_sha256)
        evidence = []
        for ordinal, chunk in enumerate(chunks, 1):
            evidence_id = "ev-" + hashlib.sha256(f"{version_id}:{parse_revision_id}:{ordinal}".encode()).hexdigest()[:24]
            evidence.append({"evidence_id": evidence_id, "ordinal": ordinal, "document_id": document_id,
                             "version_id": version_id, "parse_revision_id": parse_revision_id, **chunk})
        revision = {"parse_revision_id": parse_revision_id, "version_id": version_id,
                    "parser_fingerprint": parser_fingerprint,
                    "parser_config": json.dumps(parser_config, sort_keys=True, separators=(",", ":")),
                    "output_sha256": output_sha256, "source_sha256": digest,
                    "page_count": pages, "coverage": coverage,
                    "errors": list(parse_errors), "evidence_count": len(evidence)}
        return revision, evidence, embedder, qdrant

    def _revision_indexed(self, parse_revision_id: str) -> bool:
        version_id = None
        if self._parse_revision_tables:
            row = self._db.execute("SELECT version_id FROM rag_parse_revisions WHERE parse_revision_id=?", (parse_revision_id,)).fetchone()
            version_id = row["version_id"] if row else None
        if version_id is None:
            for row in self._db.execute("SELECT version_id FROM rag_versions"):
                if self._legacy_parse_revision_id(row["version_id"]) == parse_revision_id:
                    version_id = row["version_id"]
                    break
        if version_id and self._current_parse_revision_id(version_id) == parse_revision_id:
            return self._version_is_indexed(version_id)
        return self._revision_indexed_exact(parse_revision_id)

    def _revision_indexed_exact(self, parse_revision_id: str) -> bool:
        if parse_revision_id.startswith("pr-legacy-") or parse_revision_id.startswith("pr-unresolved-"):
            for row in self._db.execute("SELECT version_id FROM rag_versions"):
                if self._legacy_parse_revision_id(row["version_id"]) == parse_revision_id:
                    return self._legacy_version_indexed(row["version_id"])
            return False
        row = self._db.execute("SELECT evidence_count FROM rag_parse_revisions WHERE parse_revision_id=?", (parse_revision_id,)).fetchone()
        if not row or not row["evidence_count"]:
            return False
        try:
            from qdrant_client import QdrantClient, models
            if self._qdrant is None:
                self._qdrant = QdrantClient(path=str(self.root / "qdrant"))
            collection = self._active_collection()
            if not self._qdrant.collection_exists(collection):
                return False
            query_filter = models.Filter(must=[models.FieldCondition(key="parse_revision_id", match=models.MatchValue(value=parse_revision_id))])
            return self._qdrant.count(collection, count_filter=query_filter, exact=True).count == row["evidence_count"]
        except RagError:
            raise
        except RuntimeError as exc:
            raise RagError("RH_RAG_BUSY", "RAG workspace index is in use") from exc
        except ImportError as exc:
            raise RagError("RH_RAG_DEPENDENCY", "RAG dependencies are not installed") from exc
        except Exception as exc:
            raise RagError("RH_RAG_INDEX_UNAVAILABLE", "could not inspect the vector index") from exc

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
            try:
                digest = hashlib.sha256(source.read_bytes()).hexdigest()
                old = self._db.execute("SELECT version_id FROM rag_versions WHERE document_id=? AND content_sha256=?", (document_id, digest)).fetchone()
                version_id = old["version_id"] if old else "ver-" + hashlib.sha256(f"{document_id}:{digest}".encode()).hexdigest()[:24]
                self._ensure_index_config()
                revision, evidence, embedder, qdrant = self._build_parse_revision(source, document_id, version_id, digest)
                current_revision = self._current_parse_revision_id(version_id) if old else None
                if old and current_revision == revision["parse_revision_id"] and self._version_is_indexed(version_id):
                    reused += 1; documents.append({"document_id": document_id, "version_id": version_id, "parse_revision_id": revision["parse_revision_id"], "parse_status": "reused", "evidence_count": len(evidence)}); continue
                self._index(evidence, qdrant, embedder)
                raw_path = self._copy_source(source, version_id)
                self._store_document(record, raw_path, document_id, version_id, digest, revision, evidence)
                imported += 1; documents.append({"document_id": document_id, "version_id": version_id, "parse_revision_id": revision["parse_revision_id"], "parse_status": "completed", "evidence_count": len(evidence)})
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

    def reparse_document(self, document_id: str, version_id: str | None = None) -> dict[str, Any]:
        if self.read_only:
            raise RagError("RH_RAG_READ_ONLY", "RAG workspace is read only")
        document = self._db.execute("SELECT * FROM rag_documents WHERE document_id=?", (document_id,)).fetchone()
        if not document:
            raise RagError("RH_RAG_NOT_FOUND", "document was not found")
        selected_version = version_id or document["current_version_id"]
        if not selected_version:
            raise RagError("RH_RAG_NOT_FOUND", "document has no source version to reparse")
        version = self._db.execute("SELECT * FROM rag_versions WHERE version_id=? AND document_id=?", (selected_version, document_id)).fetchone()
        if not version:
            raise RagError("RH_RAG_NOT_FOUND", "source version does not belong to this document")
        return self._reparse_version(version, dict(document))

    def reparse_version(self, version_id: str, *, document_id: str | None = None) -> dict[str, Any]:
        if self.read_only:
            raise RagError("RH_RAG_READ_ONLY", "RAG workspace is read only")
        version = self._db.execute("SELECT * FROM rag_versions WHERE version_id=?", (version_id,)).fetchone()
        if not version or (document_id is not None and version["document_id"] != document_id):
            raise RagError("RH_RAG_NOT_FOUND", "source version was not found")
        document = self._db.execute("SELECT * FROM rag_documents WHERE document_id=?", (version["document_id"],)).fetchone()
        if not document:
            raise RagError("RH_RAG_NOT_FOUND", "document was not found")
        return self._reparse_version(version, dict(document))

    def _reparse_version(self, version: Any, document: dict[str, Any]) -> dict[str, Any]:
        self._ensure_index_config()
        source_value = version["source_path"]
        source = Path(source_value)
        if not source.is_absolute():
            source = (self.root / source).resolve()
        if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != version["content_sha256"]:
            raise RagError("RH_RAG_SOURCE_UNAVAILABLE", "immutable source bytes for this version are unavailable")
        revision, evidence, embedder, qdrant = self._build_parse_revision(source, document["document_id"], version["version_id"], version["content_sha256"])
        existing = self._db.execute("SELECT 1 FROM rag_parse_revisions WHERE parse_revision_id=?", (revision["parse_revision_id"],)).fetchone()
        indexed = bool(existing and self._revision_indexed(revision["parse_revision_id"]))
        if not indexed:
            self._index(evidence, qdrant, embedder)
        record = {"title": document["title"], "doi": document["doi"], "year": document["year"], "type": document["document_type"]}
        self._store_document(record, source, document["document_id"], version["version_id"], version["content_sha256"], revision, evidence,
                             update_document_metadata=version["version_id"] == document.get("current_version_id"))
        return {"outcome": "completed", "document_id": document["document_id"], "version_id": version["version_id"],
                "parse_revision_id": revision["parse_revision_id"], "evidence_count": revision["evidence_count"],
                "reused": indexed}

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
        revision_id = self._current_parse_revision_id(version_id)
        if revision_id.startswith("pr-legacy-") or revision_id.startswith("pr-unresolved-"):
            return self._legacy_version_indexed(version_id)
        return self._revision_indexed_exact(revision_id)

    def _legacy_version_indexed(self, version_id: str) -> bool:
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
        except ImportError as exc:
            raise RagError("RH_RAG_DEPENDENCY", "RAG dependencies are not installed") from exc
        except Exception as exc:
            raise RagError("RH_RAG_INDEX_UNAVAILABLE", "could not inspect the vector index") from exc

    def _copy_source(self, source: Path, version_id: str) -> Path:
        destination = self.root / "raw" / f"{version_id}{source.suffix.casefold()}"
        expected = hashlib.sha256(source.read_bytes()).hexdigest()
        if destination.exists():
            if hashlib.sha256(destination.read_bytes()).hexdigest() != expected:
                raise RagError("RH_RAG_SOURCE_IMMUTABLE", "stored raw source differs from the source version")
        else:
            temporary = destination.with_name(f"{destination.name}.{uuid.uuid4().hex}.tmp")
            try:
                temporary.write_bytes(source.read_bytes())
                temporary.replace(destination)
            finally:
                if temporary.exists():
                    temporary.unlink()
        return destination

    def _record_failure(self, record: dict[str, Any], source: Path, document_id: str, error: RagError) -> None:
        self._db.execute("INSERT OR IGNORE INTO rag_documents VALUES (?,?,?,?,?,?,?,?,?,?)", (document_id, str(record.get("title") or source.name), record.get("doi"), record.get("year"), record.get("type"), str(source), None, "failed", "unknown", json.dumps([error.to_dict()])))
        self._db.execute("UPDATE rag_documents SET parse_status='failed',coverage='unknown',errors=? WHERE document_id=? AND current_version_id IS NULL", (json.dumps([error.to_dict()]), document_id))
        self._db.commit()

    def _store_document(self, record: dict[str, Any], source: Path, document_id: str, version_id: str, digest: str, revision: dict[str, Any], evidence: list[dict[str, Any]], *, update_document_metadata: bool = True) -> None:
        title = str(record.get("title") or source.name)
        errors = json.dumps(revision["errors"])
        self._db.execute("BEGIN IMMEDIATE")
        try:
            self._db.execute("INSERT OR IGNORE INTO rag_documents VALUES (?,?,?,?,?,?,?,?,?,?)", (document_id, title, record.get("doi"), record.get("year"), record.get("type"), str(source), version_id, "completed", revision["coverage"], errors))
            self._db.execute("INSERT OR IGNORE INTO rag_versions (version_id,document_id,content_sha256,parser,page_count,coverage,errors,source_path,created) VALUES (?,?,?,?,?,?,?,?,strftime('%s','now'))", (version_id, document_id, digest, _PARSER_FINGERPRINT, revision["page_count"], revision["coverage"], errors, str(source)))
            if update_document_metadata:
                self._db.execute("UPDATE rag_documents SET title=?,doi=?,year=?,document_type=?,source_path=?,current_version_id=?,parse_status='completed',coverage=?,errors=? WHERE document_id=?", (title, record.get("doi"), record.get("year"), record.get("type"), str(source), version_id, revision["coverage"], errors, document_id))
            exists = self._db.execute("SELECT 1 FROM rag_parse_revisions WHERE parse_revision_id=?", (revision["parse_revision_id"],)).fetchone()
            if not exists:
                self._db.execute("INSERT INTO rag_parse_revisions VALUES (?,?,?,?,?,?,?,?,?,strftime('%s','now'))", (revision["parse_revision_id"], version_id, revision["parser_fingerprint"], revision["parser_config"], revision["output_sha256"], revision["page_count"], revision["coverage"], errors, revision["evidence_count"]))
                self._db.executemany("INSERT INTO rag_evidence VALUES (?,?,?,?,?,?,?,?,?)", [(value["evidence_id"], document_id, version_id, value["ordinal"], value["text"], json.dumps(value["locator"], ensure_ascii=False), value["section"], value["role"], value["quality"]) for value in evidence])
                self._db.executemany("INSERT INTO rag_evidence_parse_revisions VALUES (?,?)", [(value["evidence_id"], revision["parse_revision_id"]) for value in evidence])
            else:
                existing_count = self._db.execute("SELECT COUNT(*) FROM rag_evidence_parse_revisions WHERE parse_revision_id=?", (revision["parse_revision_id"],)).fetchone()[0]
                if existing_count != revision["evidence_count"]:
                    raise RagError("RH_RAG_REVISION_INCOMPLETE", "parse revision evidence is incomplete")
            self._db.execute("INSERT OR REPLACE INTO rag_parse_state VALUES (?,?)", (version_id, revision["parse_revision_id"]))
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise

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
        if len(vectors) != len(evidence):
            raise RagError("RH_RAG_INDEX_FAILED", "embedding returned no vectors")
        by_position = {position: vector for (position, _), vector in zip(ordered, vectors)}
        if not qdrant.collection_exists(collection):
            qdrant.create_collection(collection, vectors_config=models.VectorParams(size=len(vectors[0]), distance=models.Distance.COSINE))
        points = []
        for position, item in enumerate(evidence):
            payload = {"evidence_id": item["evidence_id"], "version_id": item.get("version_id")}
            if item.get("parse_revision_id"):
                payload["parse_revision_id"] = item["parse_revision_id"]
            points.append(models.PointStruct(id=str(uuid.UUID(hashlib.sha256(item["evidence_id"].encode()).hexdigest()[:32])), vector=by_position[position].tolist(), payload=payload))
        qdrant.upsert(collection, points=points, wait=True)
        try:
            if collection.startswith("evidence-rebuild-"):
                indexed_count = qdrant.count(collection, exact=True).count
                expected_count = len(evidence)
            else:
                revision_ids = {item.get("parse_revision_id") for item in evidence}
                if len(revision_ids) != 1 or not next(iter(revision_ids)):
                    raise RagError("RH_RAG_INDEX_FAILED", "indexed evidence does not belong to one parse revision")
                parse_revision_id = next(iter(revision_ids))
                count_filter = models.Filter(must=[models.FieldCondition(key="parse_revision_id", match=models.MatchValue(value=parse_revision_id))])
                indexed_count = qdrant.count(collection, count_filter=count_filter, exact=True).count
                expected_count = len(evidence)
            if indexed_count != expected_count:
                raise RagError("RH_RAG_INDEX_FAILED", "indexed evidence count did not match the parse revision")
        except RagError:
            raise
        except Exception as exc:
            raise RagError("RH_RAG_INDEX_FAILED", "could not verify indexed evidence count") from exc

    def rebuild_index(self) -> dict[str, Any]:
        """Build a complete temporary vector collection, then make it active."""
        evidence = [dict(row) for row in self._db.execute("SELECT evidence_id,version_id,text FROM rag_evidence ORDER BY evidence_id")]
        for item in evidence:
            item["parse_revision_id"] = self._revision_for_evidence(item["evidence_id"], item["version_id"])
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
        list_fields = {"document_ids", "version_ids", "revision_ids", "doi", "types"}
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
        clauses = ["e.version_id=d.current_version_id"] if "version_ids" not in filters and "revision_ids" not in filters else ["1=1"]
        values: list[Any] = []
        mapping = {"document_ids": "e.document_id", "version_ids": "e.version_id", "doi": "d.doi", "types": "d.document_type"}
        for key, column in mapping.items():
            if key in filters:
                item_values = filters[key] if isinstance(filters[key], list) else [filters[key]]
                if not item_values: return []
                clauses.append(f"{column} IN ({','.join('?' for _ in item_values)})"); values.extend(item_values)
        for key, op in (("year_min", ">="), ("year_max", "<=")):
            if key in filters: clauses.append(f"d.year {op} ?"); values.append(filters[key])
        rows = self._db.execute("SELECT e.*,d.title,d.doi,d.year,d.document_type,d.current_version_id,v.source_path,v.content_sha256 AS source_sha256 FROM rag_evidence e JOIN rag_documents d ON d.document_id=e.document_id JOIN rag_versions v ON v.version_id=e.version_id WHERE " + " AND ".join(clauses), values).fetchall()
        revision_filter = set(filters.get("revision_ids", [])) if "revision_ids" in filters else None
        candidates = []
        for row in rows:
            item = dict(row)
            revision_id = self._revision_for_evidence(item["evidence_id"], item["version_id"])
            if revision_filter is not None:
                if revision_id not in revision_filter:
                    continue
            elif revision_id != self._current_parse_revision_id(item["version_id"]):
                continue
            item["parse_revision_id"] = revision_id
            candidates.append(item)
        return candidates

    def search_evidence(self, query: str, *, top_k: int = 8, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        if not isinstance(query, str) or not query.strip() or not isinstance(top_k, int) or not 1 <= top_k <= 30:
            raise RagError("RH_RAG_INVALID_INPUT", "query and top_k are invalid")
        filters = self._valid_filters(filters); candidates = self._candidates(filters)
        if not candidates: return {"query": query, "items": [], "snapshot_version_ids": [], "snapshot_parse_revision_ids": [], "diagnostics": {"mode": "hybrid", "embedding_model": self._stored_embedding_model(), "lexical_hits": 0, "vector_hits": 0, "coverage_limits": ["no evidence in selected scope"]}}
        embedder, qdrant, _splitter = self._components()
        candidate_revisions = sorted({item["parse_revision_id"] for item in candidates})
        collection = self._active_collection()
        if not qdrant.collection_exists(collection) or not all(self._revision_indexed(revision_id) for revision_id in candidate_revisions):
            raise RagError("RH_RAG_INDEX_INCOMPLETE", "selected evidence is not fully indexed")
        query_vector = list(embedder.embed(self._embed_inputs([query], query=True), batch_size=_EMBEDDING_BATCH_SIZE))[0].tolist()
        allowed = {item["evidence_id"] for item in candidates}
        vector_scores: dict[str, float] = {}
        from qdrant_client import models
        hits = []
        indexed_revisions = [value for value in candidate_revisions if not value.startswith(("pr-legacy-", "pr-unresolved-"))]
        if indexed_revisions:
            revision_filter = models.Filter(must=[models.FieldCondition(key="parse_revision_id", match=models.MatchAny(any=indexed_revisions))])
            hits.extend(qdrant.query_points(collection, query=query_vector, query_filter=revision_filter, limit=sum(1 for item in candidates if item["parse_revision_id"] in indexed_revisions)).points)
        legacy_versions = sorted({item["version_id"] for item in candidates if item["parse_revision_id"].startswith(("pr-legacy-", "pr-unresolved-"))})
        if legacy_versions:
            version_filter = models.Filter(must=[models.FieldCondition(key="version_id", match=models.MatchAny(any=legacy_versions))])
            placeholders = ",".join("?" for _ in legacy_versions)
            all_version_evidence = self._db.execute(f"SELECT COUNT(*) FROM rag_evidence WHERE version_id IN ({placeholders})", legacy_versions).fetchone()[0]
            hits.extend(qdrant.query_points(collection, query=query_vector, query_filter=version_filter, limit=all_version_evidence).points)
        vector_scores = {hit.payload["evidence_id"]: float(hit.score) for hit in hits if hit.payload and hit.payload.get("evidence_id") in allowed}
        try:
            from rank_bm25 import BM25Okapi
        except ImportError as exc:
            raise RagError("RH_RAG_DEPENDENCY", "rank-bm25 is not installed") from exc
        query_tokens = list(_tokens(query).elements())
        cache_key = tuple(item["evidence_id"] for item in candidates)
        cached = self._bm25_cache.get(cache_key)
        if cached is None:
            tokenized = [list(_tokens(item["text"]).elements()) for item in candidates]
            cached = (BM25Okapi(tokenized) if any(tokenized) else None, tokenized)
            self._bm25_cache = {cache_key: cached}
        bm25, _tokenized = cached
        raw_bm25 = bm25.get_scores(query_tokens) if bm25 is not None and query_tokens else [0.0] * len(candidates)
        lexical_scores = {item["evidence_id"]: float(value) for item, value in zip(candidates, raw_bm25)}
        scores = {item["evidence_id"]: 0.0 for item in candidates}
        for rank, evidence_id in enumerate(sorted(vector_scores, key=lambda value: (vector_scores[value], value), reverse=True), 1):
            scores[evidence_id] += 1 / (_RRF_K + rank)
        lexical_ranked = [item["evidence_id"] for item in sorted(candidates, key=lambda item: (lexical_scores[item["evidence_id"]], item["evidence_id"]), reverse=True) if lexical_scores[item["evidence_id"]] > 0]
        for rank, evidence_id in enumerate(lexical_ranked, 1):
            scores[evidence_id] += 1 / (_RRF_K + rank)
        ranked = sorted(candidates, key=lambda item: (scores[item["evidence_id"]], item["evidence_id"]), reverse=True)[:top_k]
        return {"query": query, "items": [self._item(item, scores[item["evidence_id"]]) for item in ranked], "snapshot_version_ids": sorted({item["version_id"] for item in ranked}), "snapshot_parse_revision_ids": sorted({item["parse_revision_id"] for item in ranked}), "diagnostics": {"mode": "hybrid", "embedding_model": self._stored_embedding_model(), "lexical_hits": sum(value > 0 for value in lexical_scores.values()), "vector_hits": len(vector_scores), "coverage_limits": ["BM25 plus reciprocal-rank fusion; PDF layout tables retain Docling extraction quality notes"]}}

    @staticmethod
    def _item(row: dict[str, Any], score: float | None = None) -> dict[str, Any]:
        item = {key: row[key] for key in ("evidence_id", "document_id", "version_id", "parse_revision_id", "source_sha256", "text", "title", "doi", "year", "document_type", "source_path", "section", "role", "quality") if key in row}
        item["locator"] = json.loads(row["locator"])
        if score is not None: item["score"] = score
        return item

    def get_evidence_context(self, evidence_id: str, *, before: int = 1, after: int = 1) -> dict[str, Any]:
        if not isinstance(before, int) or not isinstance(after, int) or not 0 <= before <= 3 or not 0 <= after <= 3:
            raise RagError("RH_RAG_INVALID_INPUT", "context window must be between zero and three")
        hit = self._db.execute("SELECT * FROM rag_evidence WHERE evidence_id=?", (evidence_id,)).fetchone()
        if not hit: raise RagError("RH_RAG_NOT_FOUND", "evidence was not found")
        parse_revision_id = self._revision_for_evidence(evidence_id, hit["version_id"])
        rows = self._candidates({"version_ids": [hit["version_id"]], "revision_ids": [parse_revision_id]})
        rows.sort(key=lambda row: row["ordinal"])
        position = next(index for index, row in enumerate(rows) if row["evidence_id"] == evidence_id)
        hit_row = rows[position]
        def duplicate_caption(row: dict[str, Any]) -> bool:
            return hit_row["role"] == "table" and row.get("role") != "table" and bool(hit_row.get("section")) and row["text"].strip() == hit_row["section"].strip()
        left = [row for row in reversed(rows[:position]) if not duplicate_caption(row)][:before]
        right = [row for row in rows[position + 1:] if not duplicate_caption(row)][:after]
        selected = list(reversed(left)) + [hit_row] + right
        return {"evidence_id": evidence_id, "parse_revision_id": parse_revision_id, "items": [self._item(row) for row in selected]}

    def get_document(self, document_id: str) -> dict[str, Any]:
        row = self._db.execute("SELECT * FROM rag_documents WHERE document_id=?", (document_id,)).fetchone()
        if not row: raise RagError("RH_RAG_NOT_FOUND", "document was not found")
        result = dict(row); result["errors"] = json.loads(result["errors"]); result["versions"] = [dict(version) for version in self._db.execute("SELECT * FROM rag_versions WHERE document_id=? ORDER BY created", (document_id,))]
        parse_revisions = []
        for version in result["versions"]:
            version["errors"] = json.loads(version["errors"])
            version_id = version["version_id"]
            version["current_parse_revision_id"] = self._current_parse_revision_id(version_id)
            if self._parse_revision_tables:
                revisions = [dict(item) for item in self._db.execute("SELECT * FROM rag_parse_revisions WHERE version_id=? ORDER BY created", (version_id,))]
                for item in revisions:
                    item["parser_config"] = json.loads(item["parser_config"])
                    item["errors"] = json.loads(item["errors"])
            else:
                revisions = []
            unmapped = bool(self._db.execute("SELECT 1 FROM rag_evidence WHERE version_id=? LIMIT 1", (version_id,)).fetchone()) if not self._parse_revision_tables else bool(self._db.execute("SELECT 1 FROM rag_evidence e LEFT JOIN rag_evidence_parse_revisions p ON p.evidence_id=e.evidence_id WHERE e.version_id=? AND p.evidence_id IS NULL LIMIT 1", (version_id,)).fetchone())
            if unmapped:
                revision_id = self._legacy_parse_revision_id(version_id)
                revisions = [{"parse_revision_id": revision_id, "version_id": version_id,
                              "parser_fingerprint": "legacy" if revision_id.startswith("pr-legacy-") else "unresolved_legacy",
                              "parser_config": None, "output_sha256": None,
                              "evidence_count": self._db.execute("SELECT COUNT(*) FROM rag_evidence WHERE version_id=?", (version_id,)).fetchone()[0]}]
            version["parse_revisions"] = revisions
            parse_revisions.extend(revisions)
        result["parse_revisions"] = parse_revisions
        current_version_id = result["current_version_id"]
        result["current_parse_revision_id"] = next((item["current_parse_revision_id"] for item in result["versions"] if item["version_id"] == current_version_id), None)
        return result

    def get_library_status(self) -> dict[str, Any]:
        documents = [dict(row) for row in self._db.execute("SELECT document_id,title,doi,document_type,year,current_version_id,parse_status FROM rag_documents ORDER BY title")]
        completed = sum(item["parse_status"] == "completed" for item in documents)
        try:
            indexed = sum(bool(item["current_version_id"]) and self._version_is_indexed(item["current_version_id"]) for item in documents)
        except RagError as exc:
            indexed = None
            index_status = "unavailable"
            index_error: dict[str, str] | None = exc.to_dict()
        else:
            index_status = "empty" if not documents else "ready" if indexed == completed and completed else "partial"
            index_error = None
        result = {"document_count": len(documents), "version_count": self._db.execute("SELECT COUNT(*) FROM rag_versions").fetchone()[0], "evidence_count": self._db.execute("SELECT COUNT(*) FROM rag_evidence").fetchone()[0], "indexed_document_count": indexed, "failed_document_count": sum(item["parse_status"] == "failed" for item in documents), "embedding_model": self._stored_embedding_model(), "index_status": index_status, "documents": documents}
        if index_error is not None:
            result["index_error"] = index_error
        return result


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
