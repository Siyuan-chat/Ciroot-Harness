from pathlib import Path

from fastapi.testclient import TestClient

from research_harness.gui.app import create_app


def _tiny_pdf(text="Local PDF Evidence"):
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        f"<< /Length 60 >>\nstream\nBT /F1 18 Tf 72 720 Td ({text}) Tj ET\nendstream".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    result = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for n, obj in enumerate(objects, 1):
        offsets.append(len(result))
        result.extend(f"{n} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(result)
    result.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        result.extend(f"{offset:010d} 00000 n \n".encode())
    result.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(result)


def test_clean_runtime_library_create_import_search_and_restart(tmp_path):
    root = tmp_path / "portable-workspace"
    assert not (root / "library-workspace.txt").exists()
    assert not (root / "rag-model-cache.txt").exists()
    app = create_app(root, token="test")
    base = {"x-session-token": "test"}
    with TestClient(app, base_url="http://127.0.0.1") as client:
        legacy_default_empty = client.get("/api/v1/library", headers=base).json()
        assert legacy_default_empty["index_status"] == "not_indexed"
        assert legacy_default_empty["document_count"] is None
        created = client.post("/api/v1/libraries", json={"name": "Offline collection"}, headers={**base, "idempotency-key": "lib-create"})
        assert created.status_code == 200, created.text
        library_id = created.json()["library_id"]
        scope = {**base, "x-library-id": library_id}
        new_empty = client.get("/api/v1/library", headers=scope).json()
        assert new_empty["index_status"] == "not_indexed" and new_empty["document_count"] == 0
        txt = client.put("/api/v1/library/import?filename=notes.txt", content="Local TXT Evidence phrase".encode(), headers={**scope, "content-type": "application/octet-stream"})
        assert txt.status_code == 200, txt.text
        pdf = client.put("/api/v1/library/import?filename=paper.pdf", content=_tiny_pdf(), headers={**scope, "content-type": "application/octet-stream"})
        assert pdf.status_code == 200, pdf.text
        traversal = client.put("/api/v1/library/import?filename=../../notes.txt", content=b"Local TXT Evidence phrase", headers={**scope, "content-type": "application/octet-stream"})
        assert traversal.status_code == 200 and traversal.json()["duplicate"] is True
        docs = client.get("/api/v1/library", headers=scope).json()
        assert docs["index_mode"] == "basic" and len(docs["items"]) == 2
        assert all(item["versions"][0]["source_path"] for item in docs["items"])
        from research_harness.gui.local_library import list_documents, search
        selected_id = docs["items"][0]["document_id"]
        assert list_documents(root / "gui-libraries" / library_id, document_ids={selected_id})["document_count"] == 1
        assert not search(root / "gui-libraries" / library_id, "PDF Evidence", document_ids=set())["items"]
        search = client.get("/api/v1/library/search", params={"q": "Local TXT Evidence phrase", "top_k": 8}, headers=scope).json()
        assert search["diagnostics"]["mode"] == "basic" and search["items"]
        target = docs["items"][0]
        detail = client.get(f"/api/v1/library/documents/{target['document_id']}", headers=scope).json()["document"]
        assert detail["versions"]
        import json
        examples = Path(__file__).parents[1] / "src/research_harness/examples/investigation"
        body = {name: json.loads((examples / f"synthetic-{name}.json").read_text(encoding="utf-8")) for name in ("spec", "runtime", "scenario")}
        body["spec"]["research_question"] = "Local TXT Evidence phrase"
        body["spec"]["references"] = [{"document_id": target["document_id"], "visibility": "public"}]
        body["reference_scope"] = {"library_id": library_id, "collection_id": "all"}
        run = client.post("/api/v1/runs", json=body, headers={**scope, "idempotency-key": "offline-basic-reference"})
        assert run.status_code == 200, run.text
        snapshot = client.get(f"/api/v1/runs/{run.json()['run_id']}/reference-snapshot", headers=scope).json()["reference_snapshot"]
        assert snapshot["index_snapshot"]["retrieval_mode"] == "basic"
        assert snapshot["reference_evidence"]
        assert client.put("/api/v1/library/import?filename=notes.txt", content=b"Local TXT Evidence phrase", headers={**scope, "content-type": "application/octet-stream"}).json()["duplicate"] is True
        assert client.put("/api/v1/library/import?filename=bad.docx", content=b"x", headers={**scope, "content-type": "application/octet-stream"}).status_code == 400
        assert client.put("/api/v1/library/import?filename=bad.txt", content=b"\xff", headers={**scope, "content-type": "application/octet-stream"}).status_code == 400
        assert client.put("/api/v1/library/import?filename=too.txt", content=b"x" * (20 * 1024 * 1024 + 1), headers={**scope, "content-type": "application/octet-stream"}).status_code == 413

    restarted = create_app(root, token="test-2")
    with TestClient(restarted, base_url="http://127.0.0.1") as client:
        scope = {"x-session-token": "test-2", "x-library-id": library_id}
        persisted = client.get("/api/v1/library", headers=scope).json()
        assert len(persisted["items"]) == 2
        assert client.get("/api/v1/library/search", params={"q": "PDF Evidence"}, headers=scope).json()["items"]
