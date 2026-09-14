import json
from pathlib import Path

from research_harness.investigation_cli import _json, _parser, _monitor_parser


def test_cli_parser_and_json_file(tmp_path: Path):
    value = {"status": "ready"}
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    assert _json(str(path)) == value
    assert _json(json.dumps({"long": "x" * 5000})) == {"long": "x" * 5000}
    args = _parser().parse_args(["--workspace", "w", "submit", "run", "task", "--result", "{}", "--task-version", "1"])
    assert args.command == "submit" and args.task_version == 1


def test_profile_update_parser():
    import argparse
    parser = argparse.ArgumentParser()
    _monitor_parser(parser)
    args = parser.parse_args(["--workspace", "w", "profile-update", "mon-1", "--profile", '{"company_id":"c","rule_version":"r1","scope":"public"}'])
    assert args.command == "profile-update" and args.monitor_id == "mon-1"


def test_monitor_profile_update_forwards_to_service(monkeypatch, capsys):
    class Service:
        def __init__(self, workspace): self.workspace = workspace
        def update_monitor_profile(self, monitor_id, profile):
            assert monitor_id == "mon-1"
            assert profile["company_id"] == "c"
            return {"monitor_id": monitor_id, "profile": profile}
        def close(self): pass
    import research_harness.investigation as module
    monkeypatch.setattr(module, "InvestigationService", Service)
    from research_harness.investigation_cli import main
    assert main(["monitor", "--workspace", "w", "profile-update", "mon-1", "--profile", '{"company_id":"c","rule_version":"r1","scope":"public"}']) == 0
    assert '"monitor_id": "mon-1"' in capsys.readouterr().out
