import json
import tempfile
import unittest
from pathlib import Path

from research_harness.errors import PreflightError, ValidationError
from research_harness.service import Harness

ROOT = Path(__file__).parents[1]

def ready_spec():
    spec = json.loads((ROOT / "examples" / "polymer-design.draft.json").read_text(encoding="utf-8"))
    spec["status"] = "ready"; spec["unresolved_questions"] = []
    return spec

def fixture_runtime():
    runtime = json.loads((ROOT / "examples" / "runtime.example.json").read_text(encoding="utf-8"))
    runtime["llm"].update({"model":"fixture-local", "local":True})
    runtime["retrieval"]["mode"] = "lexical_test_only"
    runtime["sources"]["openalex"]["enabled"] = False
    runtime["sources"]["epo"]["enabled"] = False
    return runtime

class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        self.spec=self.root/"research.json"; self.runtime=self.root/"runtime.json"
        self.spec.write_text(json.dumps(ready_spec()),encoding="utf-8")
        self.runtime.write_text(json.dumps(fixture_runtime()),encoding="utf-8")
        self.h=Harness(self.root/"workspace")
    def tearDown(self):
        self.h.store.close()
        self.tmp.cleanup()
    def test_draft_cannot_run(self):
        draft=ready_spec(); draft["status"]="draft"; draft["unresolved_questions"]=["scope"]
        self.spec.write_text(json.dumps(draft),encoding="utf-8")
        with self.assertRaises(PreflightError): self.h.run(self.spec,self.runtime)
    def test_import_run_and_reports_are_local_fixture(self):
        source=self.root/"paper.txt"; source.write_text("Evidence paragraph 1\n",encoding="utf-8")
        doc=self.h.import_document(source,"baseline","paper")
        run=self.h.run(self.spec,self.runtime)
        record=self.h.store.run(run); self.assertEqual(record["status"],"completed")
        report=self.root/"workspace"/"reports"/run
        self.assertTrue((report/"report.json").exists()); self.assertTrue((report/"report.zh.html").exists())
        facts=json.loads((report/"report.json").read_text(encoding="utf-8")); self.assertTrue(facts["synthetic"]); self.assertIn(doc,facts["baseline_document_ids"])
    def test_invalid_ready_spec_is_rejected(self):
        bad=ready_spec(); bad["unresolved_questions"]=["missing"]
        self.spec.write_text(json.dumps(bad),encoding="utf-8")
        with self.assertRaises(ValidationError): self.h.validate(self.spec)
    def test_doctor_never_calls_network(self):
        result=self.h.doctor(self.runtime); self.assertFalse(result["network_called"])
