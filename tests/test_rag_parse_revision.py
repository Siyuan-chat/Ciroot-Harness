import hashlib
import json
import sqlite3
import sys
from collections import Counter
from types import ModuleType, SimpleNamespace

import pytest

from research_harness.rag import RagError, RagLibrary


class _Vector(list):
    def tolist(self):
        return list(self)


class _Embedder:
    def embed(self, texts, **_kwargs):
        return iter(_Vector([1.0, float(len(text))]) for text in texts)


class _Splitter:
    def __init__(self, **_kwargs):
        pass

    def split_text(self, text):
        return [text]


class _FakeIndex:
    def __init__(self):
        self.collections = {}

    def close(self):
        pass

    def collection_exists(self, name):
        return name in self.collections

    def create_collection(self, name, **_kwargs):
        self.collections[name] = {}

    def upsert(self, collection, points, wait=True):
        self.collections.setdefault(collection, {}).update({point.id: point for point in points})

    @staticmethod
    def _conditions(query_filter):
        return getattr(query_filter, "must", []) if query_filter else []

    def _matches(self, payload, query_filter):
        for condition in self._conditions(query_filter):
            key = condition.key
            match = condition.match
            if hasattr(match, "any"):
                if payload.get(key) not in match.any:
                    return False
            elif payload.get(key) != match.value:
                return False
        return True

    def count(self, collection, count_filter=None, exact=True):
        points = self.collections.get(collection, {}).values()
        return SimpleNamespace(count=sum(self._matches(point.payload, count_filter) for point in points))

    def query_points(self, collection, query, query_filter=None, limit=10):
        points = [point for point in self.collections.get(collection, {}).values() if self._matches(point.payload, query_filter)]
        hits = [SimpleNamespace(payload=point.payload, score=1.0) for point in points[:limit]]
        return SimpleNamespace(points=hits)


def _qdrant_module():
    module = ModuleType("qdrant_client")
    models = SimpleNamespace(
        PointStruct=lambda **kwargs: SimpleNamespace(**kwargs),
        VectorParams=lambda **kwargs: kwargs,
        Distance=SimpleNamespace(COSINE="cosine"),
        Filter=lambda **kwargs: SimpleNamespace(**kwargs),
        FieldCondition=lambda **kwargs: SimpleNamespace(**kwargs),
        MatchValue=lambda **kwargs: SimpleNamespace(**kwargs),
        MatchAny=lambda **kwargs: SimpleNamespace(**kwargs),
    )
    module.models = models
    module.QdrantClient = lambda **_kwargs: _FakeIndex()
    return module


def _setup(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "qdrant_client", _qdrant_module())
    bm25 = ModuleType("rank_bm25")
    bm25.BM25Okapi = lambda corpus: SimpleNamespace(
        get_scores=lambda query: [float(sum(token in document for token in query)) for document in corpus]
    )
    monkeypatch.setitem(sys.modules, "rank_bm25", bm25)
    monkeypatch.setattr("research_harness.rag._tokens", lambda text: Counter(text.lower().split()))
    monkeypatch.setattr("research_harness.rag.package_version", lambda name: "fixture-1" if name == "fastembed" else "parser-1")
    source = tmp_path / "source.txt"
    source.write_bytes(b"immutable source bytes")
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"records": [{"file": source.name, "doi": "10.1234/parse-revision", "title": "Fixture"}]}), encoding="utf-8")
    library = RagLibrary(tmp_path / "workspace")
    index = _FakeIndex()
    library._qdrant = index
    library._components = lambda **_kwargs: (_Embedder(), index, _Splitter)
    return library, index, source, catalog


def _parser(text, locator):
    def parse(_source):
        return ([{"text": text, "locator": locator, "section": None, "role": "text"}], None, "full_text", [])
    return parse


