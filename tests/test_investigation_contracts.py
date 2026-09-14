import hashlib
from pathlib import Path
import pytest
from research_harness.errors import HarnessError
from research_harness.investigation_contracts import get_task_schema, validate_runtime, validate_spec

def test_root_and_package_contract_resources_match():
    root = Path("schemas")
    package = Path("src/research_harness/schemas")
    for name in ("investigation-spec.schema.json", "investigation-runtime.schema.json", "investigation-task.schema.json"):
        assert hashlib.sha256((root / name).read_bytes()).digest() == hashlib.sha256((package / name).read_bytes()).digest()

def test_public_contract_helpers_validate_d19_shapes():
    validate_spec({"status":"ready","project_id":"p","revision":1,"research_question":"q","report_targets":["technical_report"],"references":[],"criteria":[{"value":1,"unit":"m"}]})
    validate_runtime({"mode":"host","data_mode":"synthetic","budget":{"max_tasks":1}})
    assert get_task_schema("verification")["properties"]["status"]["enum"] == ["supported","partial","insufficient","contradicted"]
    with pytest.raises(HarnessError): validate_runtime({"mode":"host","data_mode":"synthetic","budget":{"max_tasks":True}})
    with pytest.raises(HarnessError): validate_spec({"status":"ready","project_id":"p","revision":1,"research_question":"q","report_targets":[],"references":[]})
