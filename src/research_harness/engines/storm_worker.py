"""Offline-scope STORM adapter. All model and retrieval work is brokered by core."""
from __future__ import annotations

import os
import re
import atexit
import shutil
import sys
import tempfile
import uuid

from .worker_runtime import RpcClient, install_io_guard, read_message
from ..research_engine_protocol import PROTOCOL, encode_message


def _text(reply):
    result = reply.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("text"), str):
        raise RuntimeError("core broker returned no complete text")
    return result["text"]


def _bounded_tokens(requested, limit):
    if type(limit) is not int or limit < 1 or (requested is not None and (type(requested) is not int or requested < 1)):
        raise RuntimeError("invalid STORM token limit")
    return min(requested if requested is not None else limit, limit)


def _article_draft(article, evidence_rows):
    """Project only each cited Article node's own exact frozen references."""
    references = getattr(article, "reference", {})
    url_info = references.get("url_to_info", {})
    url_to_index = references.get("url_to_unified_index", {})
    index_to_url = {int(index): url for url, index in url_to_index.items()}
    evidence_by_id = {row.get("evidence_id"): row for row in evidence_rows if isinstance(row, dict)}
    citations, claims, sections = [], [], []
    citation_by_id = {}
    tree_trace = []

    def walk(node, path=(), depth=0):
        for child in getattr(node, "children", []):
            child_path = path + (str(getattr(child, "section_name", "")),)
            content = getattr(child, "content", "")
            content = content if isinstance(content, str) else ""
            raw_indexes = re.findall(r"\[(\d+)\]", content)
            tree_trace.append({"depth": depth + 1, "name": child_path[-1], "content_chars": len(content),
                "citation_indexes": raw_indexes})
            if content.strip():
                section_citations = []
                for raw_index in raw_indexes:
                    url = index_to_url.get(int(raw_index))
                    info = url_info.get(url) if url else None
                    meta = getattr(info, "meta", {}) if info else {}
                    evidence_id = meta.get("evidence_id") if isinstance(meta, dict) else None
                    evidence = evidence_by_id.get(evidence_id)
                    if not isinstance(evidence, dict) or not isinstance(evidence.get("text"), str):
                        continue
                    quote = next((snippet for snippet in getattr(info, "snippets", [])
                        if isinstance(snippet, str) and snippet and snippet in evidence["text"]), None)
                    if not quote:
                        continue
                    citation_id = "storm-" + str(evidence_id)
                    if citation_id not in citation_by_id:
                        citation = {"citation_id": citation_id, "evidence_id": evidence_id,
                            "document_id": evidence.get("document_id"), "version_id": evidence.get("version_id"),
                            "parse_revision_id": evidence.get("parse_revision_id"), "locator": evidence.get("locator"), "quote": quote}
                        citations.append(citation); citation_by_id[citation_id] = citation
                    section_citations.append(citation_id)
                sections.append({"section_id": "storm-" + str(len(sections)+1),
                    "title": " / ".join(part for part in child_path if part), "text": content})
                if section_citations:
                    claims.append({"claim_id": "storm-claim-" + str(len(claims)+1), "text": content,
                        "kind": "synthesis", "citation_ids": sorted(set(section_citations))})
            walk(child, child_path, depth + 1)

    root = getattr(article, "root", None)
    if root is not None:
        walk(root)
    return {"sections": sections, "claims": claims, "citations": citations,
        "tree_trace": tree_trace,
        "coverage_gaps": ([] if claims else ["No article claim had a uniquely mapped frozen evidence citation."])}


