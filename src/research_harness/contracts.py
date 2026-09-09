"""Small, dependency-free validation for the public JSON contracts."""
from __future__ import annotations
import json
import re
from pathlib import Path
from .errors import ValidationError

ROOT = Path(__file__).resolve().parents[2]

def load_json(path: str | Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot read JSON: {exc}") from exc

def _require(data: dict, names: tuple[str, ...], context: str) -> None:
    missing = [n for n in names if n not in data]
    extra = set(data) - set(names)
    if missing or extra:
        raise ValidationError(f"{context}: missing={missing}, unexpected={sorted(extra)}")

def validate_spec(spec: dict) -> None:
    required = ("schema_version", "project_id", "revision", "status", "topic", "objectives", "languages", "scope", "reference_library", "criteria", "inclusion_rules", "exclusion_rules", "execution", "data_policy", "human_review", "report", "unresolved_questions")
    _require(spec, required, "ResearchSpec")
    if spec["schema_version"] != "1.0" or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", spec["project_id"]):
        raise ValidationError("unsupported schema_version or invalid project_id")
    if not isinstance(spec["revision"], int) or spec["revision"] < 1:
        raise ValidationError("revision must be a positive integer")
    if spec["status"] not in {"draft", "ready"} or not isinstance(spec["topic"], str) or not spec["topic"].strip():
        raise ValidationError("status/topic invalid")
    if not isinstance(spec["objectives"], list) or not spec["objectives"]:
        raise ValidationError("at least one objective is required")
    languages = spec["languages"]
    if set(languages) != {"conversation", "search", "reports", "timezone"} or languages["conversation"] not in {"zh", "en", "ja"}:
        raise ValidationError("languages invalid")
    if not set(languages["search"]).issubset({"zh", "en", "ja"}) or not set(languages["reports"]).issubset({"zh", "en", "ja"}):
        raise ValidationError("unsupported language")
    scope = spec["scope"]
    if set(scope) != {"document_types", "sources", "publication_date_from", "patent_jurisdictions"} or not set(scope["document_types"]).issubset({"paper", "patent"}):
        raise ValidationError("scope invalid")
    for criterion in spec["criteria"]:
        if criterion.get("mode") not in {"qualitative", "threshold", "relative_to_reference"}:
            raise ValidationError("criterion mode invalid")
        target = criterion.get("target")
        if (criterion["mode"] == "threshold") != isinstance(target, dict):
            raise ValidationError("threshold criterion requires target with value and unit")
    if spec["status"] == "ready" and spec["unresolved_questions"]:
        raise ValidationError("a ready spec cannot contain unresolved_questions")
    if spec["execution"].get("trigger") != "manual" or spec["data_policy"].get("embedding") != "local":
        raise ValidationError("manual trigger and local embedding are required")

def validate_runtime(runtime: dict) -> None:
    _require(runtime, ("schema_version", "llm", "retrieval", "sources", "network", "telemetry"), "RuntimeConfig")
    if runtime["schema_version"] != "1.0" or runtime["telemetry"] != "off":
        raise ValidationError("unsupported runtime schema or telemetry must be off")
    llm = runtime["llm"]
    if llm.get("provider") not in {"openai_compatible", "anthropic"} or llm.get("structured_output") not in {"auto", "json_schema", "tool_call"}:
        raise ValidationError("LLM provider/capability invalid")
    retrieval = runtime["retrieval"]
    if retrieval.get("mode") not in {"hybrid", "lexical_test_only"} or retrieval.get("embedding", {}).get("provider") != "fastembed":
        raise ValidationError("retrieval configuration invalid")

def fingerprint(value: dict) -> str:
    import hashlib
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
