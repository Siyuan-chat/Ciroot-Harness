from research_harness.investigation_review import ReviewStore


def j(relevance, human=False, reason="r"):
    return {"relevance": relevance, "human_review_required": human, "reason": reason}


def test_judgment_escalation_and_open_issue(tmp_path):
    s = ReviewStore(tmp_path)
    a = s.record_judgment("m", "c", "d", "v1", "r1", j("relevant", True), ["e1"])
    assert a["status"] == "open"
    assert a["original_judgment"]["relevance"] == "relevant" and a["reasons"]
    assert s.record_judgment("m", "c", "d", "v1", "r1", j("relevant", True), ["e1"])["issue_id"] == a["issue_id"]
    assert len(s.review_list()) == 1
    assert s.review_list()[0]["events"][0]["evidence_refs"] == ["e1"]
    s.record_judgment("m", "c", "d", "v2", "r1", j("irrelevant", False), ["e2"])
    assert s.review_list()[0]["status"] == "open"
    s.close()


def test_uncertain_and_forced_reason_require_human(tmp_path):
    s = ReviewStore(tmp_path)
    assert s.record_judgment("m", "c1", "d1", "v", "r", j("uncertain"), ["e"])["human_review_required"]
    assert s.record_judgment("m", "c2", "d2", "v", "r", j("irrelevant"), [], ["policy"])["status"] == "open"
    s.close()


def test_decision_idempotence_restart_and_isolation(tmp_path):
    s = ReviewStore(tmp_path)
    a = s.record_judgment("m", "c1", "d", "v", "r", j("relevant", True), [], None)
    assert s.review_decide(a["issue_id"], "relevant", "checked")["status"] == "resolved"
    assert s.review_decide(a["issue_id"], "relevant", "checked")["status"] == "resolved"
    s.close()
    s = ReviewStore(tmp_path)
    assert s.review_list("m")[0]["human_decision"] == "relevant"
    b = s.record_judgment("m", "c2", "d", "v", "r", j("relevant", False), [], None)
    assert b["issue_id"] != a["issue_id"]
    assert len(s.review_list()) == 2
    s.close()
