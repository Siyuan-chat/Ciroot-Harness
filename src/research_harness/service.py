from __future__ import annotations
import csv, html, json, os, shutil, sys, time
from pathlib import Path
from .contracts import fingerprint, load_json, validate_runtime, validate_spec
from .errors import PreflightError
from .storage import Store
from .ingestion import parse
from .retrieval import search

MESSAGES={"zh":{"no_model":"未选择模型","need_ready":"ResearchSpec 必须为 ready 且不存在未解决问题"},"en":{"no_model":"no model selected","need_ready":"ResearchSpec must be ready with no unresolved questions"},"ja":{"no_model":"モデルが選択されていません","need_ready":"ResearchSpec は ready で未解決事項がない必要があります"}}

class Harness:
    def __init__(self, workspace): self.store=Store(workspace); self.workspace=Path(workspace)
    def validate(self, spec_path):
        spec=load_json(spec_path); validate_spec(spec); return spec
    @staticmethod
    def doctor_runtime(runtime, lang="en"):
        problems=[]; llm=runtime["llm"]; retrieval=runtime["retrieval"]
        if not llm.get("model"): problems.append(MESSAGES[lang]["no_model"])
        if not llm.get("local") and (not llm.get("api_key_env") or not os.getenv(llm["api_key_env"])): problems.append("missing LLM credential: " + str(llm.get("api_key_env")))
        if retrieval["mode"]=="hybrid" and not retrieval["embedding"].get("model"): problems.append("missing FastEmbed model selection")
        optional={x: bool(__import__("importlib").util.find_spec(x)) for x in ("fastembed","qdrant_client","llama_index")}
        if retrieval["mode"]=="hybrid":
            missing=[x for x in optional if not optional[x]]
            if missing: problems.append("missing hybrid retrieval components: "+", ".join(missing))
        return problems
    @staticmethod
    def doctor(runtime_path, lang="en"):
        runtime=load_json(runtime_path); validate_runtime(runtime); problems=[]; llm=runtime["llm"]; retrieval=runtime["retrieval"]
        if not llm.get("model"): problems.append(MESSAGES[lang]["no_model"])
        if not llm.get("local") and (not llm.get("api_key_env") or not os.getenv(llm["api_key_env"])): problems.append("missing LLM credential: " + str(llm.get("api_key_env")))
        if retrieval["mode"]=="hybrid" and not retrieval["embedding"].get("model"): problems.append("missing FastEmbed model selection")
        for name,cfg in runtime["sources"].items():
            if cfg.get("enabled"):
                for key,val in cfg.items():
                    if key.endswith("_env") and not os.getenv(val): problems.append(f"missing {name} credential: {val}")
        optional={x: bool(__import__("importlib").util.find_spec(x)) for x in ("langgraph","docling","fastembed","qdrant_client","llama_index")}
        if retrieval["mode"]=="hybrid":
            missing=[name for name in ("fastembed","qdrant_client","llama_index") if not optional[name]]
            if missing: problems.append("missing hybrid retrieval components: "+", ".join(missing))
        return {"ok":not problems,"problems":problems,"optional_components":optional,"network_called":False}
    def import_document(self,path,collection,kind):
        ident=self.store.import_file(path,collection,kind)
        raw=Path(path).read_bytes(); text,evidence,errors=parse(path,raw)
        self.store.db.execute("UPDATE documents SET content=?,parse_status=?,parse_errors=? WHERE id=?",(text,"parsed" if not errors else "failed",json.dumps(errors,ensure_ascii=False),ident)); self.store.db.commit()
        self.store.add_evidence(ident,evidence)
        return {"document_id":ident,"evidence_count":len(evidence),"parse_errors":errors}
    def save_spec(self, spec_path):
        spec=self.validate(spec_path); return self.store.save_spec(spec,fingerprint(spec))
    def _preflight(self,spec,runtime):
        if spec["status"]!="ready" or spec["unresolved_questions"]: raise PreflightError(MESSAGES[spec["languages"]["conversation"]]["need_ready"])
        validate_runtime(runtime)
        doctor=self.doctor_runtime(runtime, spec["languages"]["conversation"])
        if doctor: raise PreflightError("; ".join(doctor))
        if not runtime["llm"].get("model"): raise PreflightError("LLM model is required")
        if not runtime["llm"].get("local") and not os.getenv(runtime["llm"]["api_key_env"]): raise PreflightError("LLM credential is required")
        if runtime["retrieval"]["mode"]=="hybrid" and not runtime["retrieval"]["embedding"].get("model"): raise PreflightError("FastEmbed model is required for hybrid retrieval")
        for name,cfg in runtime["sources"].items():
            if cfg.get("enabled"):
                missing=[v for k,v in cfg.items() if k.endswith("_env") and not os.getenv(v)]
                if missing: raise PreflightError(f"{name} credential is required")
    def run(self,spec_path,runtime_path):
        spec=self.save_spec(spec_path); runtime=load_json(runtime_path); self._preflight(spec,runtime)
        all_docs=self.store.documents(); ref=spec["reference_library"]
        allowed_collections=set(ref["collection_ids"]); requested=set(ref["document_ids"])
        by_id={d["id"]:d for d in all_docs}; missing=requested-set(by_id)
        if missing: raise PreflightError("reference document not found: "+", ".join(sorted(missing)))
        baseline=[d["id"] for d in all_docs if d["id"] in requested or (d["collection_name"] in allowed_collections and d["collection_name"]=="baseline")]
        manifest={"execution_mode":"local_fixture" if runtime["retrieval"]["mode"]=="lexical_test_only" else "local", "synthetic":runtime["retrieval"]["mode"]=="lexical_test_only", "spec_fingerprint":fingerprint(spec),"baseline_document_ids":baseline,"sources":{},"budgets":spec["execution"]["budget"],"model":{"provider":runtime["llm"]["provider"],"model":runtime["llm"]["model"]},"notes":["No external source request is made by the local core. Enable adapters only with configured credentials."]}
        run_id=self.store.create_run(spec,manifest["execution_mode"],manifest)
        enabled=[name for name,cfg in runtime["sources"].items() if cfg.get("enabled")]
        for source in enabled: manifest["sources"][source]={"status":"pending","reason":"online adapter requires explicit integration execution"}
        status="partial" if enabled else "completed"
        frozen=[d for d in all_docs if d["id"] in baseline]
        retrieval=search(frozen,spec["topic"])
        data={"run_id":run_id,"status":status,"execution_mode":manifest["execution_mode"],"synthetic":manifest["synthetic"],"baseline_document_ids":baseline,"sources":manifest["sources"],"documents":[{"id":d["id"],"filename":d["filename"],"kind":d["kind"],"collection":d["collection_name"]} for d in frozen],"issues":self.store.issues(),"technical_map":[{"id":r["document_id"],"route":"unclassified","reported_metrics":"unknown"} for r in retrieval],"retrieval":{"mode":"lexical_test_only" if runtime["retrieval"]["mode"]=="lexical_test_only" else "lexical","results":retrieval},"limits":manifest["notes"]}
        self.store.finish_run(run_id,status,manifest,data); self.report(run_id, spec["languages"]["reports"]); return run_id
    def report(self,run_id,languages):
        run=self.store.run(run_id)
        if not run: raise KeyError(run_id)
        manifest=json.loads(run["manifest"]); data=json.loads(run["report_data"] or "null")
        if data is None: raise PreflightError("run has no frozen report data")
        out=self.workspace/"reports"/run_id; out.mkdir(parents=True,exist_ok=True); (out/"report.json").write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
        for lang in languages:
            def cell(value): return html.escape(str(value),quote=False).replace("|","\\|").replace("\n","<br>")
            labels_map={"zh":{"completed":"完成","partial":"部分完成","failed":"失败","include":"纳入","exclude":"排除","watch":"待判断","valid":"有效","invalid":"无效","not_comparable":"不可比较","insufficient_evidence":"证据不足","open":"待处理","resolved":"已处理"},"ja":{"completed":"完了","partial":"一部完了","failed":"失敗","include":"採用","exclude":"除外","watch":"要確認","valid":"有効","invalid":"無効","not_comparable":"比較不可","insufficient_evidence":"根拠不足","open":"未対応","resolved":"対応済み"},"en":{}}
            def status_label(value): return labels_map[lang].get(str(value),str(value))+" ("+str(value)+")"
            title={"zh":"研究报告","en":"Research report","ja":"調査レポート"}[lang]
            labels={"zh":("候选与判定","人工清单","合成夹具","运行","状态","来源","限制","错误","候选","判定","比较","核查","理由","原始证据"),"en":("Candidates and findings","Review issues","Synthetic fixture","Run","Status","Sources","Limits","Error","Candidate","Disposition","Comparison","Verification","Rationale","Evidence (original)"),"ja":("候補と判定","確認リスト","合成フィクスチャ","実行","状態","情報源","制限","エラー","候補","判定","比較","検証","理由","原文エビデンス")}[lang]
            reason_label={"zh":"理由（模型原文）","en":"Rationale (model original)","ja":"理由（モデル原文）"}[lang]; issue_labels={"zh":["状态","机器建议","人工决定","备注"],"en":["Status","Machine","Decision","Note"],"ja":["状態","機械判定","人の判断","備考"]}[lang]
            rows=[]
            for f in data.get("findings",[]): rows.append("| "+cell(f.get("candidate_id",""))+" | "+cell(status_label(f.get("disposition","")))+" | "+cell(status_label(f.get("comparison_result","")))+" | "+cell(status_label(f.get("verification",{}).get("status","")))+" | "+cell(f.get("rationale",""))+" | ")
            md=f"# {title}\n\n> {labels[2]}: `{data.get('synthetic',False)}`\n\n{labels[3]}: `{run_id}`  {labels[4]}: `{status_label(data.get('status'))}`\n\n{labels[5]}: `{json.dumps(data.get('sources',{}),ensure_ascii=False)}`\n\n{labels[6]}: `{json.dumps(data.get('limits',[]),ensure_ascii=False)}`\n\n{labels[7]}: `{json.dumps(data.get('error'),ensure_ascii=False)}`\n\n## {labels[0]}\n\n| ID | {labels[9]} | {labels[10]} | {labels[11]} | {reason_label} |\n|---|---|---|---|---|\n"+"\n".join(rows)+f"\n\n## {labels[13]}\n\n"+json.dumps({"candidates":data.get("candidates",[]),"reference_evidence":data.get("reference_evidence",[])},ensure_ascii=False,indent=2).replace("<","&lt;")+f"\n\n## {labels[1]}\n\n"+json.dumps(data.get("issues",[]),ensure_ascii=False,indent=2).replace("<","&lt;")+"\n"
            html_rows="".join(f"<tr><td>{html.escape(str(f.get('candidate_id','')))}</td><td>{html.escape(status_label(f.get('disposition','')))}</td><td>{html.escape(status_label(f.get('comparison_result','')))}</td><td>{html.escape(status_label(f.get('verification',{}).get('status','')))}</td><td>{html.escape(str(f.get('rationale','')))}</td></tr>" for f in data.get("findings",[]))
            evidence="".join(f"<blockquote><b>{html.escape(str(e.get('id','')))}</b> {html.escape(str(e.get('quote','')))} ({html.escape(str(e.get('locator','')))})</blockquote>" for c in data.get("candidates",[]) for e in c.get("evidence",[]))+"".join(f"<blockquote><b>{html.escape(str(e.get('id','')))}</b> {html.escape(str(e.get('quote','')))} ({html.escape(str(e.get('locator','')))})</blockquote>" for e in data.get("reference_evidence",[]))
            issue_rows="".join(f"<tr><td>{html.escape(str(i.get('id','')))}</td><td>{html.escape(status_label(i.get('status','')))}</td><td>{html.escape(status_label(i.get('machine_disposition','')))}</td><td>{html.escape(status_label(i.get('human_decision','')))}</td><td>{html.escape(str(i.get('note','')))}</td></tr>" for i in data.get("issues",[]))
            body=f"<style>body{{margin:2em}}table{{border-collapse:collapse}}td,th{{border:1px solid #999;padding:4px;overflow-wrap:anywhere}}</style><h1>{html.escape(title)}</h1><p>{html.escape(labels[2])}: {html.escape(str(data.get('synthetic')))}; {html.escape(labels[3])}: {html.escape(run_id)}; {html.escape(labels[4])}: {html.escape(status_label(data.get('status')))}</p><p>{html.escape(labels[5])}: {html.escape(json.dumps(data.get('sources',{}),ensure_ascii=False))}; {html.escape(labels[6])}: {html.escape(json.dumps(data.get('limits',[]),ensure_ascii=False))}; {html.escape(labels[7])}: {html.escape(json.dumps(data.get('error'),ensure_ascii=False))}</p><h2>{html.escape(labels[0])}</h2><table><tr><th>{html.escape(labels[8])}</th><th>{html.escape(labels[9])}</th><th>{html.escape(labels[10])}</th><th>{html.escape(labels[11])}</th><th>{html.escape(reason_label)}</th></tr>{html_rows}</table><h2>{html.escape(labels[13])}</h2>{evidence}<h2>{html.escape(labels[1])}</h2><table><tr><th>ID</th><th>{html.escape(issue_labels[0])}</th><th>{html.escape(issue_labels[1])}</th><th>{html.escape(issue_labels[2])}</th><th>{html.escape(issue_labels[3])}</th></tr>{issue_rows}</table>"
            (out/f"report.{lang}.md").write_text(md,encoding="utf-8"); (out/f"report.{lang}.html").write_text(f"<!doctype html><meta charset=utf-8><title>{html.escape(title)}</title>{body}",encoding="utf-8")
        with (out/"review.csv").open("w",encoding="utf-8",newline="") as f:
            w=csv.DictWriter(f,fieldnames=["id","status","machine_disposition","human_decision","note"]);w.writeheader();[w.writerow({k:("'"+str(i[k]) if isinstance(i.get(k),str) and i[k][:1] in "=+-@" else i.get(k)) for k in w.fieldnames}) for i in data["issues"]]
        return out
    def status(self):
        fields=("run_id","project_id","revision","outcome","stage","error","limits","artifacts")
        return [{key:self.get_result(run["id"])[key] for key in fields} for run in self.store.runs()]
    def run_fixture(self,spec_path,fixture_path,*,source_adapter=None,model_adapter=None,on_progress=None):
        from .workflow import run
        spec=self.validate(spec_path)
        if spec["status"]!="ready" or spec["unresolved_questions"]: raise PreflightError("fixture run requires ready spec")
        spec=self.store.save_spec(spec,fingerprint(spec)); run_id=self.store.create_run(spec,"fixture",{"synthetic":True})
        def progress(e):
            if on_progress:on_progress({"run_id":run_id,"stage":e["stage"],"status":"running"})
        baseline_ids=set(spec["reference_library"]["document_ids"]); baseline=[d for d in self.store.documents() if d["id"] in baseline_ids or d["collection_name"] in spec["reference_library"]["collection_ids"]]
        reference_evidence=[e for d in baseline for e in self.store.evidence(d["id"])]
        fixture=json.loads(Path(fixture_path).read_text(encoding="utf-8")); fixture["spec"]=spec; fixture["reference_evidence"]=reference_evidence
        fixture_dir=self.workspace/"fixture-inputs"; fixture_dir.mkdir(exist_ok=True)
        def retrieve(candidates):
            import hashlib
            for candidate in candidates:
                raw=candidate["quote"].encode("utf-8"); path=fixture_dir/(hashlib.sha256(raw).hexdigest()+".txt"); path.write_bytes(raw)
                imported=self.import_document(path,"discovery","paper"); candidate["document_id"]=imported["document_id"]; candidate["evidence"]=self.store.evidence(imported["document_id"])
            return candidates
        result=run(fixture,source_adapter,model_adapter,progress,retrieve)
        outcome=result.get("outcome","completed"); error=result.get("error"); stage=error.get("stage","report") if error else "report"
        for issue in result["issues"]: self.store.create_issue(issue)
        data={"run_id":run_id,"status":outcome,"execution_mode":"fixture","synthetic":True,"issues":self.store.issues(),"documents":result["candidates"],"candidates":result["candidates"],"findings":result["findings"],"baseline_document_ids":[d["id"] for d in baseline],"reference_evidence":reference_evidence,"sources":{"fixture":{"status":"failed" if outcome=="failed" else "complete"}},"limits":result.get("limits",[]),"error":error}
        self.store.finish_run(run_id,outcome,{"synthetic":True,"sources":data["sources"],"notes":["synthetic fixture"]},data); out=self.report(run_id,["zh","en","ja"])
        if on_progress:on_progress({"run_id":run_id,"stage":stage,"status":outcome})
        return {"run_id":run_id,"outcome":outcome,"stage":stage,"error":error,"stages":result["stages"],"issues":result["issues"],"artifacts":{"report":str(out)}}
    def get_result(self,run_id):
        run=self.store.run(run_id)
        if not run: raise KeyError(run_id)
        data=json.loads(run.get("report_data") or "{}")
        out=self.workspace/"reports"/run_id
        return {"run_id":run_id,"project_id":run["project_id"],"revision":run["revision"],"outcome":run["status"],"stage":(data.get("error") or {}).get("stage","report"),"error":data.get("error"),"limits":data.get("limits",[]),"artifacts":self.get_artifacts(run_id),"report_data":data,"findings":data.get("findings",[]),"issues":data.get("issues",[])}
    def get_artifacts(self,run_id):
        out=self.workspace/"reports"/run_id
        if not self.store.run(run_id) or not out.exists(): raise KeyError(run_id)
        files=[]
        for path in out.iterdir():
            parts=path.name.split("."); files.append({"language":parts[1] if len(parts)>2 else None,"format":parts[-1],"path":str(path)})
        return {"report":str(out),"files":files}
    def review_list(self):
        return [{**i,"events":json.loads(i["events"])} for i in self.store.issues()]
    def review_decide(self,issue,decision,note):
        self.store.decide(issue,decision,note); return next(i for i in self.review_list() if i["id"]==issue)
    def close(self): self.store.close()
