"""PaperQA worker using only the frozen envelope and broker RPCs."""
from __future__ import annotations

import asyncio
import io
import os
import sys
import tempfile
from pathlib import Path
import uuid
from typing import Any

os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "true"

from .worker_runtime import RpcClient, install_io_guard, read_message
from ..research_engine_protocol import PROTOCOL, encode_message


def _result_text(reply: dict[str, Any]) -> str:
    result = reply.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("text"), str):
        raise RuntimeError("broker did not return structured text")
    return result["text"]


def _make_models(client: RpcClient, settings):
    from lmi import EmbeddingModel, LLMModel, LLMResult

    class BrokerLLM(LLMModel):
        name: str = "core-broker"

        async def _run_with_fallbacks(self, attempt, /, *args, **kwargs):
            # PaperQA/LMI normally retries model profiles; this broker must make
            # a single ledgered attempt and never silently fall back.
            return await attempt(None, *args, **kwargs)

        async def _dispatch(self, spec=None, *, messages, streaming=False, **kwargs):
            if streaming:
                raise RuntimeError("streaming is disabled for the core broker")
            reply = client.call("model_call", "model-" + uuid.uuid4().hex, "paperqa", {
                "model": settings["model"], "messages": _serialize_messages(messages),
                "max_output_tokens": settings["max_output_tokens"],
            })
            text = _result_text(reply)
            return [LLMResult(model=settings["model"], text=text)]

        async def acompletion(self, messages, *, spec=None, **kwargs):
            reply = client.call("model_call", "model-" + uuid.uuid4().hex, "paperqa", {
                "model": settings["model"], "messages": _serialize_messages(messages),
                "max_output_tokens": settings["max_output_tokens"],
            })
            text = _result_text(reply)
            return [LLMResult(model=settings["model"], text=text)]

    class BrokerEmbedding(EmbeddingModel):
        name: str = "core-embedding-broker"
        ndim: int | None = None

        async def embed_documents(self, texts):
            reply = client.call("embedding", "embedding-" + uuid.uuid4().hex, "paperqa_retrieval", {
                "model": settings["embedding_model"], "texts": list(texts),
            })
            vectors = reply.get("result")
            if not isinstance(vectors, list) or len(vectors) != len(texts):
                raise RuntimeError("broker returned invalid embedding batch")
            return vectors

    return BrokerLLM(), BrokerEmbedding()


def _serialize_messages(messages):
    """Preserve PaperQA's actual role/content messages across the core RPC."""
    serialized = []
    for message in messages:
        role = getattr(message, "role", None)
        role = getattr(role, "value", role)
        content = getattr(message, "content", None)
        if role not in {"system", "user", "assistant"} or not isinstance(content, str):
            raise RuntimeError("PaperQA supplied an unsupported model message")
        serialized.append({"role": role, "content": content})
    if not serialized:
        raise RuntimeError("PaperQA supplied no model messages")
    return serialized


def _citation_for_context(index, context, evidence_map):
    doc = getattr(getattr(context, "text", None), "doc", None)
    docname = getattr(doc, "docname", None) or getattr(getattr(context, "text", None), "name", None)
    evidence = evidence_map.get(docname) if isinstance(docname, str) else None
    if not isinstance(evidence, dict):
        return None
    quote = evidence.get("text")
    if not isinstance(quote, str) or not quote.strip():
        return None
    context_id = getattr(context, "id", None)
    if not isinstance(context_id, str) or not context_id:
        return None
    return {"citation_id": f"paperqa-{context_id}", "evidence_id": evidence["evidence_id"],
        "document_id": evidence["document_id"], "version_id": evidence["version_id"],
        "parse_revision_id": evidence.get("parse_revision_id"), "locator": evidence["locator"], "quote": quote.strip()}


