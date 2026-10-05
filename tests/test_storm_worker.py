import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from research_harness.research_engine_gateway import _storm_claims_for_synthesis, _storm_frozen_rows
from research_harness.investigation import InvestigationError, InvestigationService
from research_harness.engines.storm_worker import _article_draft, _bounded_tokens
from research_harness.investigation_contracts import validate_runtime


def test_storm_synthesis_projection_requires_exact_claim_citation_and_existing_finding():
    citation = {"citation_id":"c1", "evidence_id":"ev1", "document_id":"doc1", "version_id":"v1",
        "parse_revision_id":"p1", "quote":"exact frozen quote"}
    resolved = {"draft":{"citations":[citation], "claims":[
        {"claim_id":"claim1", "text":"supported text", "citation_ids":["c1"]},
        {"claim_id":"claim2", "text":"unsupported text", "citation_ids":[]},
        {"claim_id":"claim3", "text":"wrong evidence", "citation_ids":["c1"]}]}}
    task = {"payload":{"evidence":[{"evidence_id":"ev1"}], "findings":[{"evidence_ids":["ev1"]}]}}
    claims, excluded = _storm_claims_for_synthesis(resolved, task)
    assert len(claims) == 2  # same citation is preserved for distinct generated claims; schema checks it downstream
    assert claims[0]["finding_refs"] == [0]
    assert claims[0]["quote"] == "exact frozen quote"
    assert all(claim["evidence_refs"] == ["ev1"] for claim in claims)
    assert not excluded


def test_storm_claim_without_extract_finding_is_excluded():
    resolved = {"draft":{"citations":[{"citation_id":"c1", "evidence_id":"ev1", "document_id":"d", "version_id":"v", "quote":"q"}],
        "claims":[{"claim_id":"c", "text":"candidate", "citation_ids":["c1"]}]}}
    claims, excluded = _storm_claims_for_synthesis(resolved, {"payload":{"evidence":[{"evidence_id":"ev1"}], "findings":[]}})
    assert claims == []
    assert excluded[0]["reason"] == "citation is not linked to an accepted extraction finding"


def test_storm_rm_scope_rereads_the_five_frozen_paper_and_patent_extracts():
    root = Path(".local/integration-20261005/s2-case")
    raw = (root / "evidence.json").read_bytes()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(raw).hexdigest() == manifest["files"]["evidence_sha256"]
    package = json.loads(raw)
    assert package["scope"] == "extracts_only"
    evidence = package["evidence"]
    assert len(evidence) == 5
    assert "marked legacy_unversioned" in manifest["legacy_revision_policy"]
    assert all(not row.get("parse_revision_id") for row in evidence)
    before = [(row["evidence_id"], row["document_id"], row["version_id"], row["text"], row["locator"]) for row in evidence]
    scoped = [{**row, "legacy": True} if manifest.get("legacy_revision_policy", "").find("marked legacy_unversioned") >= 0 and not row.get("parse_revision_id") else row for row in evidence]
    rows = _storm_frozen_rows(scoped, "polymer membrane examples patent", 5)
    assert {row["meta"]["evidence_id"] for row in rows} <= {entry[0] for entry in before}
    assert all(row["snippets"][0] in next(e["text"] for e in evidence if e["evidence_id"] == row["meta"]["evidence_id"]) for row in rows)
    assert before == [(row["evidence_id"], row["document_id"], row["version_id"], row["text"], row["locator"]) for row in evidence]


def test_real_service_writing_schema_accepts_block_kinds_and_rejects_gap(tmp_path):
    from test_investigation_c1 import RUNTIME, SCENARIO, SPEC
    with InvestigationService(tmp_path) as service:
        run = service.create_investigation(SPEC, RUNTIME, SCENARIO)["run_id"]
        service._task(run, "writing", "write", {"sections": []})
        task = next(item for item in service.get_pending_tasks(run) if item["role"] == "writing")
        section = {"deliverable_type":"technical_report", "language":"en", "section_id":"s1", "title":"Evidence",
            "body":"Frozen evidence text.", "claim_ids":[], "section_kind":"fact", "block_kind":"method"}
        invalid = dict(section, section_id="s2", section_kind="gap")
        import pytest
        with pytest.raises(InvestigationError, match="failed schema validation"):
            service.submit_model_result(run, task["task_id"], {"sections":[invalid]}, task["task_version"])
        assert service.get_pending_tasks(run)[-1]["task_id"] == task["task_id"]
        assert service.submit_model_result(run, task["task_id"], {"sections":[section]}, task["task_version"])["status"] == "accepted"


def test_storm_module_token_overrides_never_expand_profile_budget():
    assert _bounded_tokens(None, 800) == 800
    assert _bounded_tokens(64, 800) == 64
    assert _bounded_tokens(900, 800) == 800
    import pytest
    with pytest.raises(RuntimeError):
        _bounded_tokens(0, 800)


