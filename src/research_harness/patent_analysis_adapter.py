"""Local-only application adapter for frozen patent-structure inputs."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PureWindowsPath
from typing import Any

from .errors import ValidationError
from .patent_analysis import analyze_patent_publications


_TOP_LEVEL_FIELDS = {"schema_version", "run_id", "input_id", "selection_reason", "publications"}


def _required_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} must be a non-empty string")
    return value.strip()


def _reject_remote_fields(value: Any, location: str = "input") -> None:
    if isinstance(value, dict):
        forbidden = {"url", "uri", "endpoint", "download_url", "source_url"}
        for key, child in value.items():
            if isinstance(key, str) and key.casefold() in forbidden:
                raise ValidationError(f"{location}.{key} is not accepted; provide a local frozen input")
            _reject_remote_fields(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_remote_fields(child, f"{location}[{index}]")


def _reject_network_path(value: str | Path) -> Path:
    path = Path(value)
    windows_path = PureWindowsPath(str(value))
    if windows_path.drive.startswith("\\\\") or str(value).startswith(("\\\\", "//")):
        raise ValidationError("network/UNC input paths are not accepted; use a local disk file")
    if not path.is_absolute():
        raise ValidationError("input_path must be absolute")
    return path


def analyze_patent_input(payload: dict[str, Any], *, input_path: str | Path, input_sha256: str) -> dict[str, Any]:
    """Analyze a pre-frozen local bundle without fetching sources or accepting claims."""
    if not isinstance(payload, dict):
        raise ValidationError("patent input must be a JSON object")
    _reject_remote_fields(payload)
    if set(payload) != _TOP_LEVEL_FIELDS:
        raise ValidationError("patent input must contain exactly schema_version, run_id, input_id, selection_reason, and publications")
    if payload.get("schema_version") != "1":
        raise ValidationError("unsupported frozen patent input schema_version")
    run_id = _required_text(payload.get("run_id"), "run_id")
    input_id = _required_text(payload.get("input_id"), "input_id")
    selection_reason = _required_text(payload.get("selection_reason"), "selection_reason")
    publications = payload.get("publications")
    if not isinstance(publications, list) or not publications or not all(isinstance(item, dict) for item in publications):
        raise ValidationError("publications must be a non-empty list of objects")
    if not isinstance(input_sha256, str) or len(input_sha256) != 64 or any(char not in "0123456789abcdef" for char in input_sha256.casefold()):
        raise ValidationError("input_sha256 must be a SHA-256 hex digest")
    source_path = _reject_network_path(input_path).resolve(strict=False)
    if PureWindowsPath(str(source_path)).drive.startswith("\\\\") or str(source_path).startswith(("\\\\", "//")):
        raise ValidationError("resolved input path points to a network/UNC location")

    analysis = analyze_patent_publications(publications)
    issues = analysis.get("issues", [])
    analyses = analysis.get("publication_analyses", [])
    bound_publications = sum(
        bool(item.get("source_bindings")) and all(
            all(binding.get("binding_checks", {}).values()) for binding in item["source_bindings"]
        )
        for item in analyses if isinstance(item, dict)
    )
    return {
        "schema_version": "1",
        "run_id": run_id,
        "input_binding": {
            "input_id": input_id,
            "selection_reason": selection_reason,
            "source_kind": "local_frozen_json",
            "path": str(source_path),
            "sha256": input_sha256.lower(),
        },
        "status": "partial" if issues else "completed",
        "coverage": {
            "publication_count": len(publications),
            "source_bound_publication_count": bound_publications,
            "issue_count": len(issues),
        },
        "analysis": analysis,
        "claim_acceptance": "not_assessed",
        "limitations": [
            "Structural algorithm output does not accept claims or provide legal or scientific conclusions.",
            "Only the supplied frozen JSON was analyzed; this adapter performs no source requests, downloads, or database writes.",
        ],
    }


def load_and_analyze_patent_input(input_path: str | Path) -> dict[str, Any]:
    """Load one absolute local JSON bundle and bind results to its exact bytes."""
    path = _reject_network_path(input_path)
    try:
        path = path.resolve(strict=True)
    except OSError as exc:
        raise ValidationError("input file does not exist or cannot be resolved") from exc
    if PureWindowsPath(str(path)).drive.startswith("\\\\") or str(path).startswith(("\\\\", "//")):
        raise ValidationError("resolved input path points to a network/UNC location")
    if not path.is_file() or path.suffix.casefold() != ".json":
        raise ValidationError("input must be an existing local .json file")
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8-sig"), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValidationError("input is not valid UTF-8 JSON") from exc
    return analyze_patent_input(payload, input_path=path, input_sha256=hashlib.sha256(raw).hexdigest())