def test_reparse_adds_immutable_revision_and_searches_each_revision(tmp_path, monkeypatch):
    library, _index, source, catalog = _setup(tmp_path, monkeypatch)
    try:
        library._parse = _parser("first parse text", {"line_start": 1, "line_end": 1})
        first = library.import_library(catalog)["documents"][0]
        assert first["version_id"].startswith("ver-")
        first_revision = first["parse_revision_id"]
        first_hit = library._db.execute("SELECT evidence_id,text,locator FROM rag_evidence WHERE evidence_id=?", (library.search_evidence("first", top_k=1)["items"][0]["evidence_id"],)).fetchone()
        old_evidence_id, old_text, old_locator = first_hit["evidence_id"], first_hit["text"], json.loads(first_hit["locator"])
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()

        monkeypatch.setattr("research_harness.rag._PARSER_FINGERPRINT", "fixture-parser-2")
        library._parse = _parser("second parse text", {"line_start": 4, "line_end": 4})
        reparsed = library.reparse_document(first["document_id"], first["version_id"])
        second_revision = reparsed["parse_revision_id"]
        assert reparsed["version_id"] == first["version_id"]
        assert second_revision != first_revision
        assert reparsed["evidence_count"] == 1
        rows = library._db.execute("SELECT evidence_id,text,locator FROM rag_evidence WHERE version_id=? ORDER BY ordinal", (first["version_id"],)).fetchall()
        assert len(rows) == 2 and rows[0]["evidence_id"] == old_evidence_id
        assert (rows[0]["text"], json.loads(rows[0]["locator"])) == (old_text, old_locator)
        assert rows[1]["evidence_id"] != old_evidence_id
        assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash

        current = library.search_evidence("second", top_k=4)
        assert {item["parse_revision_id"] for item in current["items"]} == {second_revision}
        assert current["snapshot_parse_revision_ids"] == [second_revision]
        historical = library.search_evidence("first", top_k=4, filters={"revision_ids": [first_revision]})
        assert [item["evidence_id"] for item in historical["items"]] == [old_evidence_id]
        context = library.get_evidence_context(old_evidence_id, before=3, after=3)
        assert context["parse_revision_id"] == first_revision
        assert [item["parse_revision_id"] for item in context["items"]] == [first_revision]
        assert [item["text"] for item in context["items"]] == [old_text]

        saved_raw = library.root / "raw" / f"{first['version_id']}.txt"
        assert hashlib.sha256(saved_raw.read_bytes()).hexdigest() == source_hash
        library.close()
        reopened = RagLibrary(tmp_path / "workspace")
        reopened._qdrant = _index
        reopened._components = lambda **_kwargs: (_Embedder(), _index, _Splitter)
        try:
            document = reopened.get_document(first["document_id"])
            assert document["current_parse_revision_id"] == second_revision
            assert {item["parse_revision_id"] for item in document["parse_revisions"]} == {first_revision, second_revision}
            assert reopened.get_evidence_context(old_evidence_id)["items"][0]["text"] == old_text
        finally:
            reopened.close()
    finally:
        library.close()


def test_failed_reparse_keeps_current_pointer_evidence_and_raw_source(tmp_path, monkeypatch):
    library, _index, source, catalog = _setup(tmp_path, monkeypatch)
    try:
        library._parse = _parser("accepted old parse", {"line_start": 1, "line_end": 1})
        imported = library.import_library(catalog)["documents"][0]
        document_id, version_id, current_id = imported["document_id"], imported["version_id"], imported["parse_revision_id"]
        before_count = library._db.execute("SELECT COUNT(*) FROM rag_evidence").fetchone()[0]
        raw_path = library.root / "raw" / f"{version_id}.txt"
        raw_before = raw_path.read_bytes()
        monkeypatch.setattr("research_harness.rag._PARSER_FINGERPRINT", "failing-parser")

        def fail(_source):
            raise RagError("RH_RAG_PARSE_FAILED", "fixture parser failure")

        library._parse = fail
        with pytest.raises(RagError, match="fixture parser failure"):
            library.reparse_document(document_id, version_id)
        assert library._current_parse_revision_id(version_id) == current_id
        assert library._db.execute("SELECT COUNT(*) FROM rag_evidence").fetchone()[0] == before_count
        assert raw_path.read_bytes() == raw_before == source.read_bytes()
    finally:
        library.close()


