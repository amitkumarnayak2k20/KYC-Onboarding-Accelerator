from fastapi import FastAPI,HTTPException
from prometheus_client import make_asgi_app
from .config import settings
from .schemas import ApplicationCreate,ProcessRequest,EvaluationRequest,DocumentSubmission,DocumentRequestCreate
from .audit.store import create_application,get_application,get_events,add_event,add_document,get_documents,create_document_request,get_document_requests,get_slo_counts
from .orchestrator import process_application
from .evaluation.evaluator import run_evaluation,run_degraded_evaluation
from .drift.detector import status as drift_status,reset as reset_drift
from .observability.tracing import init_tracing
from .observability.metrics import DOCUMENTS_RECEIVED,DOCUMENT_REQUESTS,DUPLICATE_REQUESTS_PREVENTED,ONBOARDING_SLO
from .rag.vectorstore import search_knowledge
init_tracing()
app=FastAPI(title="Onboarding Accelerator — Account-Opening & KYC Agent",version=settings.app_version,description="Synthetic-data training capstone; human review required.")
app.mount("/metrics",make_asgi_app())

@app.get("/health")
def health():return {"status":"ok","service":settings.app_name,"version":settings.app_version}

@app.post("/applications",status_code=201)
def create_application_endpoint(payload:ApplicationCreate):
    from .security.pii import redact_text
    try:create_application(payload.applicant_id,payload.full_name,redact_text(payload.email or "")[0],payload.application_address)
    except Exception as exc:
        if "UNIQUE constraint failed" in str(exc):raise HTTPException(409,"Applicant ID already exists")
        raise
    add_event(payload.applicant_id,"APPLICATION_CREATED",{"application_address_supplied":bool(payload.application_address)})
    return {"applicant_id":payload.applicant_id,"status":"CREATED"}

@app.get("/applications/{applicant_id}")
def get_application_endpoint(applicant_id:str):
    x=get_application(applicant_id)
    if not x:raise HTTPException(404,"Application not found")
    return x

@app.post("/applications/{applicant_id}/documents",status_code=201)
def submit_document_endpoint(applicant_id:str,payload:DocumentSubmission):
    if not get_application(applicant_id):raise HTTPException(404,"Application not found")
    x=add_document(applicant_id,payload.document_type,payload.document_text,payload.vendor_version,payload.source_filename)
    DOCUMENTS_RECEIVED.labels(payload.document_type).inc()
    add_event(applicant_id,"DOCUMENT_RECEIVED",{"document_id":x["document_id"],"document_type":payload.document_type,"vendor_version":payload.vendor_version,"source_filename":payload.source_filename})
    return x

@app.get("/applications/{applicant_id}/documents")
def list_documents_endpoint(applicant_id:str):
    if not get_application(applicant_id):raise HTTPException(404,"Application not found")
    return {"applicant_id":applicant_id,"documents":[{k:v for k,v in d.items() if k!="document_text"} for d in get_documents(applicant_id)]}

@app.post("/applications/{applicant_id}/document-requests")
def request_document_endpoint(applicant_id:str,payload:DocumentRequestCreate):
    if not get_application(applicant_id):raise HTTPException(404,"Application not found")
    docs=[d for d in get_documents(applicant_id) if d["document_type"]==payload.document_type]
    usable=[d for d in docs if d["status"] in ("RECEIVED","VERIFIED")]
    if usable:
        DUPLICATE_REQUESTS_PREVENTED.labels(payload.document_type).inc()
        req=create_document_request(applicant_id,payload.document_type,payload.reason,"BLOCKED_DUPLICATE")
        add_event(applicant_id,"DUPLICATE_DOCUMENT_REQUEST_BLOCKED",{"document_type":payload.document_type,"existing_document_ids":[d["document_id"] for d in usable],"request_id":req["request_id"],"reason":payload.reason})
        return {"request":req,"sent_to_customer":False,"message":"Blocked: this document has already been received or verified."}
    req=create_document_request(applicant_id,payload.document_type,payload.reason,"SENT")
    DOCUMENT_REQUESTS.labels(payload.document_type).inc()
    event="DOCUMENT_RESUBMISSION_REQUESTED" if docs else "DOCUMENT_REQUEST_SENT"
    add_event(applicant_id,event,{"document_type":payload.document_type,"request_id":req["request_id"],"reason":payload.reason,"previously_supplied":bool(docs),"previous_statuses":[d["status"] for d in docs]})
    return {"request":req,"sent_to_customer":True,"message":"Request recorded; this demo does not send an actual customer notification."}

@app.get("/applications/{applicant_id}/document-requests")
def list_document_requests_endpoint(applicant_id:str):
    if not get_application(applicant_id):raise HTTPException(404,"Application not found")
    return {"applicant_id":applicant_id,"requests":get_document_requests(applicant_id)}

@app.post("/applications/{applicant_id}/process")
def process_endpoint(applicant_id:str,payload:ProcessRequest=ProcessRequest()):
    if not get_application(applicant_id):raise HTTPException(404,"Application not found")
    try:return process_application(applicant_id,payload)
    except ValueError as exc:raise HTTPException(400,str(exc))
    except Exception as exc:raise HTTPException(502,f"Onboarding processing failed: {type(exc).__name__}")

@app.get("/applications/{applicant_id}/audit")
def audit_endpoint(applicant_id:str):
    if not get_application(applicant_id):raise HTTPException(404,"Application not found")
    return {"applicant_id":applicant_id,"events":get_events(applicant_id)}

@app.get("/slo/summary")
def slo_summary_endpoint():
    result=get_slo_counts()
    if result["slo_attainment"] is not None:ONBOARDING_SLO.set(result["slo_attainment"])
    result["target_example"]=0.95
    result["definition"]="Applications reaching a preliminary decision without a duplicate request for a document already received or verified."
    return result

@app.post("/evaluation/run")
def evaluation_endpoint(payload:EvaluationRequest|None=None):return run_evaluation(payload.sample_ids if payload else None)
@app.get("/drift/status")
def drift_endpoint():return drift_status()
@app.post("/demo/ocr-degradation")
def demo_degradation_endpoint():
    reset_drift(); evaluation=run_degraded_evaluation(repetitions=4)
    return {"incident":"simulated_ocr_quality_regression","evaluation":evaluation,"drift":drift_status(),"message":"Synthetic DOB regression; inspect drift and Prometheus metrics."}
@app.get("/knowledge/search")
def knowledge_search_endpoint(q:str,top_k:int=4):
    if top_k<1 or top_k>10:raise HTTPException(400,"top_k must be between 1 and 10")
    try:
        results=search_knowledge(q,n_results=top_k)
        return {"query":q,"results":results,"message":"OK" if results else "No indexed knowledge found; build the vector store and configure OPENAI_API_KEY."}
    except Exception as exc:raise HTTPException(502,f"Knowledge search failed: {type(exc).__name__}")
