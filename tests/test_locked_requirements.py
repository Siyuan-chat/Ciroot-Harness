import importlib.util
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("locked_requirements", ROOT / "packaging" / "validate_locked_requirements.py")
locked = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(locked)


HASH_A = "--hash=sha256:" + "a" * 64
HASH_B = "--hash sha256:" + "b" * 64


def test_hash_pins_are_parsed_and_platform_markers_are_evaluated(tmp_path):
    lock = tmp_path / "runtime.txt"
    lock.write_text(
        f"core-helper==1.4 {HASH_A}\n"
        f"windows-helper==2.0; sys_platform == 'win32' {HASH_B}\n",
        encoding="utf-8",
    )
    windows = {"sys_platform": "win32", "python_version": "3.12", "platform_system": "Windows"}
    linux = {"sys_platform": "linux", "python_version": "3.12", "platform_system": "Linux"}
    assert locked.read_locked_pins(lock, windows) == {"core-helper": "1.4", "windows-helper": "2.0"}
    assert locked.read_locked_pins(lock, linux) == {"core-helper": "1.4"}


def test_hash_validator_rejects_unpinned_malformed_or_conflicting_requirements(tmp_path):
    lock = tmp_path / "bad.txt"
    lock.write_text("widget>=1.0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="exactly one"):
        locked.read_locked_pins(lock)
    lock.write_text("widget==1.0 --hash=sha256:bad\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid lock hash"):
        locked.read_locked_pins(lock)
    lock.write_text("widget==1.0\nwidget==2.0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="conflicting duplicate"):
        locked.read_locked_pins(lock)


def test_windows_installer_preserves_hash_lock_install_and_guards_runtime_config():
    script = (ROOT / "packaging" / "install_research_env.ps1").read_text(encoding="utf-8")
    assert "validate_locked_requirements.py" in script
    assert "--force-reinstall --no-deps $CoreWheel" in script
    assert "-r $LockFile" in script
    assert "Refusing to overwrite an existing runtime configuration" in script
    assert "without an explicit EnvironmentPath" in script
    assert "verify_installed_core.py" in script
    assert "worker could not be imported" in script


def test_core_wheel_verifier_matches_installed_module_bytes_and_detects_tampering(tmp_path):
    site = tmp_path / "site"
    package = site / "research_harness"
    (package / "engines").mkdir(parents=True)
    (package / "__init__.py").write_text("VERSION = 'fixture'\n", encoding="utf-8")
    (package / "engines" / "__init__.py").write_text("", encoding="utf-8")
    wheel = tmp_path / "research_harness-1.2.3-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("research_harness/__init__.py", (package / "__init__.py").read_bytes())
        archive.writestr("research_harness/engines/__init__.py", (package / "engines" / "__init__.py").read_bytes())
        archive.writestr("research_harness-1.2.3.dist-info/METADATA",
                         "Metadata-Version: 2.1\nName: research-harness\nVersion: 1.2.3\n\n")
    metadata = site / "research_harness-1.2.3.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text("Metadata-Version: 2.1\nName: research-harness\nVersion: 1.2.3\n\n", encoding="utf-8")
    verifier = ROOT / "packaging" / "verify_installed_core.py"
    environment = dict(os.environ, PYTHONPATH=str(site))
    wheel_hash = hashlib.sha256(wheel.read_bytes()).hexdigest()
    command = [sys.executable, str(verifier), str(wheel), wheel_hash]
    checked = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=30)
    assert checked.returncode == 0, checked.stderr
    report = json.loads(checked.stdout)
    assert report["version"] == "1.2.3" and report["verified_wheel_sha256"] == wheel_hash
    assert report["verified_module_count"] == 2

    (package / "__init__.py").write_text("VERSION = 'tampered'\n", encoding="utf-8")
    tampered = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=30)
    assert tampered.returncode != 0
    assert "differs from wheel" in tampered.stderr
