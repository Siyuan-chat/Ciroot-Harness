"""Validation of the installed public JSON contracts."""
from __future__ import annotations
import hashlib, json
from importlib import resources
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker
from .errors import ValidationError

def load_json(path: str | Path) -> dict:
    try: return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc: raise ValidationError(f"cannot read JSON: {exc}") from exc

def _validate(value: dict, name: str) -> None:
    schema=json.loads(resources.files("research_harness").joinpath("schemas",name).read_text(encoding="utf-8"))
    errors=sorted(Draft202012Validator(schema,format_checker=FormatChecker()).iter_errors(value),key=lambda e:list(e.path))
    if errors:
        error=errors[0]; raise ValidationError(f"{'.'.join(map(str,error.path)) or '$'}: {error.message}")

def validate_spec(spec: dict) -> None: _validate(spec,"research-spec.schema.json")
def validate_runtime(runtime: dict) -> None: _validate(runtime,"runtime.schema.json")
def fingerprint(value: dict) -> str: return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",", ":")).encode()).hexdigest()
