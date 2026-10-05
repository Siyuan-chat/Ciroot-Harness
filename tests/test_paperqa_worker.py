import os
import re
from pathlib import Path

import pytest

from research_harness.research_engine_protocol import PROTOCOL
from research_harness.research_engines import resolve_engine_citations, run_engine
from research_harness.engines.paperqa_worker import _citation_for_context
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
PAPERQA_PYTHON = ROOT / ".local" / "integration-20261005" / "paperqa-runtime" / "Scripts" / "python.exe"


def test_unknown_paperqa_docname_is_skipped_without_evidence_lookup_error():
    context = SimpleNamespace(id="pqac-unknown", text=SimpleNamespace(doc=SimpleNamespace(docname="missing-doc"), name="missing-doc chunk 1"))
    assert _citation_for_context(0, context, {}) is None


@pytest.mark.skipif(not PAPERQA_PYTHON.is_file(), reason="frozen PaperQA runtime is not installed")
def test_official_paperqa_docs_pipeline_uses_only_broker_rpc_and_frozen_text():
    source = ROOT / "src"
    launcher = f"import sys;sys.path.insert(0,{str(source)!r});from research_harness.engines.paperqa_worker import main;raise SystemExit(main())"
    evidence = {"evidence_id": "ev-1", "document_id": "doc-1", "version_id": "v1", "locator": "p.1",
                "parse_revision_id": "parse-1", "text": "The catalyst reached 12 MPa under the tested conditions. This is a frozen extract passage."}
    envelope = {"run_id": "run-1", "task": {"task_id": "task-1", "task_version": 1,
        "role": "evidence_analysis", "task_type": "extract", "payload": {"question": "What pressure was reached?", "evidence": [evidence]}, "output_schema": {}},
        "evidence": [evidence], "profile": {"enabled": True, "runtime_python": str(PAPERQA_PYTHON), "engine": "paperqa", "version": "2026.8.12", "model": "offline-chat", "embedding_model": "offline-embedding"},
        "limits": {"max_output_tokens": 96, "max_rpc_requests": 8}}
    rpc_ops = []

    def broker(message):
        rpc_ops.append(message["op"])
        if message["op"] == "embedding":
            return {"outcome": "accepted", "result": [[0.01] * 384 for _ in message["request"].get("texts", [])], "core_call_id": "offline", "usage": {"kind": "embedding"}}
        if message["op"] == "model_call":
            prompt = "\n".join(item["content"] for item in message["request"].get("messages", []))
            context_ids = re.findall(r"pqac-[A-Za-z0-9_-]+", prompt)
            if "JSON" in prompt or "json" in prompt.lower():
                text = '{"summary":"The catalyst reached 12 MPa under the tested conditions.","score":8}'
            else:
                text = "The catalyst reached 12 MPa under the tested conditions." + (f" ({context_ids[0]})" if context_ids else "")
            return {"outcome": "accepted", "result": {"text": text}, "core_call_id": "offline", "usage": {}}
        return {"outcome": "accepted", "result": [], "core_call_id": None, "usage": {}}

    result = run_engine([str(PAPERQA_PYTHON), "-c", launcher], envelope, broker, 60)
    assert result["status"] == "draft"
    assert result["engine"] == {"name": "paperqa", "version": "2026.8.12"}
    assert result["trace"]["coverage"] == "extracts_only"
    assert result["trace"].get("status") != "failed", result["trace"].get("frames")
    assert "embedding" in rpc_ops and "model_call" in rpc_ops
    resolved = resolve_engine_citations(envelope, result)
    assert result["draft"]["claims"] and result["draft"]["claims"][0]["citation_ids"]
    assert {item["citation_id"].removeprefix("paperqa-") for item in result["draft"]["citations"]} == set(result["trace"]["used_context_ids"])
    assert resolved["draft"]["citations"]
    assert isinstance(resolved["issues"], list)
    assert result["protocol"] == PROTOCOL
