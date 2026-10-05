import hashlib
import importlib.util
import json
from pathlib import Path
import zipfile

import pytest
from fastapi.testclient import TestClient

from research_harness.gui import app as research_gui
from research_harness.gui import demo_app
from research_harness.gui.__main__ import resolve_server_settings


def _snapshot(directory):
    directory.mkdir(parents=True, exist_ok=True)
    demo = {
        "status": {"status": "completed"},
        "result": {"synthetic": True, "outcome": "partial"},
        "reports": [
            {"type": "technical_report", "language": "en", "format": "markdown", "filename": "technical_report.md"},
            {"type": "literature_review", "language": "en", "format": "markdown", "filename": "literature_review.md"},
        ],
    }
    snapshot = {"schema_version": "1", "profile": "demo", "synthetic": True, "demo": demo}
    files = {
        "snapshot.json": json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode(),
        "technical_report.md": b"# Synthetic technical report\nSynthetic only.\n",
        "literature_review.md": b"# Synthetic literature review\nSynthetic only.\n",
    }
    for name, content in files.items():
        (directory / name).write_bytes(content)
    manifest = {"schema_version": "1", "profile": "demo", "synthetic_only": True,
                "files": {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}}
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def test_listener_defaults_loopback_and_requires_explicit_allowlist_for_self_host():
    assert resolve_server_settings("127.0.0.1", None, "research") == ("127.0.0.1", ["127.0.0.1", "localhost", "[::1]"], "research")
    assert resolve_server_settings("localhost", "localhost,lab.example", "research")[1] == ["localhost", "lab.example"]
    assert resolve_server_settings("0.0.0.0", "localhost,127.0.0.1", "research")[0] == "0.0.0.0"
    with pytest.raises(ValueError, match="explicit --allowed-hosts"):
        resolve_server_settings("0.0.0.0", None, "research")
    with pytest.raises(ValueError, match="must also appear"):
        resolve_server_settings("192.0.2.10", "lab.example", "research")
    with pytest.raises(ValueError, match="profile"):
        resolve_server_settings("127.0.0.1", None, "unknown")


def test_research_profile_remains_mutable_only_when_selected_and_host_guard_applies(tmp_path):
    app = research_gui.create_app(tmp_path, token="test", allowed_hosts=["127.0.0.1"])
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/api/v1/overview").status_code == 200
        assert client.get("/api/v1/overview", headers={"host": "evil.example"}).status_code == 403
    with pytest.raises(ValueError, match="only supports profile='research'"):
        research_gui.create_app(tmp_path / "demo", profile="demo")


def test_research_workspace_survives_service_restart(tmp_path):
    examples = Path(__file__).parents[1] / "src" / "research_harness" / "examples" / "investigation"
    body = {name: json.loads((examples / f"synthetic-{name}.json").read_text(encoding="utf-8")) for name in ("spec", "runtime", "scenario")}
    app = research_gui.create_app(tmp_path, token="first", allowed_hosts=["127.0.0.1"])
    with TestClient(app, base_url="http://127.0.0.1") as client:
        created = client.post("/api/v1/runs", json=body, headers={"x-session-token": "first", "idempotency-key": "persistent-demo"})
        assert created.status_code == 200, created.text
        run_id = created.json()["run_id"]
    reopened = research_gui.create_app(tmp_path, token="second", allowed_hosts=["127.0.0.1"])
    with TestClient(reopened, base_url="http://127.0.0.1") as client:
        assert client.get(f"/api/v1/runs/{run_id}").status_code == 200
        assert client.get("/api/v1/runs").json()["items"][0]["run_id"] == run_id


def test_demo_projection_browses_reports_downloads_and_rejects_all_other_api_actions(tmp_path):
    snapshot_dir = tmp_path / "snapshot"
    _snapshot(snapshot_dir)
    app = demo_app.create_demo_app(snapshot_dir, allowed_hosts=["127.0.0.1"])
    assert not hasattr(demo_app, "InvestigationService")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        page = client.get("/")
        assert page.status_code == 200 and "Synthetic demo" in page.text and "/api/v1/demo/download/" in page.text
        projection = client.get("/api/v1/demo")
        assert projection.status_code == 200 and projection.json()["demo"]["result"]["synthetic"] is True
        report = client.get("/api/v1/demo/reports/technical_report.md")
        assert report.status_code == 200 and "Synthetic only" in report.text
        download = client.get("/api/v1/demo/download/technical_report.md")
        assert download.status_code == 200 and download.content == report.content
        assert "attachment" in download.headers["content-disposition"]
        assert client.get("/api/v1/demo/reports/../../etc/passwd").status_code in {403, 404}
        for method, path in (("post", "/api/v1/runs"), ("post", "/api/v1/model-credentials/openai"),
                             ("put", "/api/v1/library/import"), ("delete", "/api/v1/source-credentials/key"),
                             ("get", "/api/v1/runs"), ("get", "/api/v1/mcp-setup")):
            response = getattr(client, method)(path, json={}) if method in {"post", "put"} else getattr(client, method)(path)
            assert response.status_code == 403, (method, path, response.status_code)


