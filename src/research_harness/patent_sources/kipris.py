"""KIPRIS Plus boundary: documented HTTP examples are never sent credentials."""
from __future__ import annotations
from typing import Any
from .contracts import SourceContext, pending

SOURCE = "kipris_plus"
SPEC_URL = "https://plus.kipris.or.kr/portal/popup/DBII_000000000000001/SC002/ADI_0000000000002944/apiDescriptionSearch.do"
SERVICE_URL = "https://plus.kipris.or.kr/eng/popup/service/DBII_000000000000001/view.do"
SPEC_VERSION = "official KIPRIS Plus API description; captured 2026-10-05"
CAPABILITY = "patent_search"
# Official examples currently document this exact HTTP operation, including the
# ServiceKey query parameter. It is metadata only: this adapter never dispatches it.
DOCUMENTED_HTTP = {
    "method": "GET",
    "base_url": "http://plus.kipris.or.kr/kipo-api/kipi/patUtiModInfoSearchSevice/",
    "operation": "getAdvancedSearch",
    "parameters": ("word", "inventionTitle", "astrtCont", "claimScope", "ipcNumber",
                   "applicationNumber", "openNumber", "publicationNumber",
                   "registerNumber", "priorityApplicationNumber", "ServiceKey"),
}
OPERATIONS = {"advanced_search", "bibliography", "publication_full_text", "announcement_full_text"}

class KIPRISAdapter:
    def __init__(self, context: SourceContext, *, enabled: bool = False, api_key_env: str = "KIPRIS_SERVICE_KEY"):
        self.context, self.enabled, self.api_key_env = context, enabled, api_key_env

    def diagnose(self) -> dict[str, Any]:
        import os
        return {"source": SOURCE, "status": "pending_activation" if not self.enabled else "pending_secure_transport",
                "capability": CAPABILITY, "capability_granted": CAPABILITY in self.context.capabilities,
                "credential_configured": bool(os.environ.get(self.api_key_env)),
                "official_references": [SPEC_URL, SERVICE_URL], "spec_version": SPEC_VERSION,
                "documented_http_contract": {**DOCUMENTED_HTTP, "parameters": list(DOCUMENTED_HTTP["parameters"])},
                "dispatch_enabled": False,
                "reason": "official request examples specify HTTP only; no credential or query is dispatched until an official HTTPS request contract is verified"}

    def execute(self, operation: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if operation not in OPERATIONS:
            return pending(SOURCE, str(operation), "pending_spec", "RH_KIPRIS_OPERATION_PENDING", "operation is not in the documented KIPRIS connector boundary", CAPABILITY)
        if not self.enabled:
            return pending(SOURCE, operation, "pending_activation", "RH_KIPRIS_DISABLED", "KIPRIS connector is disabled", CAPABILITY)
        if CAPABILITY not in self.context.capabilities:
            return pending(SOURCE, operation, "unsupported", "RH_PATENT_CAPABILITY", "patent search capability was not granted", CAPABILITY)
        return pending(SOURCE, operation, "pending_secure_transport", "RH_KIPRIS_HTTPS_UNCONFIRMED", "official request contract confirms HTTP examples only; no request is sent", CAPABILITY)
