from ..llm.provider import extract_fields
from ..observability.metrics import TOOL_CALLS, EXTRACTION_FIELDS
from ..observability.tracing import span

REQUIRED_FIELDS_BY_TYPE = {
    "passport": ("full_name", "date_of_birth", "document_number", "expiry_date"),
    "driving_licence": ("full_name", "date_of_birth", "document_number", "expiry_date"),
    "national_id": ("full_name", "date_of_birth", "document_number"),
    "proof_of_address": ("address",),
}

def extract_document_fields(document_text: str, document_type: str):
    with span("tool.extract_document_fields", {"tool.name": "extract_document_fields", "document.type": document_type}):
        try:
            fields, usage = extract_fields(document_text, document_type)
            data = fields.model_dump()
            required = REQUIRED_FIELDS_BY_TYPE.get(document_type, REQUIRED_FIELDS_BY_TYPE["passport"])
            missing = []
            for field in required:
                outcome = "present" if data.get(field) else "missing"
                EXTRACTION_FIELDS.labels(field, outcome).inc()
                if outcome == "missing":
                    missing.append(field)
            TOOL_CALLS.labels("extract_document_fields", "success").inc()
            return {"fields": data, "required_fields": list(required), "missing_required_fields": missing, "usage": usage}
        except Exception:
            TOOL_CALLS.labels("extract_document_fields", "failure").inc()
            raise
