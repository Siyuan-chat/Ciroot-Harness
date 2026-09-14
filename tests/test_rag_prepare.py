import json

from research_harness.rag import RagLibrary


def test_prepare_caches_parse_without_building_an_index(tmp_path, monkeypatch):
    # Offline fixture: fingerprint metadata is explicit; this does not prove a real RAG environment.
    monkeypatch.setattr("research_harness.rag.package_version", lambda _name: "fixture-0")
    source = tmp_path / "paper.txt"
    source.write_text("synthetic evidence", encoding="utf-8")
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"records": [{"file": "paper.txt", "doi": "10.1/example"}]}), encoding="utf-8")
    workspace = tmp_path / "workspace"
    calls = {"parse": 0, "index": 0}

    with RagLibrary(workspace) as library:
        def fake_parse(_path):
            calls["parse"] += 1
            return ([{"text": "synthetic evidence", "locator": {"line_start": 1, "line_end": 1}, "section": None, "role": "text"}], None, "full_text", [])

        library._parse = fake_parse
        first = library.prepare_library(catalog)
        assert first["prepared"] == 1 and first["reused"] == 0
        assert calls["parse"] == 1
        assert library._db.execute("SELECT COUNT(*) FROM rag_evidence").fetchone()[0] == 0
        assert not (workspace / "qdrant").exists()

        again = library.prepare_library(catalog)
        assert again["prepared"] == 0 and again["reused"] == 1
        assert calls["parse"] == 1

        monkeypatch.setattr("research_harness.rag._PARSER_FINGERPRINT", "test-parser-change")
        changed = library.prepare_library(catalog)
        assert changed["prepared"] == 1 and calls["parse"] == 2

        library._components = lambda: (object(), object(), type("Splitter", (), {"__init__": lambda self, **_kwargs: None, "split_text": lambda self, text: [text]}))
        library._index = lambda evidence, _qdrant, _embedder: calls.__setitem__("index", calls["index"] + len(evidence))
        imported = library.import_library(catalog)
        assert imported["imported"] == 1
        assert calls["parse"] == 2
        assert calls["index"] == 1


def test_prepare_discards_corrupt_cache_and_reparses(tmp_path):
    source = tmp_path / "paper.txt"
    source.write_text("synthetic evidence", encoding="utf-8")
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"records": [{"file": "paper.txt"}]}), encoding="utf-8")
    calls = {"parse": 0}

    with RagLibrary(tmp_path / "workspace") as library:
        def fake_parse(_path):
            calls["parse"] += 1
            return ([{"text": "synthetic evidence", "locator": {"line_start": 1, "line_end": 1}, "section": None, "role": "text"}], None, "full_text", [])

        library._parse = fake_parse
        library.prepare_library(catalog)
        next((library.root / "parse-cache").glob("*.json")).write_text("{broken", encoding="utf-8")
        result = library.prepare_library(catalog)
        assert calls["parse"] == 2
        assert "invalid parse cache was discarded" in result["documents"][0]["errors"]
