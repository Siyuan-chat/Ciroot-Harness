"""Deterministic, one-question-at-a-time intake used before an optional LLM adapter."""
from __future__ import annotations
import json, re
from pathlib import Path

QUESTIONS={
 "zh":"请说明要调查的具体对象；若尚未确定，可回复“未确定”。",
 "en":"What specific subject should be investigated? Reply 'undecided' if it is not set.",
 "ja":"調査対象を具体的に指定してください。未定の場合は「未定」と答えてください。"}

def _draft(topic: str, lang: str) -> dict:
    return {"schema_version":"1.0","project_id":"research-project","revision":1,"status":"draft","topic":topic,"objectives":["Collect evidence-backed papers and patents"],"languages":{"conversation":lang,"search":["zh","en","ja"],"reports":["zh","en","ja"],"timezone":"UTC"},"scope":{"document_types":["paper","patent"],"sources":["openalex","epo"],"publication_date_from":None,"patent_jurisdictions":[]},"reference_library":{"collection_ids":["baseline"],"document_ids":[],"freeze_each_run":True,"promotion":"explicit_only"},"criteria":[],"inclusion_rules":[],"exclusion_rules":[],"execution":{"trigger":"manual","missing_evidence":"watch_and_queue","budget":{"max_candidates":50,"max_queries_per_source":3,"max_search_rounds":2,"max_model_calls":120,"max_concurrency":3,"max_active_minutes":30,"max_file_mib":30,"max_total_download_mib":300,"max_estimated_cost_usd":None,"on_limit":"save_partial_report"}},"data_policy":{"original_storage":"local","embedding":"local","cloud_excerpt_allowed":True,"llm_context":"relevant_excerpts"},"human_review":{"enabled":True,"scope":"individual_by_default","global_rule_updates":"explicit_only"},"report":{"formats":["html","markdown","json"],"review_export":"csv","include_technical_map":True,"include_cumulative_review":True},"unresolved_questions":[QUESTIONS[lang]]}

def respond(workspace: str | Path, message: str, lang: str) -> dict:
    root=Path(workspace)/"sessions"; root.mkdir(parents=True,exist_ok=True); path=root/"intake.json"
    state=json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"turns":[],"spec":None}
    state["turns"].append({"role":"user","content":message})
    if state["spec"] is None:
        state["spec"]=_draft(message.strip(),lang); reply=QUESTIONS[lang]
    else:
        spec=state["spec"]
        if spec["unresolved_questions"]:
            if message.strip().lower() not in {"undecided","未定","未确定"}:
                spec["topic"]=message.strip(); spec["unresolved_questions"]=[]; spec["status"]="ready"; reply={"zh":"已生成 ready 草案；明确说“开始调查”才会运行。","en":"A ready draft was created; say 'start investigation' to run.","ja":"ready 草案を作成しました。明示的に開始した場合のみ実行します。"}[lang]
            else: reply=QUESTIONS[lang]
        else: reply={"zh":"当前规格已就绪；可修改 JSON 或明确开始调查。","en":"The current specification is ready; revise JSON or explicitly start.","ja":"現在の仕様は ready です。JSON を修正するか、明示的に開始してください。"}[lang]
    state["turns"].append({"role":"assistant","content":reply}); path.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding="utf-8")
    return {"intent":"clarify","reply":reply,"spec":state["spec"],"session_path":str(path)}
