"""Verify the installed core import and, for wheel installs, wheel identity."""
from __future__ import annotations

import email
import hashlib
import importlib
import importlib.metadata
import json
import sys
import zipfile
from pathlib import Path


def main() -> int:
    wheel_path = Path(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1] else None
    expected_hash = sys.argv[2].casefold() if len(sys.argv) > 2 and sys.argv[2] else None
    distribution = importlib.metadata.distribution("research-harness")
    package = importlib.import_module("research_harness")
    imported = Path(package.__file__).resolve()
    installed_init = Path(distribution.locate_file("research_harness/__init__.py")).resolve()
    if imported != installed_init:
        raise SystemExit("research_harness import is not the selected installed distribution")

    wheel_hash = None
    verified_modules = 0
    if wheel_path:
        wheel_hash = hashlib.sha256(wheel_path.read_bytes()).hexdigest()
        if expected_hash and wheel_hash != expected_hash:
            raise SystemExit("selected core wheel hash changed during installation")
        with zipfile.ZipFile(wheel_path) as archive:
            metadata_names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
            if len(metadata_names) != 1:
                raise SystemExit("core wheel must contain one distribution METADATA file")
            wheel_metadata = email.message_from_bytes(archive.read(metadata_names[0]))
            if (wheel_metadata.get("Name", "").casefold().replace("_", "-") != "research-harness" or
                    wheel_metadata.get("Version") != distribution.version):
                raise SystemExit("installed core version does not match the supplied wheel metadata")
            for name in archive.namelist():
                if not name.startswith("research_harness/") or not name.endswith(".py"):
                    continue
                installed_file = Path(distribution.locate_file(name))
                if not installed_file.is_file() or installed_file.read_bytes() != archive.read(name):
                    raise SystemExit(f"installed core module differs from wheel: {name}")
                verified_modules += 1
        if not verified_modules:
            raise SystemExit("core wheel contains no importable package modules")

    print(json.dumps({"version": distribution.version, "import_path": str(imported),
                      "verified_wheel_sha256": wheel_hash, "verified_module_count": verified_modules}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
