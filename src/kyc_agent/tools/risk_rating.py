from ..observability.metrics import TOOL_CALLS
from ..observability.tracing import span

def assign_preliminary_risk(fields: dict, address_result: dict, missing_fields: list[str]):
    # Transparent training triage rules, not a validated risk model.
    with span("tool.assign_risk_rating", {"tool.name": "assign_risk_rating"}):
        reasons = []
        if missing_fields:
            reasons.append("required_document_fields_missing")
        if address_result.get("status") == "mismatch":
            reasons.append("address_mismatch")
        if address_result.get("status") == "inconclusive":
            reasons.append("address_not_verified")
        if not fields.get("expiry_date"):
            reasons.append("document_expiry_unavailable")
        if reasons:
            band = "REVIEW"
            status = "MANUAL_REVIEW" if "address_mismatch" in reasons else "NEEDS_MORE_INFORMATION"
        else:
            band, status = "STANDARD", "READY_FOR_REVIEW"
        TOOL_CALLS.labels("assign_risk_rating", "success").inc()
        return {"preliminary_risk_band": band, "workflow_status": status,
                "reason_codes": reasons, "requires_human_review": True}
