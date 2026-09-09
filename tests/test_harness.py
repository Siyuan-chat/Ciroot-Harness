import json
import copy
import tempfile
import unittest
from unittest.mock import patch, Mock
from pathlib import Path

from research_harness.errors import PreflightError, ValidationError
from research_harness.service import Harness
from research_harness.providers import SourceError, openalex_search

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
        duplicate=ready_spec(); duplicate["criteria"]=[{"id":"same","description":"a","mode":"qualitative","target":None,"required_conditions":{},"required":False,"minimum_evidence":"abstract"},{"id":"same","description":"b","mode":"qualitative","target":None,"required_conditions":{},"required":False,"minimum_evidence":"abstract"}]
        with self.assertRaises(ValidationError): self.h.validate(self._write(duplicate))
    def test_doctor_blocks_missing_hybrid_components(self):
        runtime=fixture_runtime(); runtime["retrieval"]["mode"]="hybrid"; runtime["retrieval"]["embedding"]["model"]="synthetic-model"
        self.runtime.write_text(json.dumps(runtime),encoding="utf-8")
        with patch("importlib.util.find_spec",return_value=None):
            result=self.h.doctor(self.runtime)
        self.assertFalse(result["ok"]); self.assertTrue(any("hybrid retrieval" in x for x in result["problems"]))
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
        evidence=self.h.store.evidence(ident); self.assertEqual(["p1"],[x["locator"] for x in evidence])
    def test_xml_mixed_content_and_parse_failure_are_persisted(self):
        xml=self.root/"mixed.xml"; xml.write_text("<article><p id='p1'>Before <b>bold</b> after</p><p id='p2'>Second</p></article>",encoding="utf-8")
        ident=self.h.import_document(xml,"baseline","paper")["document_id"]
        self.assertEqual(["Before bold after","Second"],[x["quote"] for x in self.h.store.evidence(ident)])
        bad=self.root/"bad.xml"; bad.write_text("<article><p>",encoding="utf-8"); bad_id=self.h.import_document(bad,"baseline","paper")["document_id"]
        self.h.store.close(); self.h=Harness(self.root/"workspace")
        row=[d for d in self.h.store.documents() if d["id"]==bad_id][0]
        self.assertEqual("failed",row["parse_status"]); self.assertIn("xml_parse_error",row["parse_errors"])
    def test_local_retrieval_uses_only_frozen_baseline(self):
        hit=self.root/"hit.txt"; discovery=self.root/"discovery.txt"; hit.write_text("polymer design evidence",encoding="utf-8"); discovery.write_text("polymer design secret",encoding="utf-8")
        hit_id=self.h.import_document(hit,"baseline","paper")["document_id"]; self.h.import_document(discovery,"discovery","paper")
        spec=ready_spec(); spec["topic"]="polymer design"; self._write(spec)
        run=self.h.run(self.spec,self.runtime); data=json.loads((self.root/"workspace"/"reports"/run/"report.json").read_text(encoding="utf-8"))
        self.assertEqual([hit_id],[r["document_id"] for r in data["retrieval"]["results"]])
    @patch("research_harness.providers.requests.request")
    def test_openalex_adapter_records_partial_cursor(self, request):
        response=Mock(ok=True,status_code=200); response.json.return_value={"results":[{"id":"W1","doi":"https://doi.org/x","title":"Title","abstract_inverted_index":{}}],"meta":{"next_cursor":"cursor"}}; request.return_value=response
        import os
        os.environ["TEST_OPENALEX"]="synthetic"
        result=openalex_search("query","TEST_OPENALEX",1,1)
        self.assertEqual("partial",result["completeness"]); self.assertEqual("W1",result["candidates"][0]["source_id"])
    @patch("research_harness.providers.requests.request")
    def test_openalex_rejects_missing_cursor_and_bad_envelope(self, request):
        import os
        os.environ["TEST_OPENALEX"]="synthetic-key"
        response=Mock(ok=True,status_code=200); request.return_value=response
        response.json.return_value={"results":[{}],"meta":{"count":3}}
        with self.assertRaises(SourceError) as error: openalex_search("q","TEST_OPENALEX",2,1)
        self.assertEqual("invalid_response",error.exception.kind)
        response.json.return_value={"results":[None],"meta":None}
        with self.assertRaises(SourceError) as error: openalex_search("q","TEST_OPENALEX",2,1)
        self.assertEqual("invalid_response",error.exception.kind)
