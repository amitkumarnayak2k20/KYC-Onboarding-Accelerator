from ..observability.metrics import TOOL_CALLS
from ..observability.tracing import span

def verify_address(extracted_address: str | None, supplied_address: str | None):
    with span("tool.verify_address", {"tool.name": "verify_address"}):
        if not extracted_address or not supplied_address:
            result = {"status": "inconclusive", "match": False, "reason": "address_missing"}
        else:
            a = " ".join(extracted_address.casefold().split())
            b = " ".join(supplied_address.casefold().split())
            match = a == b
            result = {"status": "matched" if match else "mismatch", "match": match,
                      "reason": "exact_normalized_match" if match else "address_mismatch"}
        TOOL_CALLS.labels("verify_address", "success").inc()
        return result