def test_storm_article_projection_keeps_nested_citations_and_empty_parent():
    evidence = [{"evidence_id":"ev1", "document_id":"doc1", "version_id":"v1", "parse_revision_id":"p1",
        "locator":{"page":2}, "text":"Exact frozen quote appears here."}]
    info = SimpleNamespace(meta={"evidence_id":"ev1"}, snippets=["Exact frozen quote"])
    nested = SimpleNamespace(section_name="Finding", content="Exact frozen quote [1].", children=[])
    parent = SimpleNamespace(section_name="Evidence", content=None, children=[nested])
    root = SimpleNamespace(section_name="Topic", content=None, children=[parent])
    article = SimpleNamespace(root=root, reference={"url_to_unified_index":{"frozen:ev1":1},
        "url_to_info":{"frozen:ev1":info}})

    draft = _article_draft(article, evidence)

    assert [section["title"] for section in draft["sections"]] == ["Evidence / Finding"]
    assert [section["section_id"] for section in draft["sections"]] == ["storm-1"]
    assert len(draft["claims"]) == 1
    assert draft["claims"][0]["citation_ids"] == ["storm-ev1"]
    assert draft["citations"][0]["quote"] == "Exact frozen quote"
    assert draft["tree_trace"][0]["content_chars"] == 0


def test_storm_article_projection_keeps_uncited_nodes_as_draft_and_never_guesses_indexes():
    evidence = [{"evidence_id":"ev1", "document_id":"doc1", "version_id":"v1", "text":"Exact frozen quote."}]
    info = SimpleNamespace(meta={"evidence_id":"ev1"}, snippets=["Exact frozen quote"])
    good = SimpleNamespace(section_name="Grounded", content="Exact frozen quote [1].", children=[])
    unsupported = SimpleNamespace(section_name="Unsupported", content="Uncited prose.", children=[])
    unknown = SimpleNamespace(section_name="Unknown ref", content="Unmapped [99].", children=[])
    root = SimpleNamespace(section_name="Topic", content=None, children=[good, unsupported, unknown])
    article = SimpleNamespace(root=root, reference={"url_to_unified_index":{"frozen:ev1":1},
        "url_to_info":{"frozen:ev1":info}})

    draft = _article_draft(article, evidence)

    assert len(draft["sections"]) == 3
    assert len({section["section_id"] for section in draft["sections"]}) == 3
    assert [claim["text"] for claim in draft["claims"]] == ["Exact frozen quote [1]."]
    assert [citation["evidence_id"] for citation in draft["citations"]] == ["ev1"]
    assert "No article claim had a uniquely mapped frozen evidence citation." not in draft["coverage_gaps"]


def test_storm_article_projection_without_any_valid_reference_remains_unaccepted_draft():
    node = SimpleNamespace(section_name="Uncited", content="No verifiable source [3].", children=[])
    article = SimpleNamespace(root=SimpleNamespace(section_name="Topic", content=None, children=[node]),
        reference={"url_to_unified_index":{}, "url_to_info":{}})

    draft = _article_draft(article, [{"evidence_id":"ev1", "text":"Some evidence."}])

    assert draft["sections"][0]["text"] == "No verifiable source [3]."
    assert draft["claims"] == []
    assert draft["citations"] == []
    assert draft["coverage_gaps"] == ["No article claim had a uniquely mapped frozen evidence citation."]


def test_runtime_contract_accepts_explicit_storm_without_embedding_configuration():
    from test_investigation_c1 import RUNTIME
    runtime = dict(RUNTIME)
    runtime.update({"mode":"api", "allow_network":True, "budget":{**RUNTIME["budget"], "max_model_calls":12},
        "model_api":{"provider":"deepseek", "model":"offline-test", "api_key_env":"TEST_KEY", "max_output_tokens":800, "timeout_seconds":10},
        "research_engine":{"name":"storm", "python_executable":"C:/optional/storm-runtime/Scripts/python.exe", "timeout_seconds":60}})
    validate_runtime(runtime)


def test_worker_guard_allows_only_exact_null_device_and_blocks_lookalike(tmp_path):
    cache_root = tmp_path / "rh-storm-home-guard"
    cache_root.mkdir()
    source = (
        "import os,sqlite3; from research_harness.engines.worker_runtime import install_io_guard; "
        "install_io_guard(); open(os.devnull, 'wb').close(); "
        "sqlite3.connect(':memory:').close(); sqlite3.connect(os.path.join(os.environ['RH_WORKER_CACHE_ROOT'],'cache.db')).close(); "
        "\ntry: open(os.devnull + '.outside', 'wb').close()\n"
        "except PermissionError: print('blocked')\n"
        "else: raise SystemExit('lookalike was allowed')\n"
        "try: sqlite3.connect(os.path.join(os.path.dirname(os.environ['RH_WORKER_CACHE_ROOT']),'outside.sqlite'))\n"
        "except PermissionError: print('database blocked')\n"
        "else: raise SystemExit('non-cache database was allowed')"
    )
    env = {key: value for key, value in os.environ.items() if key.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH"}}
    result = subprocess.run([sys.executable, "-c", source], cwd=Path(__file__).resolve().parents[1],
        env=env | {"PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"), "PYTHONNOUSERSITE": "1",
                   "RH_WORKER_CACHE_ROOT": str(cache_root)},
        capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines() == ["blocked", "database blocked"]
