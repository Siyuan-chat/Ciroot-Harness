"""Synthetic subprocess tests for the research-engine JSONL boundary."""
import json
import sys
import textwrap
from pathlib import Path

from research_harness.research_engine_protocol import PROTOCOL
from research_harness.research_engines import run_engine


IDENTITY = {"run_id": "r-1", "task_id": "t-1", "task_version": 3}


def envelope(**overrides):
    value = {
        "run_id": "r-1",
        "task": {"task_id": "t-1", "task_version": 3, "role": "synthesis", "task_type": "draft", "payload": {}, "output_schema": {}},
        "evidence": [],
        "profile": {"engine": "synthetic", "version": "1", "runtime_python": sys.executable, "enabled": True},
        "limits": {"max_rpc_requests": 2, "max_output_bytes": 4096},
    }
    value.update(overrides)
    return value


def run(script, env=None, handle=None, timeout=3):
    return run_engine([sys.executable, "-c", textwrap.dedent(script)], env or envelope(), handle or (lambda _: {}), timeout)


def test_subprocess_accepts_one_identity_bound_draft_result():
    result = run(f"""
        import json,sys
        msg=json.loads(sys.stdin.readline())
        out={{'protocol':{PROTOCOL!r},'op':'result','identity':msg['identity'],'engine':{{'name':'synthetic','version':'1'}},'draft':{{'sections':[],'claims':[],'citations':[],'coverage_gaps':[]}},'trace':{{'fixture':'synthetic'}}}}
        print(json.dumps(out))
    """)
    assert result["status"] == "draft"
    assert result["draft"]["sections"] == []
    assert result["trace"]["fixture"] == "synthetic"


def test_rpc_is_forwarded_serially_with_parent_identity_and_reply_shape():
    calls = []
    result = run(f"""
        import json,sys
        msg=json.loads(sys.stdin.readline()); i=msg['identity']
        print(json.dumps({{'protocol':{PROTOCOL!r},'op':'rpc','identity':i,'rpc_op':'retrieve_frozen','request_id':'q1','purpose':'frozen lookup','request':{{'query':'demo'}}}}),flush=True)
        reply=json.loads(sys.stdin.readline())
        print(json.dumps({{'protocol':{PROTOCOL!r},'op':'result','identity':i,'engine':{{'name':'synthetic','version':'1'}},'draft':{{'sections':[],'claims':[],'citations':[],'coverage_gaps':[]}},'trace':{{'reply_op':reply['op'],'reply_id':reply['request_id'],'reply_outcome':reply['outcome']}}}}))
    """, handle=lambda request: calls.append(request) or {"outcome": "ok", "result": {"items": []}, "core_call_id": "core-1", "usage": {"retrievals": 1}})
    assert result["status"] == "draft"
    assert result["trace"]["reply_op"] == "rpc_result"
    assert result["trace"]["reply_outcome"] == "ok"
    assert len(calls) == 1
    assert calls[0]["identity"] == IDENTITY
    assert calls[0]["op"] == "retrieve_frozen"


def test_repeated_rpc_request_id_and_unknown_rpc_fail_closed():
    ok_reply = {"outcome": "ok", "result": {}, "core_call_id": "cc-1", "usage": {}}
    repeat = run(f"""
        import json,sys
        msg=json.loads(sys.stdin.readline()); i=msg['identity']
        q={{'protocol':{PROTOCOL!r},'op':'rpc','identity':i,'rpc_op':'embedding','request_id':'same','purpose':'embed','request':{{}}}}
        print(json.dumps(q),flush=True); sys.stdin.readline(); print(json.dumps(q),flush=True)
    """, handle=lambda _: ok_reply)
    assert repeat["error"]["code"] == "RH_ENGINE_REQUEST_ID"
    unknown = run(f"""
        import json,sys
        msg=json.loads(sys.stdin.readline())
        print(json.dumps({{'protocol':{PROTOCOL!r},'op':'rpc','identity':msg['identity'],'rpc_op':'fetch_url','request_id':'q','purpose':'bad','request':{{'url':'https://example.invalid'}}}}),flush=True)
    """)
    assert unknown["error"]["code"] == "RH_ENGINE_RPC_UNKNOWN"


def test_wrong_identity_malformed_json_and_eof_are_typed_failures():
    wrong = run(f"""
        import json,sys
        msg=json.loads(sys.stdin.readline()); msg['task_version'] if False else None
        print(json.dumps({{'protocol':{PROTOCOL!r},'op':'result','identity':{{'run_id':'elsewhere','task_id':'t-1','task_version':3}},'engine':{{'name':'x','version':'1'}},'draft':{{'sections':[],'claims':[],'citations':[],'coverage_gaps':[]}},'trace':{{}}}}))
    """)
    malformed = run("import sys; sys.stdin.readline(); print('{broken}')")
    eof = run("import sys; sys.stdin.readline()")
    assert wrong["error"]["code"] == "RH_ENGINE_IDENTITY"
    assert malformed["error"]["code"] == "RH_ENGINE_JSON"
    assert eof["error"]["code"] == "RH_ENGINE_EOF"


