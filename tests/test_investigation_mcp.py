import asyncio

from research_harness.investigation_mcp import InvestigationMCPServer, _call, create_mcp_server


class FakeService:
    def __init__(self): self.calls=[]
    def doctor(self): self.calls.append("doctor"); return {"ok": True}
    def status(self, run_id=None): return {"run_id": run_id}
    def close(self): self.calls.append("close")


def test_call_projects_json_and_safe_errors():
    assert _call(FakeService(), "doctor") == {"ok": True}
    class Bad:
        def status(self): raise ValueError("secret input")
    assert _call(Bad(), "status")["error"]["code"] == "RH_INVESTIGATION_INTERNAL"
    assert "secret" not in str(_call(Bad(), "status"))


def test_mcp_registers_fifteen_tools():
    server = create_mcp_server(InvestigationMCPServer(".", service=FakeService()))
    tools = getattr(server, "_tool_manager")._tools
    expected = {"doctor", "validate_plan", "create_investigation", "get_pending_tasks", "submit_model_result",
                "advance_investigation", "resume_investigation", "investigation_status", "get_result", "get_artifacts",
                "export_report", "create_monitor", "run_monitor_once", "pause_monitor", "resume_monitor", "review_list", "review_decide"}
    assert set(tools) == expected


def test_async_handler_keeps_direct_service_call():
    fake = FakeService()
    server = create_mcp_server(InvestigationMCPServer(".", service=fake))
    handler = getattr(server, "_tool_manager")._tools["doctor"].fn
    assert asyncio.run(handler()) == {"ok": True}
    assert fake.calls == ["doctor"]
