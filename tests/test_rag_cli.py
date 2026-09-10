import json
import os
import subprocess
import sys


def test_rag_cli_emits_utf8_json_for_chinese_query(tmp_path):
    env = {**os.environ, "PYTHONPATH": os.path.abspath("src")}
    env.pop("PYTHONIOENCODING", None)
    env.pop("PYTHONUTF8", None)
    command = [sys.executable, "-m", "research_harness.rag", "--workspace", str(tmp_path / "library"), "search", "哪些交联方法可以降低膜溶胀？"]
    result = subprocess.run(command, env=env, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["query"] == "哪些交联方法可以降低膜溶胀？"
    assert payload["items"] == []
