import pytest
from research_harness.investigation_sources import SyntheticTransport, SourceError, baseline_snapshot, normalize, policy_allows

def test_paging_and_failure_are_explicit():
    transport=SyntheticTransport([{"source":"synthetic-paper","query_id":"q1","candidates":[{"document_id":"d1"}],"next_cursor":"p2"},{"source":"synthetic-paper","query_id":"q1","cursor":"p2","error":"timeout"}])
    assert transport.search("synthetic-paper","q1")["next_cursor"]=="p2"
    with pytest.raises(SourceError) as error: transport.search("synthetic-paper","q1","p2")
    assert error.value.code=="RH_SOURCE_TIMEOUT"

def test_normalization_and_confidential_default_deny():
    ev=normalize({"document_id":"d1","version":"v2","content_type":"application/xml","text":"<root><p id='p1'>quoted text</p><claim id='c1'>claim text</claim></root>"})
    assert [x["locator"]["value"] for x in ev]==["p1","c1"] and ev[0]["version_id"]=="v2"
    secret={"visibility":"confidential","company_id":"co"}
    assert not policy_allows(secret,{"executor_id":"host-synthetic"})
    assert policy_allows(secret,{"model_id":"local","data_policy":{"company_id":"co","allowed_models":["local"],"allow_query_egress":True}})

def test_baseline_freezes_authorized_versions_only():
    references=[{"document_id":"base","version":"v1","text":"baseline v1","visibility":"public"},{"document_id":"secret","version":"v1","text":"hidden","visibility":"confidential","company_id":"other"}]
    snap=baseline_snapshot(references,{"executor_id":"host-synthetic"})
    assert [(x["document_id"],x["version_id"]) for x in snap]==[("base","v1")]
