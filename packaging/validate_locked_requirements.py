"""Validate exact local lock pins while preserving pip hash-checked lock files."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

try:
    from pip._vendor.packaging.requirements import Requirement
    from pip._vendor.packaging.utils import canonicalize_name
except ImportError as exc:  # pragma: no cover - BasePython is required to include pip
    raise SystemExit("the selected Python must include pip's packaging requirement parser") from exc


HASH_ARGUMENT = re.compile(r"\s+--hash(?:=|\s+)([^\s]+)")
SHA256 = re.compile(r"sha256:[0-9a-fA-F]{64}\Z")


def read_locked_pins(path: str | Path, environment: dict[str, str] | None = None) -> dict[str, str]:
    pins: dict[str, str] = {}
    for number, raw in enumerate(Path(path).read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        hashes = HASH_ARGUMENT.findall(line)
        if any(not SHA256.fullmatch(value) for value in hashes):
            raise ValueError(f"invalid lock hash at {path}:{number}")
        requirement_line = HASH_ARGUMENT.sub("", line).strip()
        if "--hash" in requirement_line:
            raise ValueError(f"unrecognized pip hash option at {path}:{number}")
        try:
            requirement = Requirement(requirement_line)
        except Exception as exc:
            raise ValueError(f"invalid PEP 508 requirement at {path}:{number}: {exc}") from exc
        specs = list(requirement.specifier)
        if requirement.url is None and (len(specs) != 1 or specs[0].operator != "==" or specs[0].version.endswith(".*")):
            raise ValueError(f"requirement must have exactly one non-wildcard == pin at {path}:{number}")
        if requirement.url is not None and not requirement.url.startswith("file:///"):
            raise ValueError(f"direct references must be absolute local file URLs at {path}:{number}")
        if requirement.marker is not None and not requirement.marker.evaluate(environment):
            continue
        name = canonicalize_name(requirement.name)
        pin = "url=" + requirement.url if requirement.url else specs[0].version
        if name in pins and pins[name] != pin:
            raise ValueError(f"conflicting duplicate pins for {name} in {path}")
        pins[name] = pin
    return pins


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: validate_locked_requirements.py LOCK_FILE")
    try:
        print(json.dumps(read_locked_pins(sys.argv[1]), sort_keys=True))
    except (OSError, UnicodeError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
