import pytest

from research_harness.errors import HarnessError
from research_harness.investigation_monitoring import MonitorStore


def _setup(tmp_path):
    store = MonitorStore(tmp_path)
    monitor = store.create({"rule_version": "r1"}, {"monitor_id": "mon-a"}, {"budget": {"max_cycles": 3, "max_total_tasks": 3}})
    return store, monitor["monitor_id"]


def _doc(version="v1", content="a", published="2026-01-02"):
    return {"document_id": "doc-a", "version": version, "content_sha256": content, "published_at": published}


def test_three_cycles_watermark_and_backlog_do_not_block_collection(tmp_path):
    store, monitor = _setup(tmp_path)
    first = store.begin_cycle(monitor, "c1", "2026-01-01", "2026-02-01")
    result = store.record_collection(first["cycle_id"], [_doc()], True, {"source": "complete"})
    assert result["watermark"]["window_end"] == "2026-02-01" and result["documents"]["judgment_backlog"] == 1
    second = store.begin_cycle(monitor, "c2", "2026-02-01", "2026-03-01")
    store.record_collection(second["cycle_id"], [_doc(published=None)], True, {})
    third = store.begin_cycle(monitor, "c3", "2026-03-01", "2026-04-01")
    assert third["reused"] is False
    state = store.status(monitor)
    assert state["cycles"][0]["judgment_backlog"] == [{"document_id": "doc-a", "document_version": "v1"}]


def test_partial_window_does_not_advance_watermark_and_reentry_is_idempotent(tmp_path):
    store, monitor = _setup(tmp_path)
    cycle = store.begin_cycle(monitor, "c1", "2026-01-01", "2026-02-01")
    assert store.begin_cycle(monitor, "c1", "2026-01-01", "2026-02-01")["reused"]
    result = store.record_collection(cycle["cycle_id"], [_doc(published=None)], False, {"reason": "failure"})
    assert result["watermark"] is None and result["status"] == "partial"
    assert store.status(monitor)["cycles"][0]["watermark"] is None
    completed = store.record_collection(cycle["cycle_id"], [_doc(published=None)], True, {"retry": True})
    assert completed["watermark"]["window_end"] == "2026-02-01"
    assert store.status(monitor)["cycles"][0]["documents"][0]["published_at"] == "unknown"


def test_pause_overlap_run_binding_and_restart(tmp_path):
    store, monitor = _setup(tmp_path)
    one = store.begin_cycle(monitor, "c1", "2026-01-01", "2026-02-01")
    with pytest.raises(HarnessError): store.begin_cycle(monitor, "overlap", "2026-01-15", "2026-02-15")
    assert store.bind_run(one["cycle_id"], "inv-1")["reused"] is False
    assert store.bind_run(one["cycle_id"], "inv-1")["reused"] is True
    store.pause(monitor)
    with pytest.raises(HarnessError): store.begin_cycle(monitor, "c2", "2026-02-01", "2026-03-01")
    store.resume(monitor)
    assert store.begin_cycle(monitor, "c2", "2026-02-01", "2026-03-01")["reused"] is False
    store.close()
    with MonitorStore(tmp_path) as reopened:
        assert reopened.status(monitor)["cycles"][0]["run_id"] == "inv-1"


def test_content_and_rule_change_require_new_judgment_and_budget_is_hard(tmp_path):
    store, monitor = _setup(tmp_path)
    one = store.begin_cycle(monitor, "c1", "2026-01-01", "2026-02-01")
    store.record_collection(one["cycle_id"], [_doc()], True, {})
    assert store.mark_judged(one["cycle_id"], "doc-a", "v1", "judgment-1")["status"] == "judged"
    two = store.begin_cycle(monitor, "c2", "2026-02-01", "2026-03-01")
    store.record_collection(two["cycle_id"], [_doc(version="v2", content="b")], True, {})
    assert store.status(monitor)["cycles"][1]["judgment_backlog"]
    store.update_profile(monitor, {"rule_version": "r2"})
    assert store.status(monitor)["profile_revision"] == 2
    assert store.status(monitor)["cycles"][0]["judgment_backlog"] == []
    third = store.begin_cycle(monitor, "c3", "2026-03-01", "2026-04-01")
    store.record_collection(third["cycle_id"], [_doc(version="v2", content="b", published="2026-03-02")], True, {})
    assert store.status(monitor)["cycles"][2]["judgment_backlog"]
    assert store.get_configuration(monitor, 1)["profile"]["rule_version"] == "r1"
    assert store.reserve_tasks(monitor, 2)["remaining"] == 1
    with pytest.raises(HarnessError): store.reserve_tasks(monitor, 2)


def test_completed_collection_reentry_reuses_and_different_window_is_rejected(tmp_path):
    store, monitor = _setup(tmp_path)
    cycle = store.begin_cycle(monitor, "c1", "2026-01-01", "2026-02-01")
    store.record_collection(cycle["cycle_id"], [_doc()], True, {"ok": True})
    assert store.record_collection(cycle["cycle_id"], [_doc()], True, {"ok": True})["documents"]["reused"] == 1
    with pytest.raises(HarnessError): store.begin_cycle(monitor, "c1", "2026-01-02", "2026-02-01")
