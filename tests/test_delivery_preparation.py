import hashlib
import importlib.util
import json
import zipfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("prepare_delivery", ROOT / "packaging" / "prepare_delivery.py")
prepare_delivery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prepare_delivery)


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _wheel(path):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("research_harness-0.1.0.dist-info/METADATA",
                         "Metadata-Version: 2.1\nName: research-harness\nVersion: 0.1.0\n\n")


def _build_environment(path):
    path.write_text(json.dumps({
        "schema_version": "1", "python_executable": "C:/Python/python.exe",
        "python_version": "3.12.0", "pyinstaller_version": "6.0.0", "platform": "Windows",
        "installed_distributions": [{"name": "pyinstaller", "version": "6.0.0", "license": "GPL-2.0-or-later"}],
        "scope": "build-environment inventory only; not proof every package is bundled",
    }), encoding="utf-8")
    return path


def test_delivery_requires_new_absolute_output_and_rejects_existing(tmp_path):
    with pytest.raises(ValueError, match="absolute"):
        prepare_delivery.output_location("relative-output")
    existing = tmp_path / "already-there"
    existing.mkdir()
    with pytest.raises(FileExistsError):
        prepare_delivery.output_location(existing)


def test_windows_build_isolated_output_and_excludes_optional_engine_libraries():
    script = (ROOT / "packaging" / "build_windows.ps1").read_text(encoding="utf-8")
    assert "[Parameter(Mandatory = $true)][string]$OutputRoot" in script
    assert "OutputRoot already exists" in script
    assert "--exclude-module paperqa" in script
    assert "--exclude-module knowledge_storm" in script
    assert "--exclude-module dspy" in script
    assert "--exclude-module torch" in script
    assert "Remove-Item" not in script


def test_prepare_delivery_hashes_copied_package_wheel_locks_and_guides(tmp_path):
    source = tmp_path / "fresh-portable"
    source.mkdir()
    exe = source / "ResearchHarnessGUI.exe"
    exe.write_bytes(b"synthetic executable placeholder")
    wheel = tmp_path / "research_harness-0.1.0-py3-none-any.whl"
    _wheel(wheel)
    build_environment = _build_environment(tmp_path / "build-environment.json")
    output = tmp_path / "delivery"

    result = prepare_delivery.prepare(source, output, wheel, Path(__import__("sys").executable), build_environment)

    assert result == output.resolve()
    copied_exe = output / "portable" / "ResearchHarnessGUI" / exe.name
    copied_wheel = output / "optional-runtime" / "wheels" / wheel.name
    copied_build_environment = output / "build-metadata" / "windows-build-environment.json"
    assert _digest(copied_exe) == _digest(exe)
    assert _digest(copied_wheel) == _digest(wheel)
    assert _digest(copied_build_environment) == _digest(build_environment)
    for filename in ("core-lock.txt", "paperqa-runtime.txt", "paperqa-licenses.txt", "patent-analysis-lock.txt", "patent-analysis.txt"):
        assert (output / "optional-runtime" / "requirements" / filename).is_file()
    for filename in prepare_delivery.GUIDES:
        assert (output / "guides" / filename).is_file()
    for filename in prepare_delivery.GUIDE_SUPPORT:
        source_guide = ROOT / "docs" / filename
        copied_guide = output / "guides" / filename
        assert _digest(copied_guide) == _digest(source_guide)
    for filename in prepare_delivery.DEPLOYMENT_CONFIGS:
        source_config = ROOT / filename
        copied_config = output / "deployment-configs" / filename
        assert _digest(copied_config) == _digest(source_config)
    manifest = json.loads((output / "delivery-manifest.json").read_text(encoding="utf-8"))
    assert manifest["core_package_artifact"]["sha256"] == _digest(wheel)
    assert manifest["windows_delivery"]["native_webview2_acceptance"] == "pending_host_acceptance"
    assert manifest["windows_delivery"]["research_calls_enabled_by_delivery"] is False
    assert "complete matching source repository" in manifest["windows_delivery"]["deployment_build_context"]
    assert manifest["windows_delivery"]["windows_build_environment"]["sha256"] == _digest(build_environment)
    assert manifest["windows_delivery"]["portable_file_sha256"][exe.name] == _digest(exe)


def test_prepare_delivery_never_reuses_machine_local_config(tmp_path):
    source = tmp_path / "portable"
    source.mkdir()
    (source / "ResearchHarnessGUI.exe").write_bytes(b"placeholder")
    (source / "library-workspace.txt").write_text("user path", encoding="utf-8")
    wheel = tmp_path / "core.whl"
    _wheel(wheel)
    build_environment = _build_environment(tmp_path / "build-environment.json")
    with pytest.raises(ValueError, match="machine-local"):
        prepare_delivery.prepare(source, tmp_path / "delivery", wheel, Path(__import__("sys").executable), build_environment)
    assert not (tmp_path / "delivery").exists()


def test_prepare_rejects_both_ancestor_directions_before_creating_staging(tmp_path):
    wheel = tmp_path / "core.whl"
    _wheel(wheel)
    build_environment = _build_environment(tmp_path / "build-environment.json")
    python = Path(__import__("sys").executable)

    source = tmp_path / "source"
    source.mkdir()
    (source / "ResearchHarnessGUI.exe").write_bytes(b"placeholder")
    nested_output = source / "delivery"
    before = set(source.iterdir())
    with pytest.raises(ValueError, match="contain one another"):
        prepare_delivery.prepare(source, nested_output, wheel, python, build_environment)
    assert set(source.iterdir()) == before
    assert not nested_output.exists()

    outer = tmp_path / "outer"
    inner_source = outer / "source"
    inner_source.mkdir(parents=True)
    (inner_source / "ResearchHarnessGUI.exe").write_bytes(b"placeholder")
    before = set(outer.iterdir())
    with pytest.raises(ValueError, match="contain one another"):
        prepare_delivery.prepare(inner_source, outer, wheel, python, build_environment)
    assert set(outer.iterdir()) == before
    assert not list(tmp_path.glob(".outer.staging-*"))


def test_prepare_detects_corrupted_copy_and_preserves_existing_user_directory(tmp_path, monkeypatch):
    source = tmp_path / "portable"
    source.mkdir()
    (source / "ResearchHarnessGUI.exe").write_bytes(b"original")
    wheel = tmp_path / "core.whl"
    _wheel(wheel)
    build_environment = _build_environment(tmp_path / "build-environment.json")
    original_copytree = prepare_delivery.shutil.copytree

    def corrupt_copytree(src, dst, *args, **kwargs):
        copied = original_copytree(src, dst, *args, **kwargs)
        (Path(dst) / "ResearchHarnessGUI.exe").write_bytes(b"modified")
        return copied

    monkeypatch.setattr(prepare_delivery.shutil, "copytree", corrupt_copytree)
    output = tmp_path / "delivery"
    with pytest.raises(IOError, match="different file list or SHA-256"):
        prepare_delivery.prepare(source, output, wheel, Path(__import__("sys").executable), build_environment)
    assert not output.exists()
    assert not list(tmp_path.glob(".delivery.staging-*"))

    existing = tmp_path / "existing-delivery"
    existing.mkdir()
    sentinel = existing / "do-not-overwrite.txt"
    sentinel.write_text("user content", encoding="utf-8")
    with pytest.raises(FileExistsError):
        prepare_delivery.prepare(source, existing, wheel, Path(__import__("sys").executable), build_environment)
    assert sentinel.read_text(encoding="utf-8") == "user content"