def run(envelope: dict[str, Any], client: RpcClient) -> dict[str, Any]:
    # Imports happen after the import-time LiteLLM price-map network switch.
    from paperqa import Docs, Settings
    from paperqa.settings import AnswerSettings, ParsingSettings

    # PaperQA Settings create an index directory even when using in-memory Docs.
    # Keep that incidental state in the OS temp area, never in user home/workspace.
    os.environ.setdefault("PQA_HOME", tempfile.gettempdir())

    profile = envelope["profile"]
    settings_config = profile.get("paperqa", {})
    settings = {
        "model": profile.get("model"),
        "embedding_model": profile.get("embedding_model"),
        "max_output_tokens": envelope["limits"].get("max_output_tokens", 1024),
    }
    if not all(isinstance(settings[k], str) and settings[k] for k in ("model", "embedding_model")):
        raise ValueError("worker requires explicit broker model and embedding model names")
    llm, embedding = _make_models(client, settings)
    paper_settings = Settings(
        llm="core-broker", summary_llm="core-broker", embedding="core-embedding-broker",
        parsing=ParsingSettings(use_doc_details=False, multimodal=False, defer_embedding=False),
        answer=AnswerSettings(evidence_k=max(1, len(envelope["evidence"])), evidence_relevance_score_cutoff=0, evidence_retrieval=False),
    )
    docs = Docs()
    evidence_map = {}
    for index, item in enumerate(envelope["evidence"]):
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            continue
        evidence_id = item.get("evidence_id")
        if not isinstance(evidence_id, str) or not evidence_id:
            continue
        # One deterministic in-memory document per frozen evidence passage.
        docname = f"evidence-{index:04d}-{evidence_id}"
        citation = f"{item.get('document_id', '')} ({item.get('version_id', '')})"
        data = item["text"].encode("utf-8")
        if len(item["text"].strip()) < 10:
            continue
        # aadd_file keeps a Windows temporary file open while aadd rereads it;
        # stage a uniquely named text file, close it, then call the same public
        # Docs.aadd API directly for cross-platform read compatibility.
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".txt", delete=False) as stream:
            stream.write(data)
            staged = Path(stream.name)
        try:
            asyncio.get_event_loop().run_until_complete(docs.aadd(staged, citation=citation, docname=docname,
                dockey=docname, title=citation, settings=paper_settings, llm_model=llm,
                embedding_model=embedding))
        finally:
            staged.unlink(missing_ok=True)
        evidence_map[docname] = item
    if not evidence_map:
        return {"protocol": PROTOCOL, "op": "result", "identity": client.identity,
            "engine": {"name": "paperqa", "version": "2026.8.12"},
            "draft": {"sections": [], "claims": [], "citations": [],
                      "coverage_gaps": ["No eligible frozen extract evidence was supplied."]},
            "trace": {"coverage": "extracts_only", "documents": 0}}
    query = envelope["task"]["payload"].get("question") or envelope["task"]["payload"].get("research_question") or envelope.get("research_question") or "Summarize the supplied evidence."
    session = asyncio.get_event_loop().run_until_complete(docs.aquery(str(query), settings=paper_settings, llm_model=llm,
        summary_llm_model=llm, embedding_model=embedding))
    citations = []
    claim_text = getattr(session, "answer", None) or getattr(session, "raw_answer", "")
    contexts = getattr(session, "contexts", [])
    used_context_ids = getattr(session, "used_contexts", set())
    for index, context in enumerate(contexts):
        context_id = getattr(context, "id", None)
        if not isinstance(context_id, str) or context_id not in used_context_ids:
            continue
        # Cite only the source passage itself, never PaperQA's generated summary.
        citation = _citation_for_context(index, context, evidence_map)
        if citation is not None:
            citations.append(citation)
    citation_ids = [item["citation_id"] for item in citations]
    return {"protocol": PROTOCOL, "op": "result", "identity": client.identity,
        "engine": {"name": "paperqa", "version": "2026.8.12"},
        "draft": {"sections": [], "claims": ([{"text": str(claim_text), "citation_ids": citation_ids}] if claim_text else []),
                  "citations": citations, "coverage_gaps": ["Coverage is limited to supplied extracts (extracts_only)."]},
        "trace": {"coverage": "extracts_only", "documents": len(evidence_map), "contexts": len(contexts),
                  "used_context_ids": sorted(used_context_ids)}}


def main() -> int:
    loop = asyncio.new_event_loop()
    # Initialize asyncio's internal wakeup socket before the guard. It is an
    # in-process runtime mechanism, not a provider/network capability.
    if hasattr(loop, "_make_self_pipe"):
        loop._make_self_pipe()
    asyncio.set_event_loop(loop)
    install_io_guard()
    first = read_message(sys.stdin.buffer)
    if first.get("op") != "run" or not isinstance(first.get("envelope"), dict):
        return 2
    client = RpcClient(); client.identity = first["identity"]
    try:
        result = run(first["envelope"], client)
    except Exception as error:
        result = {"protocol": PROTOCOL, "op": "result", "identity": client.identity,
                  "engine": {"name": "paperqa", "version": "2026.8.12"},
                  "draft": {"sections": [], "claims": [], "citations": [], "coverage_gaps": ["PaperQA execution failed; review required."]},
                  "trace": {"coverage": "extracts_only", "status": "failed", "error_type": type(error).__name__}}
    sys.stdout.buffer.write(encode_message(result)); sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
