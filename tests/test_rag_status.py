from importlib.metadata import PackageNotFoundError
import sys

import pytest

from research_harness.rag import RagError, RagLibrary


def _store_completed_document(library: RagLibrary) -> None:
    library._db.execute("INSERT INTO rag_documents VALUES (?,?,?,?,?,?,?,?,?,?)", ("doc-1", "Fixture", None, 2024, "article", "fixture.txt", "ver-1", "completed", "full_text", "[]"))
    library._db.execute("INSERT INTO rag_versions VALUES (?,?,?,?,?,?,?,?,?)", ("ver-1", "doc-1", "sha", "fixture", 1, "full_text", "[]", "fixture.txt", 1))
    library._db.execute("INSERT INTO rag_evidence VALUES (?,?,?,?,?,?,?,?,?)", ("ev-1", "doc-1", "ver-1", 1, "fixture evidence", '{"line_start": 1, "line_end": 1}', None, "text", "fixture"))
    library._db.commit()


def test_status_keeps_empty_and_verified_index_counts_distinct(tmp_path, monkeypatch):
    with RagLibrary(tmp_path / "empty") as empty:
        status = empty.get_library_status()
        assert status["indexed_document_count"] == 0
        assert status["index_status"] == "empty"

    with RagLibrary(tmp_path / "indexed") as library:
        _store_completed_document(library)
        monkeypatch.setattr(library, "_version_is_indexed", lambda _version_id: True)
        status = library.get_library_status()
        assert status["indexed_document_count"] == 1
        assert status["index_status"] == "ready"

        monkeypatch.setattr(library, "_version_is_indexed", lambda _version_id: False)
        status = library.get_library_status()
        assert status["indexed_document_count"] == 0
        assert status["index_status"] == "partial"


@pytest.mark.parametrize("error", [RagError("RH_RAG_DEPENDENCY", "RAG dependencies are not installed"), RagError("RH_RAG_INDEX_UNAVAILABLE", "could not inspect the vector index")])
def test_status_reports_an_unavailable_index_as_unknown(tmp_path, monkeypatch, error):
    with RagLibrary(tmp_path / "library") as library:
        _store_completed_document(library)
        monkeypatch.setattr(library, "_version_is_indexed", lambda _version_id: (_ for _ in ()).throw(error))
        status = library.get_library_status()
        assert status["indexed_document_count"] is None
        assert status["index_status"] == "unavailable"
        assert status["index_error"] == error.to_dict()


def test_status_keeps_qdrant_dependency_and_index_failures_explicit(tmp_path, monkeypatch):
    with RagLibrary(tmp_path / "library") as library:
        _store_completed_document(library)
        monkeypatch.setitem(sys.modules, "qdrant_client", None)
        status = library.get_library_status()
        assert status["indexed_document_count"] is None
        assert status["index_status"] == "unavailable"
        assert status["index_error"]["code"] == "RH_RAG_DEPENDENCY"

    with RagLibrary(tmp_path / "busy") as library:
        _store_completed_document(library)
        library._qdrant = type("BusyIndex", (), {"collection_exists": lambda self, _collection: (_ for _ in ()).throw(RuntimeError("locked")), "close": lambda self: None})()
        status = library.get_library_status()
        assert status["indexed_document_count"] is None
        assert status["index_error"]["code"] == "RH_RAG_BUSY"

    with RagLibrary(tmp_path / "corrupt") as library:
        _store_completed_document(library)
        library._qdrant = type("CorruptIndex", (), {"collection_exists": lambda self, _collection: (_ for _ in ()).throw(ValueError("corrupt")), "close": lambda self: None})()
        status = library.get_library_status()
        assert status["indexed_document_count"] is None
        assert status["index_error"]["code"] == "RH_RAG_INDEX_UNAVAILABLE"


def test_search_maps_missing_fingerprint_metadata_to_rag_dependency(tmp_path, monkeypatch):
    with RagLibrary(tmp_path / "library") as library:
        _store_completed_document(library)
        monkeypatch.setattr("research_harness.rag.package_version", lambda name: (_ for _ in ()).throw(PackageNotFoundError(name)))
        with pytest.raises(RagError, match="RAG dependencies are not installed") as raised:
            library.search_evidence("fixture")
        assert raised.value.code == "RH_RAG_DEPENDENCY"