def test_deadline_output_and_rpc_count_limits_are_enforced():
    slow = run("import sys,time; sys.stdin.readline(); time.sleep(2)", timeout=0.1)
    noisy = run("import sys; sys.stdin.readline(); print('x'*1100000)")
    limited_env = envelope(limits={"max_rpc_requests": 0, "max_output_bytes": 4096})
    limited = run(f"""
        import json,sys
        msg=json.loads(sys.stdin.readline())
        print(json.dumps({{'protocol':{PROTOCOL!r},'op':'rpc','identity':msg['identity'],'rpc_op':'model_call','request_id':'q','purpose':'call','request':{{}}}}),flush=True)
    """, env=limited_env)
    assert slow["error"]["code"] == "RH_ENGINE_TIMEOUT"
    assert noisy["error"]["code"] == "RH_ENGINE_LINE_LIMIT"
    assert limited["error"]["code"] == "RH_ENGINE_RPC_LIMIT"


def test_total_output_cap_and_late_message_after_final_are_rejected():
    small_budget = envelope(limits={"max_rpc_requests": 5, "max_output_bytes": 700})
    repeated = run(f"""
        import json,sys
        msg=json.loads(sys.stdin.readline()); i=msg['identity']
        q={{'protocol':{PROTOCOL!r},'op':'rpc','identity':i,'rpc_op':'retrieve_frozen','request_id':'q1','purpose':'x'*500,'request':{{}}}}
        print(json.dumps(q),flush=True); sys.stdin.readline()
        q['request_id']='q2'; print(json.dumps(q),flush=True)
    """, env=small_budget, handle=lambda _: {"outcome": "ok", "result": {}, "core_call_id": None, "usage": {}})
    late = run(f"""
        import json,sys
        msg=json.loads(sys.stdin.readline()); i=msg['identity']
        result={{'protocol':{PROTOCOL!r},'op':'result','identity':i,'engine':{{'name':'synthetic','version':'1'}},'draft':{{'sections':[],'claims':[],'citations':[],'coverage_gaps':[]}},'trace':{{}}}}
        print(json.dumps(result),flush=True); print(json.dumps({{'protocol':{PROTOCOL!r},'op':'late','identity':i}}),flush=True)
    """)
    assert repeated["error"]["code"] == "RH_ENGINE_OUTPUT_LIMIT"
    assert late["error"]["code"] == "RH_ENGINE_LATE_MESSAGE"


def test_missing_runtime_is_pending_activation_and_profile_secrets_are_rejected():
    pending = run("raise SystemExit(0)", env=envelope(profile={"engine": "synthetic", "version": "1", "enabled": True}))
    secret = run("raise SystemExit(0)", env=envelope(profile={"engine": "synthetic", "version": "1", "runtime_python": sys.executable, "enabled": True, "api_token": "never-log"}))
    assert pending["error"]["code"] == "RH_ENGINE_PENDING_ACTIVATION"
    assert secret["error"]["code"] == "RH_ENGINE_PROFILE_SECRET"
    assert "never-log" not in json.dumps(secret)


def test_profile_output_token_limits_are_not_misclassified_as_credentials():
    profile = {"engine": "synthetic", "version": "1", "runtime_python": sys.executable,
               "enabled": True, "max_output_tokens": 256, "max_tokens": 128}
    result = run("import json,sys; m=json.loads(sys.stdin.readline()); print(json.dumps({'protocol':'research-engine-jsonl/1','op':'result','identity':m['identity'],'engine':{'name':'synthetic','version':'1'},'draft':{'sections':[],'claims':[],'citations':[],'coverage_gaps':[]},'trace':{}}))",
                 env=envelope(profile=profile))
    assert result["status"] == "draft"


def test_non_finite_timeouts_are_rejected_before_launch():
    for timeout in (float("nan"), float("inf"), float("-inf")):
        result = run("raise SystemExit(0)", timeout=timeout)
        assert result["error"]["code"] == "RH_ENGINE_TIMEOUT"


def test_worker_does_not_inherit_provider_credentials(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "parent-secret-must-stay-in-core")
    result = run(f"""
        import json,os,sys
        msg=json.loads(sys.stdin.readline())
        print(json.dumps({{'protocol':{PROTOCOL!r},'op':'result','identity':msg['identity'],'engine':{{'name':'synthetic','version':'1'}},'draft':{{'sections':[],'claims':[],'citations':[],'coverage_gaps':[]}},'trace':{{'inherited_secret':bool(os.environ.get('OPENAI_API_KEY'))}}}}))
    """)
    assert result["status"] == "draft"
    assert result["trace"]["inherited_secret"] is False


def test_nonzero_exit_after_valid_result_is_not_success():
    result = run(f"""
        import json,sys
        msg=json.loads(sys.stdin.readline())
        print(json.dumps({{'protocol':{PROTOCOL!r},'op':'result','identity':msg['identity'],'engine':{{'name':'synthetic','version':'1'}},'draft':{{'sections':[],'claims':[],'citations':[],'coverage_gaps':[]}},'trace':{{}}}}))
        sys.exit(2)
    """)
    assert result["error"]["code"] == "RH_ENGINE_EXIT"


def test_root_and_packaged_protocol_schemas_are_identical_valid_json():
    for name in ("research-engine.schema.json", "research-engine-protocol.schema.json"):
        root = Path("schemas") / name
        packaged = Path("src/research_harness/schemas") / name
        assert root.read_bytes() == packaged.read_bytes()
        json.loads(root.read_text(encoding="utf-8"))
