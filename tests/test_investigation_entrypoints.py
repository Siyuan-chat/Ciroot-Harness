import json
from pathlib import Path

from research_harness.investigation_cli import _json, _parser


def test_cli_parser_and_json_file(tmp_path: Path):
    value = {"status": "ready"}
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    assert _json(str(path)) == value
    assert _json(json.dumps({"long": "x" * 5000})) == {"long": "x" * 5000}
    args = _parser().parse_args(["--workspace", "w", "submit", "run", "task", "--result", "{}", "--task-version", "1"])
    assert args.command == "submit" and args.task_version == 1
