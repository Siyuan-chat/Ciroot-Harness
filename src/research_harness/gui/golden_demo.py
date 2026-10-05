"""Small GUI projection of the canonical, offline Golden Demo."""
from __future__ import annotations

import json
import re
from pathlib import Path

from research_harness.golden_demo import run_golden_demo
from research_harness.investigation import InvestigationError, InvestigationService
from research_harness.errors import NotFoundError


class GoldenDemoFacade:
    _PRIVATE_PATH_KEYS = {"path", "file_path", "artifact_path", "workspace", "workspace_path", "root", "root_path"}

    def __init__(self, workspace: str | Path):
        self.workspace = (Path(workspace).resolve() / "public-golden-demo").resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.pointer = self.workspace / "gui-golden-demo-latest.json"

    @staticmethod
    def _public(value):
        if isinstance(value, dict):
            return {key: GoldenDemoFacade._public(item) for key, item in value.items()
                    if key.lower() not in GoldenDemoFacade._PRIVATE_PATH_KEYS}
        if isinstance(value, list):
            return [GoldenDemoFacade._public(item) for item in value]
        return value

    def latest_run_id(self) -> str | None:
        if not self.pointer.exists():
            return None
        try:
            value = json.loads(self.pointer.read_text(encoding="utf-8"))
            run_id = value.get("run_id") if isinstance(value, dict) else None
        except (OSError, json.JSONDecodeError):
            raise InvestigationError("RH_GOLDEN_DEMO_STATE", "saved demo state is unreadable") from None
        if not isinstance(run_id, str) or not re.fullmatch(r"inv-[0-9a-f]{12}", run_id):
            raise InvestigationError("RH_GOLDEN_DEMO_STATE", "saved demo state is invalid")
        return run_id

    def run(self) -> dict:
        with InvestigationService(self.workspace) as service:
            outcome = run_golden_demo(str(self.workspace), service)
            run_id = outcome["run_id"]
            temp = self.pointer.with_suffix(".tmp")
            temp.write_text(json.dumps({"run_id": run_id}), encoding="utf-8")
            temp.replace(self.pointer)
            return self._envelope(service, run_id)

    def read(self, run_id: str | None = None) -> dict:
        run_id = run_id or self.latest_run_id()
        if run_id is None:
            return {"schema_version": "1", "demo": None}
        if not isinstance(run_id, str) or not re.fullmatch(r"inv-[0-9a-f]{12}", run_id):
            raise InvestigationError("RH_RUN_NOT_FOUND", "demo run was not found")
        with InvestigationService(self.workspace) as service:
            try:
                return self._envelope(service, run_id)
            except NotFoundError:
                raise InvestigationError("RH_RUN_NOT_FOUND", "demo run was not found") from None

    def _envelope(self, service: InvestigationService, run_id: str) -> dict:
        row = service._run(run_id)
        result = service.get_result(run_id)
        report_data = service.build_report_data(run_id)
        report_root = (self.workspace / "reports").resolve()
        reports = []
        expected_reports = {("technical_report", "en"), ("literature_review", "en")}
        for artifact in result.get("artifacts", []):
            if artifact.get("format") != "markdown" or artifact.get("type") not in {"technical_report", "literature_review"}:
                continue
            candidate = (self.workspace / str(artifact.get("path", ""))).resolve()
            try:
                candidate.relative_to(report_root)
            except ValueError:
                raise InvestigationError("RH_GOLDEN_DEMO_REPORT_ARTIFACT", "an exported demo report is outside the report area") from None
            if not candidate.is_file():
                raise InvestigationError("RH_GOLDEN_DEMO_REPORT_ARTIFACT", "an expected exported demo report is unavailable")
            language = artifact.get("language", "en")
            reports.append({"type": artifact["type"], "language": language,
                            "format": "markdown", "content": candidate.read_text(encoding="utf-8")})
        available_reports = {(report["type"], report["language"]) for report in reports}
        if not expected_reports <= available_reports:
            raise InvestigationError("RH_GOLDEN_DEMO_REPORT_ARTIFACT", "an expected exported demo report is unavailable")
        return {"schema_version": "1", "demo": {
            "workspace_label": "Golden Demo", "run_id": run_id,
            "status": self._public(service.status(run_id)),
            "spec": self._public(json.loads(row["spec"])),
            "result": self._public(result),
            "report_data": self._public(report_data),
            "reports": reports,
        }}
