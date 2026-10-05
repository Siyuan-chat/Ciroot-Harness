import hashlib
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from research_harness.errors import ValidationError
from research_harness.patent_analysis_adapter import analyze_patent_input, load_and_analyze_patent_input


def _bundle():
    text = "1. An independent claim for a polymer composition."
    locator = {"kind": "xml_node", "value": "/claims/claim[1]"}
    evidence = {
        "evidence_id": "ev-p1-1", "publication_id": "P1", "version_id": "P1-A1",
        "parse_revision_id": "pr-p1-1", "locator": locator, "text": text,
    }
    claim = {
        "claim_number": 1, "text": text, "language": "en",
        "source_bindings": [{
            "evidence_id": evidence["evidence_id"], "publication_id": "P1",
            "version_id": "P1-A1", "parse_revision_id": "pr-p1-1",
            "locator": locator, "quote": text,
        }],
    }
    return {
        "schema_version": "1", "run_id": "run-frozen-1", "input_id": "frozen-patent-case-1",
        "selection_reason": "Existing locator is readable; case selected by material availability.",
        "publications": [{
            "publication_id": "P1", "version_id": "P1-A1", "parse_revision_id": "pr-p1-1",
            "language": "en", "family_ids": ["F1"], "classifications": [{"scheme": "IPC", "code": "C08G 73/00"}],
            "citations": [], "source_evidence": [evidence], "claims": [claim],
        }],
    }


def test_load_adapter_runs_offline_and_returns_frozen_input_binding(tmp_path, monkeypatch):
    def forbidden_network(*_args, **_kwargs):
        raise AssertionError("adapter must not use the network")

    monkeypatch.setattr(socket, "create_connection", forbidden_network)
    monkeypatch.setattr(socket.socket, "connect", forbidden_network)
    path = tmp_path / "frozen.json"
    raw = json.dumps(_bundle(), ensure_ascii=False).encode("utf-8")
    path.write_bytes(raw)

    result = load_and_analyze_patent_input(path.resolve())

    assert result["run_id"] == "run-frozen-1"
    assert result["input_binding"] == {
        "input_id": "frozen-patent-case-1",
        "selection_reason": "Existing locator is readable; case selected by material availability.",
        "source_kind": "local_frozen_json", "path": str(path.resolve()),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    assert result["coverage"]["publication_count"] == 1
    assert result["coverage"]["source_bound_publication_count"] == 1
    assert result["analysis"]["publication_analyses"][0]["claims"][0]["trusted_structure_eligible"] is True
    assert result["claim_acceptance"] == "not_assessed"
    assert "legal or scientific conclusions" in result["limitations"][0]


def test_adapter_rejects_remote_input_fields_and_missing_run_provenance(tmp_path):
    payload = _bundle()
    payload["source_url"] = "https://example.invalid/patent"
    with pytest.raises(ValidationError, match="local frozen input"):
        analyze_patent_input(payload, input_path=tmp_path / "x.json", input_sha256="a" * 64)

    payload = _bundle()
    payload.pop("run_id")
    with pytest.raises(ValidationError, match="exactly schema_version"):
        analyze_patent_input(payload, input_path=tmp_path / "x.json", input_sha256="a" * 64)


def test_local_json_loader_rejects_relative_non_json_and_malformed_inputs(tmp_path):
    with pytest.raises(ValidationError, match="absolute"):
        load_and_analyze_patent_input("relative.json")
    text_file = tmp_path / "bundle.txt"
    text_file.write_text("{}", encoding="utf-8")
    with pytest.raises(ValidationError, match=".json"):
        load_and_analyze_patent_input(text_file.resolve())
    bad_json = tmp_path / "broken.json"
    bad_json.write_text("{oops", encoding="utf-8")
    with pytest.raises(ValidationError, match="valid UTF-8 JSON"):
        load_and_analyze_patent_input(bad_json.resolve())


def test_local_json_loader_rejects_unc_path_before_resolving_or_reading():
    with pytest.raises(ValidationError, match="network/UNC"):
        load_and_analyze_patent_input(r"\\server\share\frozen.json")


def test_synthetic_example_is_valid_and_explicitly_not_real_research():
    root = Path(__file__).parents[1]
    path = root / "examples" / "patent_analysis" / "frozen-input.synthetic.json"
    result = load_and_analyze_patent_input(path.resolve())
    readme = (path.parent / "README.md").read_text(encoding="utf-8").casefold()
    assert result["input_binding"]["input_id"] == "synthetic-patent-input-001"
    assert result["analysis"]["input_publications"][0]["publication_id"] == "SYNTHETIC-PUB-001"
    assert "synthetic" in readme and "not scientific" in readme


def test_cli_patent_analyze_prints_structured_partial_json_without_side_effects(tmp_path):
    root = Path(__file__).parents[1]
    workspace = tmp_path / "unused-workspace"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root / "src")
    command = [sys.executable, "-m", "research_harness.cli", "patent-analyze", "--input",
               str((root / "examples" / "patent_analysis" / "frozen-input.synthetic.json").resolve())]
    completed = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=30)
    assert completed.returncode == 4
    result = json.loads(completed.stdout)
    assert result["status"] == "partial"
    assert result["claim_acceptance"] == "not_assessed"
    assert result["input_binding"]["sha256"]
    assert not workspace.exists()
