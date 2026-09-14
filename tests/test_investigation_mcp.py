import asyncio
import sys
from pathlib import Path

from research_harness.investigation_mcp import InvestigationMCPServer, _call, create_mcp_server


class FakeService:
    def __init__(self): self.calls=[]
    def doctor(self): self.calls.append("doctor"); return {"ok": True}
    def status(self, run_id=None): return {"run_id": run_id}
    def close(self): self.calls.append("close")
    def update_monitor_profile(self, monitor_id, profile):
        self.calls.append(("update_monitor_profile", monitor_id, profile))
        return {"monitor_id": monitor_id, "profile": profile}


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
                "export_report", "create_monitor", "monitor_validate", "run_monitor_once", "update_monitor_profile", "monitor_status", "pause_monitor", "resume_monitor", "review_list", "review_decide"}
    assert set(tools) == expected


def test_async_handler_keeps_direct_service_call():
    fake = FakeService()
    server = create_mcp_server(InvestigationMCPServer(".", service=fake))
    handler = getattr(server, "_tool_manager")._tools["doctor"].fn
    assert asyncio.run(handler()) == {"ok": True}
    assert fake.calls == ["doctor"]


def test_async_profile_update_forwards_exact_payload():
    fake = FakeService()
    server = create_mcp_server(InvestigationMCPServer(".", service=fake))
    handler = getattr(server, "_tool_manager")._tools["update_monitor_profile"].fn
    profile = {"company_id": "c", "rule_version": "r1", "scope": "public"}
    assert asyncio.run(handler("mon-1", profile)) == {"monitor_id": "mon-1", "profile": profile}
    assert fake.calls == [("update_monitor_profile", "mon-1", profile)]


def test_real_stdio_initialize_list_and_call(tmp_path: Path):
    """Exercise the actual SDK stdio client/server boundary with fake service."""
    script = tmp_path / "server.py"
    source = r'''
import sys
sys.path.insert(0, sys.argv[1])
from research_harness.investigation_mcp import InvestigationMCPServer, create_mcp_server
class F:
    def doctor(self): return {"ok": True, "mode": "synthetic"}
    def close(self): pass
create_mcp_server(InvestigationMCPServer(".", service=F())).run(transport="stdio")
'''
    script.write_text(source, encoding="utf-8")

    async def check():
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        params = StdioServerParameters(command=sys.executable, args=[str(script), str(Path(__file__).parents[1] / "src")])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
                names = {item.name for item in listed.tools}
                assert "doctor" in names and "review_decide" in names
                result = await session.call_tool("doctor", {})
                assert result.is_error is False
                assert '"ok": true' in str(result.content[0].text).lower()
    asyncio.run(check())
