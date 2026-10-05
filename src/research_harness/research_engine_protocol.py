"""JSONL protocol helpers for supervised, non-authoritative research engines."""
from __future__ import annotations

import json
from typing import Any


PROTOCOL = "research-engine-jsonl/1"
IDENTITY_FIELDS = ("run_id", "task_id", "task_version")


class ProtocolError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def identity_of(envelope: dict[str, Any]) -> dict[str, Any]:
    task = envelope.get("task")
    if not isinstance(task, dict):
        raise ProtocolError("RH_ENGINE_ENVELOPE", "task object is required")
    identity = {
        "run_id": envelope.get("run_id"),
        "task_id": task.get("task_id"),
        "task_version": task.get("task_version"),
    }
    if not isinstance(identity["run_id"], str) or not identity["run_id"]:
        raise ProtocolError("RH_ENGINE_ENVELOPE", "run_id is required")
    if not isinstance(identity["task_id"], str) or not identity["task_id"]:
        raise ProtocolError("RH_ENGINE_ENVELOPE", "task.task_id is required")
    if isinstance(identity["task_version"], bool) or not isinstance(identity["task_version"], int) or identity["task_version"] < 1:
        raise ProtocolError("RH_ENGINE_ENVELOPE", "task.task_version must be a positive integer")
    return identity


def encode_message(message: dict[str, Any]) -> bytes:
    try:
        return (json.dumps(message, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProtocolError("RH_ENGINE_JSON", "message is not finite JSON") from exc


def decode_message(line: bytes) -> dict[str, Any]:
    def no_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    try:
        value = json.loads(line.decode("utf-8"), object_pairs_hook=no_duplicates,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite JSON number")))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ProtocolError("RH_ENGINE_JSON", "worker emitted malformed UTF-8 JSONL") from exc
    if not isinstance(value, dict):
        raise ProtocolError("RH_ENGINE_MESSAGE", "worker JSONL message must be an object")
    return value
