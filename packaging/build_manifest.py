"""Record build inputs and optionally freeze the synthetic Golden Demo export."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import email
import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = ("src/research_harness", "frontend", "packaging", "deployment", "Dockerfile", "Dockerfile.research", "Dockerfile.demo", "compose.yaml", "compose.env.example", ".dockerignore", "pyproject.toml", "requirements")


def _build_input(relative: str) -> bool:
    return relative in {"Dockerfile", "Dockerfile.research", "Dockerfile.demo", "compose.yaml", "compose.env.example", ".dockerignore", "pyproject.toml"} or relative.startswith(("src/research_harness/", "frontend/", "packaging/", "deployment/", "requirements/"))


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _license(distribution: importlib.metadata.Distribution) -> str:
    metadata = distribution.metadata
    value = metadata.get("License-Expression")
    if value:
        return value
    classifiers = [item.removeprefix("License :: ").replace(" :: ", " / ") for item in metadata.get_all("Classifier", []) if item.startswith("License :: ")]
    if classifiers:
        return "; ".join(classifiers)
    raw = (metadata.get("License") or "").strip()
    return raw.splitlines()[0][:160] if raw else "license metadata unavailable"


def _tracked_state() -> dict:
    head = os.environ.get("RH_BUILD_HEAD")
    dirty_hashes: dict[str, str] = {}
    supplied = os.environ.get("RH_DIRTY_FILE_HASHES_JSON", "").strip()
    if supplied:
        try:
            values = json.loads(supplied)
            if not isinstance(values, dict) or any(not isinstance(key, str) or not _build_input(key.replace("\\", "/")) or not isinstance(value, str) or len(value) != 64 for key, value in values.items()):
                raise ValueError("dirty file hashes must be a JSON object of paths to SHA-256 strings")
            dirty_hashes.update(values)
        except json.JSONDecodeError as exc:
            raise ValueError("RH_DIRTY_FILE_HASHES_JSON must be valid JSON") from exc
    try:
        if not head or head == "unknown":
            head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
        status = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=all"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL)
        for row in status.splitlines():
            relative = row[3:].strip().strip('"')
            relative = relative.replace("\\", "/")
            if not _build_input(relative) or relative.endswith("/live-epo-runtime.json"):
                continue
            path = (ROOT / relative).resolve()
            try:
                path.relative_to(ROOT)
            except ValueError:
                continue
            if path.is_file():
                dirty_hashes[relative] = sha256(path.read_bytes())
        dirty_status = "provided_and_git_available" if supplied else "available"
    except (OSError, subprocess.CalledProcessError):
        head = head if head and head != "unknown" else "unknown"
        dirty_status = "provided_without_git_metadata" if supplied else "git_metadata_not_in_build_context"
    return {"git_head": head or "unknown", "dirty_file_hash_status": dirty_status, "dirty_file_sha256": dict(sorted(dirty_hashes.items()))}


def _source_hashes() -> dict[str, str]:
    values: dict[str, str] = {}
    for entry in SOURCE_ROOTS:
        path = ROOT / entry
        if path.is_file():
            values[entry] = sha256(path.read_bytes())
        elif path.is_dir():
            for item in path.rglob("*"):
                if item.is_file() and not any(part in {"__pycache__", "node_modules", ".venv", "venv"} for part in item.parts):
                    relative = item.relative_to(ROOT).as_posix()
                    if relative.endswith("/live-epo-runtime.json"):
                        continue
                    values[relative] = sha256(item.read_bytes())
    return dict(sorted(values.items()))


def _engine_requirements() -> tuple[list[dict], list[dict]]:
    locks, licenses = [], []
    requirements = ROOT / "requirements"
    if not requirements.is_dir():
        return locks, licenses
    for path in sorted(requirements.iterdir()):
        name = path.name.casefold()
        if not path.is_file() or not any(engine in name for engine in ("paperqa", "storm")):
            continue
        record = {"file": path.name, "sha256": sha256(path.read_bytes()), "installed_in_core_image": False}
        if "license" in name:
            licenses.append(record)
        elif "runtime" in name or "lock" in name:
            locks.append(record)
    return locks, licenses


def _image_engine_profile(profile: str | None) -> dict:
    if profile is None:
        return {"status": "not_selected_for_this_build"}
    import importlib.util

    helper_path = ROOT / "packaging" / "research_image_profile.py"
    spec = importlib.util.spec_from_file_location("rh_research_image_profile", helper_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("research image profile resolver is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    selected = module.resolve_profile(profile, ROOT / "requirements")
    return {"status": "selected", **selected}


def _installed_packages(allowed_names: set[str] | None = None) -> list[dict]:
    from pip._vendor.packaging.utils import canonicalize_name

    records = []
    for distribution in sorted(importlib.metadata.distributions(), key=lambda item: (item.metadata.get("Name") or "").casefold()):
        name = distribution.metadata.get("Name", "unknown")
        if allowed_names is not None and canonicalize_name(name) not in allowed_names:
            continue
        records.append({"name": name, "version": distribution.version, "license": _license(distribution)})
    return records


def _core_lock_names(path: Path) -> set[str]:
    from pip._vendor.packaging.requirements import Requirement
    from pip._vendor.packaging.utils import canonicalize_name

    names = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            requirement = Requirement(line)
            if requirement.marker is None or requirement.marker.evaluate():
                names.add(canonicalize_name(requirement.name))
    names.add("research-harness")
    return names


def _wheel_metadata(path: str | Path | None) -> dict | None:
    if not path:
        return None
    wheel = Path(path).resolve()
    if not wheel.is_file() or wheel.suffix.casefold() != ".whl":
        raise ValueError("--core-wheel must point to an existing wheel")
    import zipfile
    with zipfile.ZipFile(wheel) as archive:
        metadata_names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(metadata_names) != 1:
            raise ValueError("core wheel must contain exactly one .dist-info/METADATA")
        metadata = email.message_from_bytes(archive.read(metadata_names[0]))
    return {"file": wheel.name, "sha256": sha256(wheel.read_bytes()), "name": metadata.get("Name"), "version": metadata.get("Version")}


def build_demo_snapshot(directory: str | Path) -> dict:
    """Generate a frozen public snapshot by calling the canonical synthetic demo once."""
    sys.path.insert(0, str(ROOT / "src"))
    from research_harness.gui.golden_demo import GoldenDemoFacade

    output = Path(directory).resolve()
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="rh-demo-build-") as workspace:
        payload = GoldenDemoFacade(workspace).run()
    demo = payload.get("demo") if isinstance(payload, dict) else None
    result = demo.get("result") if isinstance(demo, dict) else None
    if not isinstance(result, dict) or result.get("synthetic") is not True:
        raise RuntimeError("Golden Demo output did not declare synthetic data")
    reports = demo.get("reports")
    expected = {"technical_report": "technical_report.md", "literature_review": "literature_review.md"}
    if not isinstance(reports, list):
        raise RuntimeError("Golden Demo did not export report files")
    safe_reports = []
    for report in reports:
        report_type = report.get("type") if isinstance(report, dict) else None
        filename = expected.get(report_type)
        content = report.get("content") if isinstance(report, dict) else None
        if filename is None or report.get("language") != "en" or not isinstance(content, str):
            continue
        (output / filename).write_bytes(content.encode("utf-8"))
        safe_reports.append({"type": report_type, "language": "en", "format": "markdown", "filename": filename})
    if {report["type"] for report in safe_reports} != set(expected):
        raise RuntimeError("Golden Demo did not export the expected English reports")
    demo["reports"] = safe_reports
    snapshot = {"schema_version": "1", "profile": "demo", "synthetic": True, "demo": demo}
    (output / "snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    files = {name: sha256((output / name).read_bytes()) for name in ("snapshot.json", *sorted(expected.values()))}
    demo_manifest = {"schema_version": "1", "profile": "demo", "synthetic_only": True, "files": files}
    (output / "manifest.json").write_text(json.dumps(demo_manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    return demo_manifest


def build_manifest(demo_files: dict | None = None, core_wheel: str | Path | None = None, research_engine_profile: str | None = None) -> dict:
    lock_path = ROOT / "requirements" / "core-lock.txt"
    core_names = _core_lock_names(lock_path) if lock_path.is_file() else None
    distributions = _installed_packages(core_names)
    engine_locks, engine_licenses = _engine_requirements()
    frontend = {path.relative_to(ROOT).as_posix(): sha256(path.read_bytes()) for path in sorted((ROOT / "frontend" / "dist").rglob("*")) if path.is_file()} if (ROOT / "frontend" / "dist").is_dir() else {}
    return {
        "schema_version": "1",
        **_tracked_state(),
        "source_file_sha256": _source_hashes(),
        "frontend_dist_sha256": frontend,
        "core_dependencies": {"lock_file": "requirements/core-lock.txt", "lock_sha256": sha256(lock_path.read_bytes()) if lock_path.is_file() else None, "installed_packages": distributions},
        "core_package_artifact": _wheel_metadata(core_wheel),
        "research_engine_locks": engine_locks,
        "research_engine_license_records": engine_licenses,
        "research_engine_image_profile": _image_engine_profile(research_engine_profile),
        "demo_files": (demo_files or {}).get("files", {}),
        "acceptance": {"configuration_tests": "not_recorded_by_build", "service_smoke": "not_recorded_by_build", "container_build": "pending_host_acceptance", "container_runtime": "pending_host_acceptance"},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--demo-dir")
    parser.add_argument("--core-wheel")
    parser.add_argument("--research-engine-profile", choices=("paperqa", "storm"))
    args = parser.parse_args()
    demo_files = build_demo_snapshot(args.demo_dir) if args.demo_dir else None
    manifest = build_manifest(demo_files, args.core_wheel, args.research_engine_profile)
    path = Path(args.manifest).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "built", "git_head": manifest["git_head"], "source_files": len(manifest["source_file_sha256"]), "frontend_files": len(manifest["frontend_dist_sha256"]), "engine_locks": len(manifest["research_engine_locks"]), "demo_files": len(manifest["demo_files"]), "artifact_path": str(path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
