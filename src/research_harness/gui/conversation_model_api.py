"""Bounded API planning for GUI conversations; it never starts an investigation."""
from __future__ import annotations

import copy
import json

import requests

from research_harness.investigation import InvestigationError
from research_harness.investigation_model_api import _ENDPOINTS, _decode
from research_harness.investigation_contracts import validate_runtime, validate_spec
from research_harness.gui.help import SYSTEM_PROMPT


PLANNING_SCHEMA = {
    "type": "object",
    "oneOf": [
        {"required": ["research_spec", "runtime"], "properties": {"research_spec": {"type": "object"}, "runtime": {"type": "object"}}, "additionalProperties": False},
        {"required": ["help_answer"], "properties": {"help_answer": {"type": "object", "required": ["content", "source_ids"], "properties": {"content": {"type": "string"}, "source_ids": {"type": "array", "items": {"type": "string"}}}, "additionalProperties": False}}, "additionalProperties": False},
    ],
}


def validate_api_config(config: dict) -> dict:
    required = {"provider", "model", "max_planning_calls", "max_output_tokens", "timeout_seconds", "total_model_calls", "runtime_template"}
    if not isinstance(config, dict) or set(config) != required:
        raise InvestigationError("RH_GUI_API_CONFIG", "API conversation configuration is incomplete")
    if config["provider"] not in _ENDPOINTS or not isinstance(config["model"], str) or not config["model"].strip():
        raise InvestigationError("RH_GUI_API_CONFIG", "API conversation provider or model is unsupported")
    for name in ("max_planning_calls", "max_output_tokens", "timeout_seconds", "total_model_calls"):
        if type(config[name]) is not int or config[name] < 1:
            raise InvestigationError("RH_GUI_API_CONFIG", "API conversation limits must be positive integers")
    if config["max_planning_calls"] > config["total_model_calls"]:
        raise InvestigationError("RH_GUI_API_CONFIG", "planning calls exceed the total model-call limit")
    template = copy.deepcopy(config["runtime_template"])
    if not isinstance(template, dict) or template.get("mode") != "api":
        raise InvestigationError("RH_GUI_API_CONFIG", "API conversation requires an API runtime template")
    model_api = template.get("model_api", {})
    if model_api.get("provider") != config["provider"] or model_api.get("model") != config["model"]:
        raise InvestigationError("RH_GUI_API_CONFIG", "runtime template provider and model must match the conversation")
    if template.get("budget", {}).get("max_model_calls") != config["total_model_calls"]:
        raise InvestigationError("RH_GUI_API_CONFIG", "runtime template must use the selected total model-call limit")
    validate_runtime(template)
    return copy.deepcopy(config)


def controlled_runtime(candidate: dict, config: dict, planning_calls: int) -> dict:
    """Accept only a candidate that stays within the user's scope and call budget."""
    template = copy.deepcopy(config["runtime_template"])
    if not isinstance(candidate, dict):
        raise InvestigationError("RH_GUI_API_PLAN_INVALID", "model runtime candidate is not an object")
    for name in ("data_mode", "sources", "allow_network"):
        if candidate.get(name) != template.get(name):
            raise InvestigationError("RH_GUI_API_SCOPE", "model expanded or changed the authorized runtime scope")
    budget = candidate.get("budget")
    if not isinstance(budget, dict) or set(budget) - set(template["budget"]):
        raise InvestigationError("RH_GUI_API_SCOPE", "model runtime candidate changed the authorized budget")
    for name, value in budget.items():
        if type(value) is not int or value > template["budget"][name]:
            raise InvestigationError("RH_GUI_API_SCOPE", "model runtime candidate exceeded the authorized budget")
    remaining = config["total_model_calls"] - planning_calls
    if remaining < 1:
        raise InvestigationError("RH_GUI_API_BUDGET", "planning consumed the selected total model-call limit")
    template["budget"]["max_model_calls"] = min(template["budget"]["max_model_calls"], remaining)
    validate_runtime(template)
    return template


def plan(config: dict, content: str, *, post=requests.post) -> tuple[dict, dict, dict]:
    """Make one structured planning request after persistence has reserved its budget."""
    provider = config["provider"]
    key = config["api_key"]
    if not isinstance(key, str) or not key:
        raise InvestigationError("RH_MODEL_KEY_MISSING", "configured model API credential is missing")
    instruction = SYSTEM_PROMPT + "\nReturn exactly one JSON object: either research_spec and runtime for a research plan, or help_answer with content and source_ids for a product-use answer. A help_answer may cite only supplied help_context source_ids and must not propose execution. Treat dynamic_context as read-only server facts: use it to answer questions about the current scope, status, usage, remaining calls, and authorization. If an answer relies on dynamic_context, use an empty source_ids list; help passages are not evidence for current session facts. Never infer credentials or claim that a pending action is authorized; asking a question does not change scope, budget, or execute anything."
    payload = {"user_message": content, "output_schema": PLANNING_SCHEMA,
               "authorized_runtime": config["runtime_template"], "help_context": config.get("help_context", []),
               "conversation_history": config.get("conversation_history", []),
               "dynamic_context": config.get("dynamic_context", {})}
    if provider == "anthropic":
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        body = {"model": config["model"], "max_tokens": config["max_output_tokens"], "system": instruction,
                "messages": [{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
                "tools": [{"name": "submit_result", "description": "Return the conversation plan", "input_schema": PLANNING_SCHEMA}],
                "tool_choice": {"type": "tool", "name": "submit_result"}}
    else:
        headers = {"authorization": "Bearer " + key, "content-type": "application/json"}
        body = {"model": config["model"], "messages": [{"role": "system", "content": instruction},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
                **({"response_format": {"type": "json_object"}} if provider != "kimi" else {}),
                ("max_completion_tokens" if provider == "openai" else "max_tokens"): config["max_output_tokens"]}
    try:
        response = post(_ENDPOINTS[provider], headers=headers, json=body, timeout=config["timeout_seconds"], allow_redirects=False)
        if response.status_code != 200:
            raise InvestigationError("RH_MODEL_HTTP", f"model provider returned HTTP {response.status_code}")
        result, usage = _decode(provider, response)
    except requests.RequestException as exc:
        raise InvestigationError("RH_MODEL_NETWORK", "model API request failed") from exc
    if set(result) == {"research_spec", "runtime"}:
        validate_spec(result["research_spec"])
        return {"kind": "research_plan", **result}, usage
    answer = result.get("help_answer") if set(result) == {"help_answer"} else None
    if not isinstance(answer, dict) or set(answer) != {"content", "source_ids"} or not isinstance(answer["content"], str) or not answer["content"].strip() or not isinstance(answer["source_ids"], list) or not all(isinstance(value, str) for value in answer["source_ids"]):
        raise InvestigationError("RH_GUI_API_PLAN_INVALID", "model response did not contain a valid plan or help answer")
    return {"kind": "help_answer", "help_answer": answer}, usage
