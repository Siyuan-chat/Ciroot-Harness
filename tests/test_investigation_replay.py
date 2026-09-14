import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from investigation_replay import result_for

def test_object_target_respects_languages():
    result = result_for({"role": "writing", "payload": {"report_targets": [{"deliverable_type": "technical_report", "languages": ["en"]}], "claims": [{"claim_id": "c"}]}})
    assert [x["language"] for x in result["sections"]] == ["en"]
    assert result["sections"][0]["deliverable_type"] == "technical_report"

def test_empty_evidence_is_insufficient():
    assert result_for({"role": "synthesis", "payload": {"evidence": []}}) == {"claims": []}
    assert result_for({"role": "verification", "payload": {"claims": []}})["verification"]["status"] == "insufficient"
