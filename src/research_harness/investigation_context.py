"""Canonical, immutable application-layer context bundles and receipts."""
from __future__ import annotations

import hashlib
import json


def canonical_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def build_context_bundle(*, run_id: str, task_id: str, task_version: int, payload: dict, output_schema: dict, prompt: str, profile: dict, included_refs: list[str], template_version: str, budget: dict, authorization: dict, retrieval_selection=None) -> dict:
    core = {"task_id": task_id, "task_version": task_version, "payload": payload, "output_schema": output_schema,
            "run_id": run_id, "prompt": prompt, "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "template_version": template_version, "profile": profile, "included_refs": included_refs,
            "retrieval_selection": retrieval_selection, "budget": budget, "authorization": authorization}
    return {**core, "logical_sha256": hashlib.sha256(canonical_bytes(core)).hexdigest(), "capture_layer": "application"}


def verify_context_bundle(bundle: dict) -> bool:
    core = {key: value for key, value in bundle.items() if key not in {"logical_sha256", "capture_layer"}}
    return bundle.get("capture_layer") == "application" and hashlib.sha256(canonical_bytes(core)).hexdigest() == bundle.get("logical_sha256")
