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
        if text:
            self.store.db.execute("UPDATE documents SET content=? WHERE id=?",(text,ident)); self.store.db.commit()
        self.store.add_evidence(ident,evidence)
        return {"document_id":ident,"evidence_count":len(evidence),"parse_errors":errors}
    def save_spec(self, spec_path):
        spec=self.validate(spec_path); self.store.save_spec(spec,fingerprint(spec)); return spec
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
            title={"zh":"研究报告","en":"Research report","ja":"調査レポート"}[lang]
            md=f"# {title}\n\nRun: `{run_id}`\n\nStatus: **{run['status']}**\n\nExecution mode: `{run['mode']}`; synthetic: `{manifest['synthetic']}`\n\n## Coverage\n\n"+json.dumps(manifest["sources"],ensure_ascii=False,indent=2)+"\n\n## Limits\n\n"+"\n".join('- '+x for x in manifest["notes"])+"\n"
            (out/f"report.{lang}.md").write_text(md,encoding="utf-8"); (out/f"report.{lang}.html").write_text(f"<!doctype html><meta charset=utf-8><title>{title}</title><pre>{html.escape(md)}</pre>",encoding="utf-8")
        with (out/"review.csv").open("w",encoding="utf-8",newline="") as f:
            w=csv.DictWriter(f,fieldnames=["id","status","machine_disposition","human_decision","note"]);w.writeheader();[w.writerow({k:("'"+str(i[k]) if isinstance(i.get(k),str) and i[k][:1] in "=+-@" else i.get(k)) for k in w.fieldnames}) for i in data["issues"]]
        return out
    def status(self): return self.store.runs()
    def review_list(self): return self.store.issues()
    def review_decide(self,issue,decision,note): self.store.decide(issue,decision,note)
