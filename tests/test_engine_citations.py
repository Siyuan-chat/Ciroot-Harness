from research_harness.research_engines import resolve_engine_citations


def _evidence(revision="pr-1", text="Alpha exact evidence passage."):
    value = {"evidence_id": "ev-1", "document_id": "doc-1", "version_id": "ver-1",
             "text": text, "locator": {"kind": "page", "value": "2"}}
    if revision is not None:
        value["parse_revision_id"] = revision
    return value


def _envelope(evidence=None):
    return {"run_id": "r-1", "task": {"task_id": "t-1", "task_version": 1}, "evidence": evidence or [_evidence()]}


def _citation(**overrides):
    value = {"citation_id": "c-1", "evidence_id": "ev-1", "document_id": "doc-1", "version_id": "ver-1",
             "parse_revision_id": "pr-1", "locator": {"kind": "page", "value": "2"}, "quote": "Alpha exact evidence passage."}
    value.update(overrides)
    return value


def _result(citations):
    return {"draft": {"sections": [{"title": "draft"}], "claims": [{"claim_id": "cl-1", "citation_ids": ["c-1"]}],
                      "citations": citations, "coverage_gaps": []}}


def test_unique_exact_citation_is_kept_and_bound_to_parse_revision():
    output = resolve_engine_citations(_envelope(), _result([_citation()]))
    assert output["issues"] == []
    assert output["draft"]["citations"][0]["parse_revision_id"] == "pr-1"
    assert output["draft"]["claims"][0]["citation_ids"] == ["c-1"]


def test_wrong_document_version_revision_locator_and_fabricated_quote_are_removed():
    bads = [
        _citation(citation_id="c-1", document_id="another"),
        _citation(citation_id="c-2", version_id="ver-2"),
        _citation(citation_id="c-3", parse_revision_id="pr-2"),
        _citation(citation_id="c-4", locator={"kind": "page", "value": "3"}),
        _citation(citation_id="c-5", quote="fabricated claim"),
    ]
    output = resolve_engine_citations(_envelope(), {"draft": {"sections": [], "claims": [], "citations": bads, "coverage_gaps": []}})
    assert output["draft"]["citations"] == []
    assert len(output["issues"]) == 5


def test_repeated_quote_is_ambiguous_and_duplicate_citation_ids_are_rejected():
    duplicate_text = "Alpha exact evidence passage. Beta. Alpha exact evidence passage."
    output = resolve_engine_citations(_envelope([_evidence(text=duplicate_text)]), {"draft": {"sections": [], "claims": [], "citations": [_citation(), _citation(citation_id="c-2", evidence_id="missing")], "coverage_gaps": []}})
    assert output["draft"]["citations"] == []
    assert {item["code"] for item in output["issues"]} == {"RH_ENGINE_QUOTE", "RH_ENGINE_EVIDENCE_REF"}


def test_duplicate_citation_ids_invalidate_every_occurrence_and_overlapping_quote_is_ambiguous():
    duplicate = resolve_engine_citations(_envelope(), {"draft": {"sections": [], "claims": [], "citations": [_citation(), _citation()], "coverage_gaps": []}})
    assert duplicate["draft"]["citations"] == []
    assert len(duplicate["issues"]) == 2
    assert all(issue["code"] == "RH_ENGINE_CITATION_ID" for issue in duplicate["issues"])
    overlapping = resolve_engine_citations(_envelope([_evidence(text="aaa")]), {"draft": {"sections": [], "claims": [], "citations": [_citation(quote="aa")], "coverage_gaps": []}})
    assert overlapping["draft"]["citations"] == []
    assert overlapping["issues"][0]["code"] == "RH_ENGINE_QUOTE"


def test_legacy_evidence_is_explicitly_labeled_and_cannot_claim_a_revision():
    evidence = _evidence(revision=None, text="Legacy quote only once.")
    evidence["legacy"] = True
    c = _citation(parse_revision_id=None, quote="Legacy quote only once.")
    accepted = resolve_engine_citations(_envelope([evidence]), _result([c]))
    assert accepted["draft"]["citations"][0]["legacy"] is True
    rejected = resolve_engine_citations(_envelope([evidence]), _result([_citation(quote="Legacy quote only once.")]))
    assert rejected["draft"]["citations"] == []
    assert rejected["issues"][0]["code"] == "RH_ENGINE_PARSE_REVISION"

    unmarked = _evidence(revision=None, text="Legacy quote only once.")
    rejected_unmarked = resolve_engine_citations(_envelope([unmarked]), _result([c]))
    assert rejected_unmarked["draft"]["citations"] == []
    assert rejected_unmarked["issues"][0]["code"] == "RH_ENGINE_PARSE_REVISION"


def test_unknown_evidence_and_malformed_citation_arrays_become_issues():
    output = resolve_engine_citations(_envelope(), {"draft": {"sections": "bad", "claims": "bad", "citations": [_citation(evidence_id="unknown")], "coverage_gaps": None}})
    assert output["draft"] == {"sections": [], "claims": [], "citations": [], "coverage_gaps": []}
    assert {item["code"] for item in output["issues"]} == {
        "RH_ENGINE_EVIDENCE_REF", "RH_ENGINE_SECTIONS_INVALID", "RH_ENGINE_CLAIMS_INVALID", "RH_ENGINE_COVERAGE_INVALID"
    }


def test_json_unhashable_citation_evidence_and_claim_refs_return_issues_not_exceptions():
    malformed = {"draft": {"sections": [], "claims": [{"citation_ids": [["c-1"], {"id": "c-1"}, 7]}],
                           "citations": [{"citation_id": ["c-1"], "evidence_id": ["ev-1"]},
                                         {"citation_id": "c-2", "evidence_id": {"id": "ev-1"}}], "coverage_gaps": []}}
    output = resolve_engine_citations(_envelope(), malformed)
    assert output["draft"]["citations"] == []
    assert len(output["issues"]) == 5
