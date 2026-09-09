import json
import copy
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
        doc=self.h.import_document(source,"baseline","paper")["document_id"]
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
    def test_schema_rejects_reviewed_counterexamples(self):
        cases=[]
        x=ready_spec(); x["execution"]["budget"]["max_candidates"]=-1; cases.append(x)
        x=ready_spec(); x["human_review"]["global_rule_updates"]="automatic"; cases.append(x)
        x=ready_spec(); x["scope"]["publication_date_from"]="2026-02-30"; cases.append(x)
        x=ready_spec(); x["languages"]["reports"]=[]; cases.append(x)
        x=ready_spec(); x["criteria"]=[{"id":"x","description":"x","mode":"threshold","target":{},"required_conditions":{},"required":True,"minimum_evidence":"fulltext"}]; cases.append(x)
        for case in cases:
            with self.assertRaises(ValidationError): self.h.validate(self._write(case))
        runtime=fixture_runtime(); runtime["llm"]["api_key"]="synthetic-sentinel"
        self.runtime.write_text(json.dumps(runtime),encoding="utf-8")
        with self.assertRaises(ValidationError): self.h.doctor(self.runtime)
    def _write(self, value):
        self.spec.write_text(json.dumps(value),encoding="utf-8"); return self.spec
    def test_report_is_a_frozen_snapshot_and_honors_explicit_reference(self):
        first=self.root/"one.txt"; second=self.root/"two.txt"; later=self.root/"later.txt"
        first.write_text("one",encoding="utf-8"); second.write_text("two",encoding="utf-8"); later.write_text("later",encoding="utf-8")
        first_id=self.h.import_document(first,"baseline","paper")["document_id"]; self.h.import_document(second,"baseline","paper")
        spec=ready_spec(); spec["reference_library"]["collection_ids"]=[]; spec["reference_library"]["document_ids"]=[first_id]; self._write(spec)
        run=self.h.run(self.spec,self.runtime); report=self.root/"workspace"/"reports"/run/"report.json"; before=report.read_text(encoding="utf-8")
        self.h.import_document(later,"discovery","paper"); self.h.report(run,["en"])
        after=report.read_text(encoding="utf-8"); self.assertEqual(before,after); self.assertEqual([first_id],json.loads(after)["baseline_document_ids"])
    def test_xml_parser_keeps_stable_locator(self):
        xml=self.root/"record.xml"; xml.write_text("<article><p id='p1'>Measured result</p></article>",encoding="utf-8")
        ident=self.h.import_document(xml,"baseline","paper")["document_id"]
        evidence=self.h.store.evidence(ident); self.assertEqual(evidence[0]["locator"],"element:1"); self.assertEqual(evidence[1]["locator"],"p1")
