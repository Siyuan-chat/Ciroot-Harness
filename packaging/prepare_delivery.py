"""Assemble a hash-verified Windows portable delivery candidate."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MACHINE_CONFIGS = ("library-workspace.txt", "rag-model-cache.txt", "mcp-python.txt")
GUIDES = ("INTEGRATION_GUIDE.zh-CN.md", "INTEGRATION_GUIDE.en.md", "INTEGRATION_GUIDE.ja.md")
GUIDE_SUPPORT = ("INTEGRATION_STAGE.md", "INTEGRATION_ACTIVATION.md", "INTEGRATION_EVALUATION.md", "SOURCE_API_MATRIX.md")
DEPLOYMENT_CONFIGS = ("Dockerfile", "Dockerfile.research", "Dockerfile.demo", "compose.yaml", "compose.env.example", ".dockerignore")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _absolute_existing(value: str | Path, *, directory: bool = False) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f"path must be absolute: {path}")
    resolved = path.resolve(strict=True)
    if directory != resolved.is_dir():
        expected = "directory" if directory else "file"
        raise ValueError(f"expected existing {expected}: {resolved}")
    return resolved


def output_location(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f"output root must be absolute: {path}")
    resolved = path.resolve(strict=False)
    if resolved.exists():
        raise FileExistsError(f"refusing to replace an existing delivery directory: {resolved}")
    return resolved


def copy_verified(source: Path, destination: Path) -> dict[str, str]:
    source = _absolute_existing(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    source_hash, copied_hash = sha256(source), sha256(destination)
    if source_hash != copied_hash:
        raise IOError(f"copied artifact hash mismatch: {source} -> {destination}")
    return {"source": str(source), "sha256": copied_hash}


def _tree_inventory(root: Path) -> dict[str, str]:
    records = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"portable build must not contain symlinks: {path}")
        if path.is_file():
            records[path.relative_to(root).as_posix()] = sha256(path)
    return records


def _copy_requirements(stage: Path) -> dict[str, dict[str, str]]:
    source_dir = ROOT / "requirements"
    selected = sorted(path for path in source_dir.iterdir() if path.is_file())
    if not any(path.name == "core-lock.txt" for path in selected):
        raise FileNotFoundError("requirements/core-lock.txt is required")
    records = {}
    target_dir = stage / "optional-runtime" / "requirements"
    for source in selected:
        records[source.name] = copy_verified(source, target_dir / source.name)
    return records


def prepare(portable_source: Path, output_root: Path, core_wheel: Path, python: Path, build_environment: Path) -> Path:
    portable_source = _absolute_existing(portable_source, directory=True)
    core_wheel = _absolute_existing(core_wheel)
    python = _absolute_existing(python)
    build_environment = _absolute_existing(build_environment)
    unresolved_output = Path(output_root)
    if not unresolved_output.is_absolute():
        raise ValueError(f"output root must be absolute: {unresolved_output}")
    unresolved_output = unresolved_output.resolve(strict=False)
    if (unresolved_output == portable_source or unresolved_output in portable_source.parents or
            portable_source in unresolved_output.parents):
        raise ValueError("output root and portable build source cannot contain one another")
    output_root = output_location(unresolved_output)
    for name in MACHINE_CONFIGS:
        if (portable_source / name).exists():
            raise ValueError(f"portable build contains machine-local configuration: {name}")
    if core_wheel.suffix.casefold() != ".whl":
        raise ValueError("CoreWheel must be a wheel file")
    build_record = json.loads(build_environment.read_text(encoding="utf-8-sig"))
    if (not isinstance(build_record, dict) or build_record.get("schema_version") != "1" or
            not build_record.get("python_executable") or not build_record.get("pyinstaller_version") or
            not isinstance(build_record.get("installed_distributions"), list) or not build_record.get("scope")):
        raise ValueError("build environment record is missing required fields")
    if not (ROOT / "docs" / GUIDES[0]).is_file():
        raise FileNotFoundError("trilingual integration guides are not available")
    if not all((ROOT / "docs" / name).is_file() for name in GUIDES):
        raise FileNotFoundError("all three integration guides are required")

    output_root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_root.name}.staging-", dir=output_root.parent))
    try:
        portable_dest = staging / "portable" / "ResearchHarnessGUI"
        shutil.copytree(portable_source, portable_dest)
        source_files = _tree_inventory(portable_source)
        copied_files = _tree_inventory(portable_dest)
        if copied_files != source_files:
            raise IOError("portable tree copy has a different file list or SHA-256 from its source")
        portable_files = copied_files
        if not any(name.casefold().endswith("researchharnessgui.exe") for name in portable_files):
            raise FileNotFoundError("portable source does not contain ResearchHarnessGUI.exe")

        wheel_record = copy_verified(core_wheel, staging / "optional-runtime" / "wheels" / core_wheel.name)
        build_environment_record = copy_verified(build_environment,
                                                 staging / "build-metadata" / "windows-build-environment.json")
        installer_record = copy_verified(ROOT / "packaging" / "install_research_env.ps1",
                                         staging / "optional-runtime" / "install_research_env.ps1")
        lock_validator_record = copy_verified(ROOT / "packaging" / "validate_locked_requirements.py",
                                               staging / "optional-runtime" / "validate_locked_requirements.py")
        core_verifier_record = copy_verified(ROOT / "packaging" / "verify_installed_core.py",
                                              staging / "optional-runtime" / "verify_installed_core.py")
        requirements = _copy_requirements(staging)
        guide_records = {}
        for name in (*GUIDES, *GUIDE_SUPPORT):
            guide_records[name] = copy_verified(ROOT / "docs" / name, staging / "guides" / name)
        deployment_records = {}
        for name in DEPLOYMENT_CONFIGS:
            deployment_records[name] = copy_verified(ROOT / name, staging / "deployment-configs" / name)

        manifest_path = staging / "delivery-manifest.json"
        command = [str(python), str(ROOT / "packaging" / "build_manifest.py"),
                   "--manifest", str(manifest_path), "--core-wheel", str(core_wheel)]
        result = subprocess.run(command, cwd=ROOT, check=False, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(f"build_manifest.py failed ({result.returncode}): {result.stderr.strip()}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        package_record = manifest.get("core_package_artifact")
        if not isinstance(package_record, dict) or package_record.get("sha256") != wheel_record["sha256"]:
            raise RuntimeError("generated manifest does not match the copied core wheel")
        manifest["windows_delivery"] = {
            "profile": "portable-desktop-with-optional-research-runtime",
            "portable_file_sha256": portable_files,
            "core_wheel": {"file": core_wheel.name, **wheel_record},
            "windows_build_environment": {"file": "build-metadata/windows-build-environment.json", **build_environment_record,
                                          "scope": build_record["scope"]},
            "optional_installer": {"file": "install_research_env.ps1", **installer_record,
                                   "lock_validator": lock_validator_record, "core_verifier": core_verifier_record},
            "requirements": requirements,
            "guides": guide_records,
            "deployment_configs": deployment_records,
            "deployment_build_context": "These configuration files require the complete matching source repository as Docker build context; this bundle is not a standalone build context.",
            "engine_runtime_location": "separate user-selected venv; never bundled into the EXE",
            "research_calls_enabled_by_delivery": False,
            "native_webview2_acceptance": "pending_host_acceptance",
            "portable_config_overwrite": "not_performed",
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        output_root.parent.mkdir(parents=True, exist_ok=True)
        staging.replace(output_root)
        return output_root
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--portable-source", required=True, help="absolute PyInstaller onedir directory")
    parser.add_argument("--output-root", required=True, help="new absolute delivery directory; never overwritten")
    parser.add_argument("--core-wheel", required=True, help="absolute local core wheel")
    parser.add_argument("--build-environment", required=True, help="absolute build-environment.json from build_windows.ps1")
    parser.add_argument("--python", default=sys.executable, help="absolute Python that can run build_manifest.py")
    args = parser.parse_args()
    result = prepare(Path(args.portable_source), Path(args.output_root), Path(args.core_wheel), Path(args.python), Path(args.build_environment))
    print(json.dumps({"status": "prepared_candidate", "path": str(result),
                      "manifest": str(result / "delivery-manifest.json"),
                      "native_webview2_acceptance": "pending_host_acceptance"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
