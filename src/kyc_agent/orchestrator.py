import time
from datetime import date
from .audit.store import add_event,save_result,get_documents,get_application,add_document,update_document_status,get_slo_counts
from .observability.tracing import span
from .observability.metrics import REQUESTS,REQUEST_LATENCY,MANUAL_REVIEW,APPLICATION_DECISIONS,DOCUMENTS_RECEIVED,ONBOARDING_SLO
from .security.pii import redact_text
from .tools.document_extraction import extract_document_fields
from .tools.address_verification import verify_address
from .tools.risk_rating import assign_preliminary_risk
from .rag.vectorstore import search_knowledge

def expiry_check(value):
    if not value:return {"status":"NOT_CHECKED","reason":"expiry_date_missing"}
    try: expiry=date.fromisoformat(value.strip())
    except ValueError:return {"status":"INVALID_FORMAT","reason":"expiry_date_not_iso"}
    return {"status":"EXPIRED" if expiry<date.today() else "VALID","reason":"document_expired" if expiry<date.today() else "not_expired"}

def process_application(applicant_id,request):
    started=time.perf_counter()
    with span("kyc.process_application",{"kyc.workflow":"account_opening"}):
      try:
        if request.document_text:
            _,redaction_counts=redact_text(request.document_text)
            stored=add_document(applicant_id,request.document_type,request.document_text,request.vendor_version)
            DOCUMENTS_RECEIVED.labels(request.document_type).inc()
            add_event(applicant_id,"DOCUMENT_RECEIVED",{"document_id":stored["document_id"],"document_type":request.document_type,"vendor_version":request.vendor_version,"pii_redaction_counts":redaction_counts})
        application=get_application(applicant_id); docs=[d for d in get_documents(applicant_id) if d["status"]!="SUPERSEDED"]
        if not docs:raise ValueError("No documents are registered. Submit at least one document before processing.")
        identity_types={"passport","driving_licence","national_id"}
        if not any(d["document_type"] in identity_types for d in docs):
            raise ValueError("An identity document is required (passport, driving_licence or national_id).")
        per_doc=[]; aggregate={}; missing=[]; usage=[]
        for doc in docs:
            extracted=extract_document_fields(doc["document_text"],doc["document_type"]); fields=extracted["fields"]; usage.append(extracted["usage"])
            for k,v in fields.items():
                if v and not aggregate.get(k):aggregate[k]=v
            expiry=expiry_check(fields.get("expiry_date")); missing.extend([f"{doc['document_type']}:{x}" for x in extracted["missing_required_fields"]])
            status="VERIFIED" if not extracted["missing_required_fields"] and expiry["status"] in ("VALID","NOT_CHECKED") else "NEEDS_REVIEW"
            if expiry["status"] in ("EXPIRED","INVALID_FORMAT"):status="NEEDS_REVIEW"
            update_document_status(doc["document_id"],status)
            per_doc.append({"document_id":doc["document_id"],"document_type":doc["document_type"],"status":status,"extracted_fields":fields,"missing_required_fields":extracted["missing_required_fields"],"expiry_check":expiry,"vendor_version":doc["vendor_version"]})
            add_event(applicant_id,"DOCUMENT_CHECK_COMPLETED",{"document_id":doc["document_id"],"document_type":doc["document_type"],"status":status,"missing_required_fields":extracted["missing_required_fields"],"expiry_check":expiry})
        addr=next((x["extracted_fields"].get("address") for x in per_doc if x["document_type"]=="proof_of_address" and x["extracted_fields"].get("address")),None) or aggregate.get("address")
        address=verify_address(addr,request.address_text or application.get("application_address"))
        risk=assign_preliminary_risk(aggregate,address,missing)
        if any(x["expiry_check"]["status"] in ("EXPIRED","INVALID_FORMAT") for x in per_doc):
            risk.update({"workflow_status":"MANUAL_REVIEW","preliminary_risk_band":"REVIEW"})
            risk["reason_codes"]=list(set(risk["reason_codes"]+["document_expired_or_invalid_expiry"]))
        policy=search_knowledge("account opening KYC document requirements address verification expiry and escalation guidance")
        inventory=[{"document_id":x["document_id"],"document_type":x["document_type"],"status":x["status"],"vendor_version":x["vendor_version"]} for x in per_doc]
        result={"applicant_id":applicant_id,"workflow_status":risk["workflow_status"],"document_inventory":inventory,"documents_checked":per_doc,"extracted_fields":aggregate,"missing_required_fields":missing,"address_verification":address,"preliminary_assessment":risk,"retrieved_policy_context":policy,"vendor_versions":sorted({x["vendor_version"] for x in docs}),"llm_usage":usage,"human_review_required":True,"disclaimer":"Training demo only. Preliminary onboarding assessment, not account-opening approval. Human review and approved identity checks are mandatory."}
        save_result(applicant_id,result)
        add_event(applicant_id,"APPLICATION_DECISION_RECORDED",{"workflow_status":risk["workflow_status"],"preliminary_risk_band":risk["preliminary_risk_band"],"documents_count":len(docs),"address_status":address["status"],"policy_chunks_retrieved":len(policy)})
        APPLICATION_DECISIONS.labels(risk["workflow_status"]).inc()
        slo=get_slo_counts()
        if slo["slo_attainment"] is not None:ONBOARDING_SLO.set(slo["slo_attainment"])
        if risk["workflow_status"] in ("MANUAL_REVIEW","NEEDS_MORE_INFORMATION"):MANUAL_REVIEW.labels(risk["workflow_status"]).inc()
        REQUESTS.labels("success").inc(); return result
      except Exception as exc:
        REQUESTS.labels("failure").inc(); add_event(applicant_id,"ONBOARDING_PROCESSING_FAILED",{"error_type":type(exc).__name__}); raise
      finally:REQUEST_LATENCY.observe(time.perf_counter()-started)
