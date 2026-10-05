"""GPSS capability diagnostics; business routes remain pending_spec."""
from __future__ import annotations
from typing import Any
from .contracts import SourceContext, pending

SOURCE = "tipo_gpss"
SPEC_URL = "https://www.tipo.gov.tw/wSite/public/Attachment/007/f1744687672229.pdf"
SPEC_VERSION = "official GPSS API introduction; detailed business API schema unavailable"
CAPABILITY = "patent_search"
OPERATIONS = {"query": "patent search", "case_lookup": "case lookup", "document_lookup": "document lookup"}

class GPSSAdapter:
    def __init__(self, context: SourceContext, *, enabled: bool = False, spec_configured: bool = False):
        self.context, self.enabled, self.spec_configured = context, enabled, spec_configured

    def diagnose(self) -> dict[str, Any]:
        return {"source": SOURCE, "status": "pending_activation" if not self.enabled else "pending_spec",
                "capability": CAPABILITY, "capability_granted": CAPABILITY in self.context.capabilities,
                "official_reference": SPEC_URL, "spec_version": SPEC_VERSION,
                "spec_configured": self.spec_configured, "dispatch_enabled": False,
                "operations": sorted(OPERATIONS)}

    def execute(self, operation: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if operation not in OPERATIONS:
            return pending(SOURCE, str(operation), "pending_spec", "RH_GPSS_OPERATION_PENDING", "operation is not part of the diagnostic capability contract", CAPABILITY)
        if not self.enabled:
            return pending(SOURCE, operation, "pending_activation", "RH_GPSS_DISABLED", "GPSS connector is disabled", CAPABILITY)
        if CAPABILITY not in self.context.capabilities:
            return pending(SOURCE, operation, "unsupported", "RH_PATENT_CAPABILITY", "patent search capability was not granted", CAPABILITY)
        return pending(SOURCE, operation, "pending_spec", "RH_GPSS_SPEC_MISSING", "official introduction confirms a query API but does not define request/response routes or fields", CAPABILITY)