def test_read_only_legacy_database_reads_stable_revision_without_migration(tmp_path, monkeypatch):
    workspace = tmp_path / "legacy"
    workspace.mkdir()
    (workspace / "qdrant").mkdir()
    connection = sqlite3.connect(workspace / "rag.sqlite")
    connection.executescript(
        """
        CREATE TABLE rag_documents(document_id TEXT PRIMARY KEY,title TEXT NOT NULL,doi TEXT,year INTEGER,document_type TEXT,source_path TEXT NOT NULL,current_version_id TEXT,parse_status TEXT NOT NULL,coverage TEXT NOT NULL,errors TEXT NOT NULL);
        CREATE TABLE rag_versions(version_id TEXT PRIMARY KEY,document_id TEXT NOT NULL,content_sha256 TEXT NOT NULL,parser TEXT NOT NULL,page_count INTEGER,coverage TEXT NOT NULL,errors TEXT NOT NULL,source_path TEXT NOT NULL,created REAL NOT NULL);
        CREATE TABLE rag_evidence(evidence_id TEXT PRIMARY KEY,document_id TEXT NOT NULL,version_id TEXT NOT NULL,ordinal INTEGER NOT NULL,text TEXT NOT NULL,locator TEXT NOT NULL,section TEXT,role TEXT NOT NULL,quality TEXT NOT NULL);
        CREATE TABLE rag_config(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        """
    )
    connection.execute("INSERT INTO rag_documents VALUES (?,?,?,?,?,?,?,?,?,?)", ("doc-old", "Old", None, 2024, "article", "old.pdf", "ver-old", "completed", "full_text", "[]"))
    connection.execute("INSERT INTO rag_versions VALUES (?,?,?,?,?,?,?,?,?)", ("ver-old", "doc-old", "source-sha", "legacy-parser", 1, "full_text", "[]", "old.pdf", 1))
    connection.execute("INSERT INTO rag_evidence VALUES (?,?,?,?,?,?,?,?,?)", ("ev-old", "doc-old", "ver-old", 1, "old evidence", '{"page":1}', None, "text", "fixture"))
    connection.commit()
    connection.close()

    first = RagLibrary(workspace, read_only=True)
    try:
        revision_id = first._revision_for_evidence("ev-old", "ver-old")
        assert revision_id.startswith("pr-legacy-")
        document = first.get_document("doc-old")
        assert document["current_parse_revision_id"] == revision_id
        assert first.get_evidence_context("ev-old")["parse_revision_id"] == revision_id
    finally:
        first.close()
    second = RagLibrary(workspace, read_only=True)
    try:
        assert second._revision_for_evidence("ev-old", "ver-old") == revision_id
        assert not second._tables_exist("rag_parse_revisions", "rag_evidence_parse_revisions", "rag_parse_state")
        with pytest.raises(RagError) as error:
            second.reparse_document("doc-old")
        assert error.value.code == "RH_RAG_READ_ONLY"
    finally:
        second.close()


def test_wrong_revision_is_empty_and_wrong_document_version_pair_is_rejected(tmp_path, monkeypatch):
    library, _index, _source, catalog = _setup(tmp_path, monkeypatch)
    try:
        library._parse = _parser("fixture text", {"line_start": 1, "line_end": 1})
        imported = library.import_library(catalog)["documents"][0]
        assert library.search_evidence("fixture", filters={"revision_ids": ["pr-missing"]})["items"] == []
        with pytest.raises(RagError) as error:
            library.reparse_document(imported["document_id"], "ver-from-another-document")
        assert error.value.code == "RH_RAG_NOT_FOUND"
        with pytest.raises(RagError) as error:
            library.reparse_version(imported["version_id"], document_id="doc-wrong")
        assert error.value.code == "RH_RAG_NOT_FOUND"
    finally:
        library.close()


def test_parser_revision_does_not_require_embedding_rebuild_but_model_change_does(tmp_path, monkeypatch):
    library, _index, _source, catalog = _setup(tmp_path, monkeypatch)
    try:
        library._parse = _parser("one", {"line_start": 1, "line_end": 1})
        imported = library.import_library(catalog)["documents"][0]
        monkeypatch.setattr("research_harness.rag._PARSER_FINGERPRINT", "changed-parser")
        library._parse = _parser("two", {"line_start": 2, "line_end": 2})
        changed = library.reparse_document(imported["document_id"])
        assert changed["parse_revision_id"] != imported["parse_revision_id"]
        library.close()
        incompatible = RagLibrary(tmp_path / "workspace", embedding_model="another-embedding-model")
        try:
            with pytest.raises(RagError) as error:
                incompatible.reparse_document(imported["document_id"])
            assert error.value.code == "RH_RAG_CONFIG_MISMATCH"
        finally:
            incompatible.close()
    finally:
        library.close()


def test_reparsing_historical_source_version_preserves_current_document_metadata(tmp_path, monkeypatch):
    library, _index, source, catalog = _setup(tmp_path, monkeypatch)
    try:
        library._parse = _parser("historical source parse", {"line_start": 1, "line_end": 1})
        old = library.import_library(catalog)["documents"][0]
        source.write_bytes(b"newer immutable source bytes")
        library._parse = _parser("current source parse", {"line_start": 2, "line_end": 2})
        current = library.import_library(catalog)["documents"][0]
        assert old["version_id"] != current["version_id"]
        before = library.get_document(old["document_id"])
        current_metadata = {key: before[key] for key in ("current_version_id", "source_path", "coverage", "parse_status")}
        monkeypatch.setattr("research_harness.rag._PARSER_FINGERPRINT", "historical-reparse-parser")
        library._parse = _parser("historical source reparsed", {"line_start": 9, "line_end": 9})

        reparsed = library.reparse_document(old["document_id"], old["version_id"])
        after = library.get_document(old["document_id"])
        assert reparsed["version_id"] == old["version_id"]
        assert {key: after[key] for key in current_metadata} == current_metadata
        default = library.search_evidence("current", top_k=5)
        assert {item["version_id"] for item in default["items"]} == {current["version_id"]}
        assert default["snapshot_version_ids"] == [current["version_id"]]
    finally:
        library.close()