def test_demo_detects_snapshot_and_post_start_file_tampering(tmp_path):
    snapshot_dir = tmp_path / "snapshot"
    manifest = _snapshot(snapshot_dir)
    (snapshot_dir / "literature_review.md").write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256"):
        demo_app.create_demo_app(snapshot_dir)

    _snapshot(snapshot_dir)
    app = demo_app.create_demo_app(snapshot_dir)
    (snapshot_dir / "technical_report.md").write_text("changed after startup", encoding="utf-8")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/api/v1/demo/download/technical_report.md").status_code == 503


def test_build_time_snapshot_uses_core_golden_demo_and_is_persistent(tmp_path):
    script = Path(__file__).parents[1] / "packaging" / "build_manifest.py"
    spec = importlib.util.spec_from_file_location("rh_build_manifest", script)
    build_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_module)

    target = tmp_path / "frozen-demo"
    manifest = build_module.build_demo_snapshot(target)
    assert set(manifest["files"]) == {"snapshot.json", "technical_report.md", "literature_review.md"}
    first_app = demo_app.create_demo_app(target)
    with TestClient(first_app, base_url="http://127.0.0.1") as client:
        before = client.get("/api/v1/demo").json()
        assert before["demo"]["result"]["synthetic"] is True
        assert client.get("/api/v1/demo/download/literature_review.md").status_code == 200
    reopened_app = demo_app.create_demo_app(target)
    with TestClient(reopened_app, base_url="http://127.0.0.1") as client:
        after = client.get("/api/v1/demo").json()
        assert after == before
        assert client.get("/api/v1/demo/reports/literature_review.md").status_code == 200


def test_build_manifest_fingerprints_only_build_inputs_and_separates_engine_records():
    script = Path(__file__).parents[1] / "packaging" / "build_manifest.py"
    spec = importlib.util.spec_from_file_location("rh_build_manifest_metadata", script)
    build_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_module)
    manifest = build_module.build_manifest({"files": {"snapshot.json": "test-hash"}})
    assert manifest["git_head"] and manifest["dirty_file_hash_status"]
    assert manifest["core_dependencies"]["lock_sha256"]
    assert {item["file"] for item in manifest["research_engine_locks"]} == {"paperqa-runtime.txt", "storm-runtime.txt", "storm-runtime-linux.txt"}
    assert {item["file"] for item in manifest["research_engine_license_records"]} == {"paperqa-licenses.txt", "storm-licenses.txt", "storm-licenses-linux.txt"}
    assert not any(path.endswith("live-epo-runtime.json") for path in manifest["source_file_sha256"])
    assert all(path.startswith(("src/research_harness/", "frontend/", "packaging/", "deployment/", "requirements/")) or path in {"Dockerfile", "Dockerfile.research", "Dockerfile.demo", "compose.yaml", "compose.env.example", ".dockerignore", "pyproject.toml"} for path in manifest["dirty_file_sha256"])
    assert manifest["acceptance"]["container_runtime"] == "pending_host_acceptance"


def test_core_service_lock_excludes_optional_research_and_desktop_engines():
    lock = (Path(__file__).parents[1] / "requirements" / "core-lock.txt").read_text(encoding="utf-8")
    packages = {line.split("==", 1)[0].casefold() for line in lock.splitlines() if "==" in line and not line.startswith("#")}
    assert {"fastapi", "uvicorn", "langgraph", "jsonschema"} <= packages
    assert not ({"pywebview", "paper-qa", "torch", "networkx", "scikit-learn"} & packages)


