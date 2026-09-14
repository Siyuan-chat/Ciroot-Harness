"""Public, resource-backed D19 investigation contract helpers."""
from __future__ import annotations
import json
from importlib import resources
from typing import Any
from jsonschema import Draft202012Validator
from .errors import ValidationError

def _load(name: str) -> dict[str, Any]:
    return json.loads(resources.files("research_harness").joinpath("schemas", name).read_text(encoding="utf-8"))

def _validate(value: dict[str, Any], name: str) -> None:
    if not isinstance(value, dict): raise ValidationError("contract input must be an object")
    errors = sorted(Draft202012Validator(_load(name)).iter_errors(value), key=lambda error: list(error.path))
    if errors: raise ValidationError(f"invalid contract field: {'.'.join(map(str, errors[0].path)) or '$'}")

def validate_spec(spec: dict[str, Any]) -> None: _validate(spec, "investigation-spec.schema.json")
def validate_runtime(runtime: dict[str, Any]) -> None: _validate(runtime, "investigation-runtime.schema.json")

def get_task_schema(role: str) -> dict[str, Any]:
    schema = _load("investigation-task.schema.json")
    try: return {"$schema": schema["$schema"], "$defs": schema["$defs"], **schema["$defs"]["roles"][role]}
    except KeyError as exc: raise ValidationError("unknown investigation task role") from exc