def run(envelope, client):
    # These imports are deliberately delayed until after the cost map is made local.
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "true"
    os.environ["DSP_CACHEBOOL"] = "false"
    worker_home = tempfile.mkdtemp(prefix="rh-storm-home-")
    os.environ["HOME"] = worker_home
    os.environ["USERPROFILE"] = worker_home
    os.environ["RH_WORKER_CACHE_ROOT"] = worker_home
    atexit.register(shutil.rmtree, worker_home, ignore_errors=True)
    dspy_cache = tempfile.mkdtemp(prefix="rh-storm-dspy-")
    os.environ["DSP_CACHEDIR"] = dspy_cache
    atexit.register(shutil.rmtree, dspy_cache, ignore_errors=True)
    import dspy
    from knowledge_storm.interface import Information
    from knowledge_storm.storm_wiki.engine import STORMWikiLMConfigs, STORMWikiRunner, STORMWikiRunnerArguments
    from knowledge_storm.storm_wiki.modules.storm_dataclass import StormInformationTable
    from knowledge_storm.storm_wiki.modules.callback import BaseCallbackHandler

    profile = envelope["profile"]
    limits = envelope["limits"]
    class BrokerLM(dspy.LM):
        def __init__(self):
            super().__init__(model="openai/core-broker")
            self.kwargs.update({"temperature": 0, "max_tokens": limits["max_output_tokens"], "n": 1})

        def basic_request(self, prompt, **kwargs):
            return self.__call__(prompt=prompt, **kwargs)

        def __call__(self, prompt=None, messages=None, **kwargs):
            if messages is None:
                if not isinstance(prompt, str):
                    raise RuntimeError("STORM supplied no text prompt")
                messages = [{"role": "user", "content": prompt}]
            if not isinstance(messages, list) or not messages:
                raise RuntimeError("STORM supplied invalid messages")
            normalized = []
            for message in messages:
                role = message.get("role") if isinstance(message, dict) else None
                content = message.get("content") if isinstance(message, dict) else None
                if role not in {"system", "user", "assistant"} or not isinstance(content, str):
                    # DSPy often passes a rendered prompt string; preserve it as user text.
                    if isinstance(prompt, str):
                        normalized = [{"role": "user", "content": prompt}]
                        break
                    raise RuntimeError("STORM model message shape is unsupported")
                normalized.append({"role": role, "content": content})
            module_limit = kwargs.get("max_output_tokens", kwargs.get("max_tokens"))
            reply = client.call("model_call", "storm-model-" + uuid.uuid4().hex, "storm", {
                "messages": normalized, "max_output_tokens": _bounded_tokens(module_limit, limits["max_output_tokens"])})
            return [_text(reply)]

    class FrozenLexicalTable(StormInformationTable):
        """Replace upstream SentenceTransformer loading with explicit lexical ranking."""
        def prepare_table_for_retrieval(self):
            self._lexical_ready = True

        def retrieve_information(self, queries, search_top_k):
            query_list = [queries] if isinstance(queries, str) else list(queries)
            infos = list(self.url_to_info.values())
            selected = []
            for query in query_list:
                terms = set(re.findall(r"[\w-]+", query.casefold()))
                ranked = sorted(infos, key=lambda info: (-len(terms & set(re.findall(r"[\w-]+", " ".join(info.snippets).casefold()))), info.url))
                selected.extend(ranked[:max(1, int(search_top_k))])
            unique = {}
            for info in selected:
                unique[info.url] = info
            return list(unique.values())

    class FrozenRM:
        def __call__(self, query_or_queries, exclude_urls=None):
            queries = query_or_queries if isinstance(query_or_queries, list) else [query_or_queries]
            results = []
            for query in queries:
                response = client.call("retrieve_frozen", "storm-rm-" + uuid.uuid4().hex, "storm_frozen_scope", {
                    "query": str(query), "top_k": int(limits["search_top_k"]), "exclude_urls": list(exclude_urls or [])})
                rows = response.get("result")
                if not isinstance(rows, list):
                    raise RuntimeError("core retrieval response was invalid")
                retrieved_evidence_ids.extend(item.get("meta", {}).get("evidence_id") for item in rows
                    if isinstance(item, dict) and isinstance(item.get("meta"), dict) and isinstance(item["meta"].get("evidence_id"), str))
                results.append(rows)
            return results[0] if len(results) == 1 else [item for group in results for item in group]

    retrieved_evidence_ids = []
    model = BrokerLM()
    configs = STORMWikiLMConfigs()
    configs.set_conv_simulator_lm(model)
    configs.set_question_asker_lm(model)
    configs.set_outline_gen_lm(model)
    configs.set_article_gen_lm(model)
    configs.set_article_polish_lm(model)
    output_dir = tempfile.mkdtemp(prefix="rh-storm-")
    atexit.register(shutil.rmtree, output_dir, ignore_errors=True)
    args = STORMWikiRunnerArguments(output_dir=output_dir,
        max_conv_turn=int(limits["max_conv_turn"]), max_perspective=1,
        max_search_queries_per_turn=int(limits["max_search_queries_per_turn"]),
        disable_perspective=True, search_top_k=int(limits["search_top_k"]),
        retrieve_top_k=int(limits["retrieve_top_k"]), max_thread_num=1)
    runner = STORMWikiRunner(args, configs, FrozenRM())
    # No custom class is injected into upstream curation. Replace its table factory
    # with our public InformationTable subclass before invoking the runner.
    original = runner.run_knowledge_curation_module
    def curation(*a, **kw):
        result = original(*a, **kw)
        if isinstance(result, tuple):
            table, log = result
            return FrozenLexicalTable(table.conversations), log
        return FrozenLexicalTable(result.conversations)
    runner.run_knowledge_curation_module = curation
    topic = envelope["task"]["payload"].get("question") or envelope["task"]["payload"].get("research_question") or envelope.get("research_question") or "Synthesize the supplied frozen evidence."
    runner.topic = str(topic)
    runner.article_dir_name = re.sub(r"[^A-Za-z0-9_-]+", "_", str(topic))[:80] or "frozen_evidence"
    runner.article_output_dir = os.path.join(output_dir, runner.article_dir_name)
    os.makedirs(runner.article_output_dir, exist_ok=True)
    callback = BaseCallbackHandler()
    information_table = runner.run_knowledge_curation_module(callback_handler=callback)
    curated_evidence_ids = sorted({info.meta.get("evidence_id") for info in information_table.url_to_info.values()
        if isinstance(getattr(info, "meta", None), dict) and isinstance(info.meta.get("evidence_id"), str)})
    outline = runner.run_outline_generation_module(information_table=information_table, callback_handler=callback)
    article = runner.run_article_generation_module(outline=outline, information_table=information_table, callback_handler=callback)
    projected = _article_draft(article, envelope.get("evidence", []))
    citations, claims, sections = projected["citations"], projected["claims"], projected["sections"]
    section_names = article.get_first_level_section_names()
    gaps = ["retrieval_scope=frozen_task_evidence; retrieval_mode=lexical; no vector model used",
            "STORM 1.1.1 hardcodes disable_perspective=False in curation; perspective calls remain budgeted"]
    gaps.extend(projected["coverage_gaps"])
    return {"protocol": PROTOCOL, "op": "result", "identity": client.identity,
        "engine": {"name": "storm", "version": "1.1.1"},
        "draft": {"sections": sections, "claims": claims, "citations": citations, "coverage_gaps": gaps},
        "trace": {"retrieval": "frozen_evidence_only", "ranking": "lexical", "disable_perspective_effective": False,
                  "retrieved_evidence_ids": sorted(set(retrieved_evidence_ids)), "curated_evidence_ids": curated_evidence_ids,
                  "article_section_count": len(section_names),
                  "article_reference_count": len(getattr(article, "reference", {}).get("url_to_info", {})),
                  "article_tree": projected["tree_trace"],
                  "mapped_citation_count": len(citations)}}


def main():
    import os
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "true"
    os.environ["DSP_CACHEBOOL"] = "false"
    import asyncio
    loop = asyncio.new_event_loop()
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
        import traceback
        frames = traceback.extract_tb(error.__traceback__)
        result = {"protocol": PROTOCOL, "op": "result", "identity": client.identity,
                  "engine": {"name": "storm", "version": "1.1.1"},
                  "draft": {"sections": [], "claims": [], "citations": [], "coverage_gaps": ["STORM execution failed; review required."]},
                  "trace": {"status": "failed", "error_type": type(error).__name__,
                      "error_name": getattr(error, "name", None),
                      "error_frames": [{"file": os.path.basename(frame.filename), "line": frame.lineno, "function": frame.name}
                          for frame in frames[-8:] if frame.filename.endswith(".py")]}}
    sys.stdout.buffer.write(encode_message(result)); sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
