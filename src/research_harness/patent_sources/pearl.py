"""WIPO Pearl connector boundary; route remains pending until an official API spec is supplied."""
from __future__ import annotations

from typing import Any

from .contracts import SourceContext, pending


SOURCE = "wipo_pearl"
SPEC_URL = "https://www.wipo.int/en/web/wipo-pearl/w/news/2026/wipo-pearl-api-for-terminology-now-available-in-a-new-platform"
PLATFORM_URL = "https://b2b.wipo.int"
SPEC_CAPTURE_DATE = "2026-09-04"
SPEC_EVIDENCE = {
    "migration_announcement": SPEC_URL,
    "announcement_capture_date": SPEC_CAPTURE_DATE,
    "platform_entry": PLATFORM_URL,
    "local_b2b_shell": "sha256:fb660dc54033320dd2b7eb5e50d709d3247736417de39ad7e4610e96aae97335",
    "note": "Announcement confirms migration to a new platform; local shell and platform entry do not define business request/response routes, so every operation remains pending_spec.",
}
OPERATIONS = {"term_search", "multilingual_search", "record_query"}
CAPABILITY = "terminology_search"


class PearlAdapter:
    """Expose activation diagnostics without inventing WIPO Pearl endpoints."""

    def __init__(self, context: SourceContext, *, enabled: bool, spec_configured: bool = False):
        self.context, self.enabled, self.spec_configured = context, enabled, spec_configured

    def diagnose(self) -> dict[str, Any]:
        status = "pending_activation" if self.enabled is not True else "pending_spec"
        code = "RH_PEARL_DISABLED" if status == "pending_activation" else "RH_PEARL_SPEC_MISSING"
        message = "WIPO Pearl connector is disabled" if status == "pending_activation" else "no WIPO Pearl business API specification is configured; no route is registered"
        return {"source": SOURCE, "status": status, "spec_configured": self.spec_configured,
                "capability": CAPABILITY, "capability_granted": CAPABILITY in self.context.capabilities,
                "official_reference": SPEC_URL, "platform_entry": PLATFORM_URL, "spec_evidence": SPEC_EVIDENCE, "operations": {
                    name: {"status": status, "code": code, "message": message} for name in sorted(OPERATIONS)}}

    def execute(self, operation: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not isinstance(operation, str) or not operation:
            return pending(SOURCE, "", "error", "RH_PEARL_OPERATION", "operation must be a non-empty string")
        if operation not in OPERATIONS:
            return pending(SOURCE, operation, "pending_spec", "RH_PEARL_OPERATION_PENDING", "operation is not part of the explicitly pending Pearl contract")
        if self.enabled is not True:
            return pending(SOURCE, operation, "pending_activation", "RH_PEARL_DISABLED", "WIPO Pearl connector is disabled", CAPABILITY)
        if CAPABILITY not in self.context.capabilities:
            return pending(SOURCE, operation, "unsupported", "RH_PATENT_CAPABILITY", "terminology search capability was not granted", CAPABILITY)
        # A flag or credential alone cannot supply the missing request, language,
        # record, pagination, and licensing contract; never make a speculative call.
        return pending(SOURCE, operation, "pending_spec", "RH_PEARL_SPEC_MISSING",
                       "official WIPO Pearl business API request/response specification is not available", CAPABILITY)
