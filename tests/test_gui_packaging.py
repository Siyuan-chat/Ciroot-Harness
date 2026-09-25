"""Static bundle checks for resources opened at runtime by the GUI."""
import json
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_windows_bundle_includes_scripted_fixture_at_resource_lookup_path():
    build_script = (ROOT / "packaging/build_windows.ps1").read_text(encoding="utf-8")
    loader = (ROOT / "src/research_harness/gui/app.py").read_text(encoding="utf-8")
    source = ROOT / "src/research_harness/examples/investigation"

    assert '--add-data "$root\\src\\research_harness\\examples\\investigation;research_harness\\examples\\investigation"' in build_script
    assert 'resources.files("research_harness").joinpath("examples", "investigation")' in loader
    for name in ("synthetic-spec.json", "synthetic-runtime.json", "synthetic-scenario.json"):
        assert json.loads((source / name).read_text(encoding="utf-8"))


def test_frontend_bundle_keeps_the_synthetic_execution_scenario():
    build_script = (ROOT / "packaging/build_windows.ps1").read_text(encoding="utf-8")
    frontend_dist = ROOT / "frontend/dist"
    assert '--add-data "$root\\frontend\\dist;frontend\\dist"' in build_script
    assert json.loads((frontend_dist / "synthetic-scenario.json").read_text(encoding="utf-8"))
