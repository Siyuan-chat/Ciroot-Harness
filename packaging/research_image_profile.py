"""Resolve and install one isolated optional engine for the research image."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


PROFILES = {
    "paperqa": {
        "lock": "paperqa-runtime.txt",
        "package": "paper-qa",
        "worker": "research_harness.engines.paperqa_worker",
    },
    "storm": {
        "lock": "storm-runtime-linux.txt",
        "package": "knowledge-storm",
        "worker": "research_harness.engines.storm_worker",
    },
}


def resolve_profile(profile: str, requirements_root: str | Path) -> dict:
    """Return the exact selected lock/worker and its pinned engine version."""
    from pip._vendor.packaging.requirements import Requirement
    from pip._vendor.packaging.utils import canonicalize_name

    if profile not in PROFILES:
        raise ValueError("engine profile must be 'paperqa' or 'storm'")
    requirements = Path(requirements_root).resolve()
    details = PROFILES[profile]
    lock = requirements / details["lock"]
    if not lock.is_file():
        raise FileNotFoundError(f"selected engine lock is missing: {lock.name}")
    target = canonicalize_name(details["package"])
    versions = set()
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
        if not line or line.startswith("#") or line.startswith("--"):
            continue
        # pip hash options follow a valid PEP 508 requirement in the lock.
        requirement_text = line.split(" --hash=", 1)[0]
        requirement = Requirement(requirement_text)
        if requirement.marker is not None and not requirement.marker.evaluate():
            continue
        if canonicalize_name(requirement.name) == target:
            specs = list(requirement.specifier)
            if len(specs) != 1 or specs[0].operator != "==" or specs[0].version.endswith(".*"):
                raise ValueError(f"engine package is not exactly pinned in {lock.name}")
            versions.add(specs[0].version)
    if len(versions) != 1:
        raise ValueError(f"expected one active {details['package']} pin in {lock.name}")
    return {
        "profile": profile,
        "lock_file": details["lock"],
        "lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
        "package": details["package"],
        "version": next(iter(versions)),
        "worker_module": details["worker"],
        "python_executable": "/opt/research-engine/bin/python",
    }


def install_profile(profile: str, python: str, requirements_root: str | Path) -> dict:
    selected = resolve_profile(profile, requirements_root)
    lock = Path(requirements_root).resolve() / selected["lock_file"]
    logical_requirements = []
    pending = ""
    for raw in lock.read_text(encoding="utf-8").splitlines():
        part = raw.strip()
        if not part or part.startswith("#"):
            continue
        pending += (" " if pending else "") + (part[:-1].rstrip() if part.endswith("\\") else part)
        if part.endswith("\\"):
            continue
        if not pending.startswith("--"):
            logical_requirements.append(pending.strip())
        pending = ""
    if pending and not pending.startswith("--"):
        logical_requirements.append(pending.strip())
    has_hashes = ["--hash=sha256:" in line for line in logical_requirements]
    if any(has_hashes) and not all(has_hashes):
        raise ValueError(f"lock mixes hashed and unhashed requirements: {lock.name}")
    command = [python, "-m", "pip", "install", "--disable-pip-version-check", "--no-cache-dir"]
    if has_hashes and all(has_hashes):
        command.append("--require-hashes")
    if profile == "storm":
        command.extend(["--index-url", "https://pypi.org/simple", "--extra-index-url", "https://download.pytorch.org/whl/cpu"])
    command.extend(["-r", str(lock)])
    subprocess.run(command, check=True)
    subprocess.run([python, "-m", "pip", "check"], check=True)
    subprocess.run([python, "-c", f"import {selected['worker_module']}; print('selected {profile} worker import: PASS')"], check=True)
    subprocess.run([python, "-c", f"import importlib.metadata; actual=importlib.metadata.version({selected['package']!r}); assert actual == {selected['version']!r}, (actual, {selected['version']!r}); print('selected engine pin: ' + actual)"], check=True)
    return selected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("profile", choices=sorted(PROFILES))
    parser.add_argument("--requirements-root", default="requirements")
    parser.add_argument("--python")
    args = parser.parse_args()
    selected = install_profile(args.profile, args.python, args.requirements_root) if args.python else resolve_profile(args.profile, args.requirements_root)
    print(json.dumps(selected, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
