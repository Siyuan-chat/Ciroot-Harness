"""Deterministic synthetic replay driver for one or more pending host tasks.

This is a test/replay utility. It performs no network or model calls and makes
no claim about scientific quality. Input is the exact JSON returned by
``get_pending_tasks`` (one task or a list); output is valid role-result JSON.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
from typing import Any

LANGS = {"zh": "合成离线证据支持该段落。", "en": "Synthetic offline evidence supports this section.", "ja": "合成オフライン証拠がこの節を支持します。"}

def result_for(task: dict[str, Any]) -> dict[str, Any]:
    role, p = task["role"], task.get("payload", {})
    if role == "planning":
        return {"search_plan": {"queries": [
            {"query_id": "replay-paper", "source": "synthetic-paper", "query": "synthetic membrane", "input_refs": [], "parent_query_id": None},
            {"query_id": "replay-patent", "source": "synthetic-patent", "query": "synthetic membrane", "input_refs": [], "parent_query_id": None}]}}
    if role in {"paper_search", "patent_search"}:
        return {"candidates": [{"document_id": x["document_id"], "relevance": "relevant", "reason": "Synthetic replay candidate."} for x in p.get("candidates", [])]}
    if role == "evidence_analysis":
        return {"findings": [{"finding_id": "replay-finding-1", "finding": "The source contains a synthetic membrane statement.", "evidence_ids": [p["evidence"][0]["evidence_id"]], "value": None, "unit": None, "conditions": None}] if p.get("evidence") else []}
    if role == "business_judgment":
        return {"judgments": [{"document_id": x["document_id"], "relevance": "relevant", "human_review_required": False, "reason": "Synthetic replay judgment."} for x in p.get("documents", [])]}
    if role == "synthesis":
        e = (p.get("evidence") or [{}])[0]
        return {"claims": [{"claim_id": "replay-claim-1", "claim": "The synthetic source describes a membrane route.", "finding_refs": [0], "evidence_refs": [e["evidence_id"]], "quote": e.get("text", "Synthetic replay evidence."), "document_id": e.get("document_id", "synthetic-unknown"), "version_id": e.get("version_id", e.get("version", "v1"))}]}
    if role == "writing":
        targets = p.get("report_targets") or ["technical_report", "literature_review"]
        return {"sections": [{"deliverable_type": t, "language": lang, "section_id": f"replay-{t}-{lang}", "title": "Synthetic replay", "body": LANGS[lang], "claim_ids": ["replay-claim-1"]} for t in targets for lang in ("zh", "en", "ja")]}
    if role == "verification":
        return {"verification": {"status": "supported", "conclusion": "Synthetic replay claims are structurally supported by the supplied fixture.", "supported_claim_refs": [0]}}
    raise ValueError(f"unsupported role: {role}")

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Deterministic synthetic investigation replay; no network/model calls")
    ap.add_argument("--pending", required=True, help="pending task JSON file")
    ap.add_argument("--output", required=True, help="result JSON file")
    args = ap.parse_args(argv)
    raw = json.loads(Path(args.pending).read_text(encoding="utf-8"))
    tasks = raw if isinstance(raw, list) else [raw]
    results = [{"task_id": t.get("task_id"), "task_version": t.get("task_version"), "role": t.get("role"), "result": result_for(t), "synthetic": True, "driver": "deterministic-replay"} for t in tasks]
    out = results if isinstance(raw, list) else results[0]
    Path(args.output).write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(Path(args.output)), "tasks": len(results), "synthetic": True, "network": False, "model_api": False}, ensure_ascii=False))
    return 0
if __name__ == "__main__": raise SystemExit(main())