def test_build_manifest_records_core_wheel_identity_and_hash(tmp_path):
    script = Path(__file__).parents[1] / "packaging" / "build_manifest.py"
    spec = importlib.util.spec_from_file_location("rh_build_manifest_wheel", script)
    build_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_module)
    wheel = tmp_path / "research_harness-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("research_harness-0.1.0.dist-info/METADATA", "Metadata-Version: 2.1\nName: research-harness\nVersion: 0.1.0\n\n")
    record = build_module.build_manifest(core_wheel=wheel)["core_package_artifact"]
    assert record["name"] == "research-harness" and record["version"] == "0.1.0"
    assert record["sha256"] == hashlib.sha256(wheel.read_bytes()).hexdigest()


def test_compose_separates_core_paperqa_and_synthetic_demo_images():
    import yaml

    root = Path(__file__).parents[1]
    compose = yaml.safe_load((root / "compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]
    assert services["research"]["build"]["dockerfile"] == "Dockerfile"
    assert services["research"]["volumes"]
    assert services["research_paperqa"]["profiles"] == ["paperqa"]
    assert services["research_paperqa"]["build"]["dockerfile"] == "Dockerfile.research"
    assert services["research_paperqa"]["volumes"] != services["research"]["volumes"]
    assert services["research_paperqa"]["build"]["args"]["RH_ENGINE_PROFILE"] == "paperqa"
    storm = services["research_storm"]
    assert storm["profiles"] == ["storm"] and storm["build"]["dockerfile"] == "Dockerfile.research"
    assert storm["build"]["args"]["RH_ENGINE_PROFILE"] == "storm"
    assert storm["volumes"] != services["research_paperqa"]["volumes"]
    assert storm["environment"]["RH_RESEARCH_ENGINE_NAME"] == "storm"
    assert storm["environment"]["RH_RESEARCH_ENGINE_PYTHON_EXECUTABLE"] == "/opt/research-engine/bin/python"
    assert storm["ports"] == ["127.0.0.1:${RH_STORM_PORT:-8768}:8765"]
    assert services["demo"]["build"]["dockerfile"] == "Dockerfile.demo"
    assert services["demo"]["read_only"] is True and "demo_internal" in services["demo"]["networks"]
    research_image = (root / "Dockerfile.research").read_text(encoding="utf-8")
    demo_image = (root / "Dockerfile.demo").read_text(encoding="utf-8")
    assert "research_image_profile.py \"$RH_ENGINE_PROFILE\"" in research_image
    assert "--require-hashes" in (root / "packaging" / "research_image_profile.py").read_text(encoding="utf-8")
    assert "--research-engine-profile \"$RH_ENGINE_PROFILE\"" in research_image
    assert "RH_RESEARCH_ENGINE_NAME=${RH_ENGINE_PROFILE}" in research_image
    assert "RH_RESEARCH_ENGINE_PYTHON_EXECUTABLE=/opt/research-engine/bin/python" in research_image
    assert "paperqa-runtime.txt" not in demo_image and "RH_PROFILE=demo" in demo_image
    assert "requirements/core-lock.txt" in (root / "Dockerfile").read_text(encoding="utf-8")
    assert "live-epo-runtime.json" in (root / ".dockerignore").read_text(encoding="utf-8")


def test_compose_env_example_is_nonsecret_loopback_default_and_manifest_input():
    root = Path(__file__).parents[1]
    example = (root / "compose.env.example").read_text(encoding="utf-8-sig")
    assert "RH_ALLOWED_HOSTS=localhost,127.0.0.1" in example
    assert "RH_PORT=8765" in example and "RH_DEMO_PORT=8766" in example and "RH_PAPERQA_PORT=8767" in example and "RH_STORM_PORT=8768" in example
    assert "SECRET=" not in example and "API_KEY=" not in example
    spec = importlib.util.spec_from_file_location("rh_build_manifest_env_example", root / "packaging" / "build_manifest.py")
    build_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_module)
    assert "compose.env.example" in build_module.SOURCE_ROOTS
    assert build_module._build_input("compose.env.example")


def test_optional_engine_locks_are_exact_and_platform_markers_select_windows_only_packages():
    from pip._vendor.packaging.markers import default_environment
    from pip._vendor.packaging.requirements import Requirement
    from pip._vendor.packaging.utils import canonicalize_name

    root = Path(__file__).parents[1]

    def active_pins(platform, system):
        environment = default_environment()
        environment.update(sys_platform=platform, platform_system=system)
        result = {}
        locks = [root / "requirements" / "core-lock.txt", root / "requirements" / "paperqa-runtime.txt"]
        for lock in locks:
            logical_lines = []
            pending = ""
            for raw in lock.read_text(encoding="utf-8").splitlines():
                part = raw.strip()
                if not part or part.startswith("#"):
                    continue
                pending += (" " if pending else "") + (part[:-1].rstrip() if part.endswith("\\") else part)
                if part.endswith("\\"):
                    continue
                logical_lines.append(pending.strip())
                pending = ""
            if pending:
                logical_lines.append(pending.strip())
            for line in logical_lines:
                if not line or line.startswith("--"):
                    continue
                requirement = Requirement(line.split(" --hash=", 1)[0])
                if requirement.marker is not None and not requirement.marker.evaluate(environment):
                    continue
                specs = list(requirement.specifier)
                assert requirement.url is not None or (len(specs) == 1 and specs[0].operator == "==" and not specs[0].version.endswith(".*")), line
                name = canonicalize_name(requirement.name)
                pin = "url=" + requirement.url if requirement.url else specs[0].version
                assert name not in result or result[name] == pin, (name, result.get(name), pin)
                result[name] = pin
        return result

    windows = active_pins("win32", "Windows")
    linux = active_pins("linux", "Linux")
    assert "pywin32" in windows and "pywin32" not in linux
    for platform, filename in (("win32", "storm-runtime.txt"), ("linux", "storm-runtime-linux.txt")):
        environment = default_environment()
        environment.update(sys_platform=platform, platform_system="Windows" if platform == "win32" else "Linux")
        lock = root / "requirements" / filename
        entries = []
        pending = ""
        for raw in lock.read_text(encoding="utf-8").splitlines():
            part = raw.strip()
            if not part or part.startswith("#"):
                continue
            pending += (" " if pending else "") + (part[:-1].rstrip() if part.endswith("\\") else part)
            if part.endswith("\\"):
                continue
            entries.append(pending.strip())
            pending = ""
        if pending:
            entries.append(pending.strip())
        requirements = [Requirement(line.split(" --hash=", 1)[0]) for line in entries if line and not line.startswith("--")]
        active = {canonicalize_name(req.name): req for req in requirements if req.marker is None or req.marker.evaluate(environment)}
        assert "knowledge-storm" in active
        if platform == "win32":
            assert "pywin32" in active
        else:
            assert "pywin32" not in active
            assert str(next(iter(active["torch"].specifier)).version) == "2.14.1+cpu"


def test_research_image_profile_installs_exactly_one_target_lock_and_manifest_records_pin(monkeypatch):
    root = Path(__file__).parents[1]
    script = root / "packaging" / "research_image_profile.py"
    spec = importlib.util.spec_from_file_location("rh_research_image_profile", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    paperqa = module.resolve_profile("paperqa", root / "requirements")
    storm = module.resolve_profile("storm", root / "requirements")
    assert paperqa["lock_file"] == "paperqa-runtime.txt" and paperqa["package"] == "paper-qa"
    assert storm["lock_file"] == "storm-runtime-linux.txt" and storm["package"] == "knowledge-storm"
    assert paperqa["lock_sha256"] != storm["lock_sha256"]
    assert storm["version"] == "1.1.1" and storm["worker_module"].endswith("storm_worker")

    calls = []
    monkeypatch.setattr(module.subprocess, "run", lambda command, check: calls.append(command))
    module.install_profile("storm", "/opt/research-engine/bin/python", root / "requirements")
    assert calls[0][0:5] == ["/opt/research-engine/bin/python", "-m", "pip", "install", "--disable-pip-version-check"]
    assert "--require-hashes" in calls[0] and calls[0][-1].endswith("storm-runtime-linux.txt")
    assert calls[0][calls[0].index("--index-url") + 1] == "https://pypi.org/simple"
    assert calls[0][calls[0].index("--extra-index-url") + 1] == "https://download.pytorch.org/whl/cpu"
    assert calls[1][1:] == ["-m", "pip", "check"]
    assert calls[2][-1].endswith("import research_harness.engines.storm_worker; print('selected storm worker import: PASS')")

    monkeypatch.undo()
    manifest_script = root / "packaging" / "build_manifest.py"
    manifest_spec = importlib.util.spec_from_file_location("rh_build_manifest_storm_profile", manifest_script)
    manifest_module = importlib.util.module_from_spec(manifest_spec)
    manifest_spec.loader.exec_module(manifest_module)
    manifest = manifest_module.build_manifest(research_engine_profile="storm")
    assert manifest["research_engine_image_profile"]["profile"] == "storm"
    assert manifest["research_engine_image_profile"]["version"] == "1.1.1"
    assert manifest["research_engine_image_profile"]["lock_sha256"] == storm["lock_sha256"]
