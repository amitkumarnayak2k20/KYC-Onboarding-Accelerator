import os, re, shutil
from pathlib import Path
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from .config import settings
from .schemas import ApplicationCreate, ProcessRequest, EvaluationRequest, DocumentSubmission, DocumentRequestCreate
from .audit.store import (create_application,get_application,get_events,add_event,add_document,get_documents,
    create_document_request,get_document_requests,get_slo_counts,list_applications,update_application,supersede_documents)
from .orchestrator import process_application
from .evaluation.evaluator import run_evaluation,run_degraded_evaluation
from .drift.detector import status as drift_status,reset as reset_drift
from .observability.tracing import init_tracing
from .observability.metrics import DOCUMENTS_RECEIVED,DOCUMENT_REQUESTS,DUPLICATE_REQUESTS_PREVENTED,ONBOARDING_SLO
from .rag.vectorstore import search_knowledge, build_vectorstore, DOCS_DIR
from .agent import chat as agent_chat
from .security.pii import redact_text
from .schemas import DocumentSubmission

init_tracing()
app=FastAPI(title="Onboarding Accelerator — Account-Opening & KYC Agent",version=settings.app_version,
    description="Copilot-style account-opening and KYC training application. Synthetic data only; human review required.")
@app.get("/metrics", include_in_schema=False)
def metrics_endpoint():
    """Expose Prometheus metrics from the default prometheus_client registry."""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


@app.get("/health")
def health(): return {"status":"ok","service":settings.app_name,"version":settings.app_version}

@app.post("/chat")
def chat_endpoint(payload: dict):
    message=str(payload.get("message", ""))[:4000]
    return agent_chat(message)

@app.get("/applications")
def applications_endpoint(status: str|None=None, limit: int=100):
    return {"applications":list_applications(status=status,limit=min(max(limit,1),200))}

@app.post("/applications",status_code=201)
def create_application_endpoint(payload:ApplicationCreate):
    try: create_application(payload.applicant_id,payload.full_name,redact_text(payload.email or "")[0],payload.application_address)
    except Exception as exc:
        if "UNIQUE constraint failed" in str(exc): raise HTTPException(409,"Applicant ID already exists")
        raise
    add_event(payload.applicant_id,"APPLICATION_CREATED",{"application_address_supplied":bool(payload.application_address)})
    return {"applicant_id":payload.applicant_id,"status":"CREATED"}

@app.patch("/applications/{applicant_id}")
def patch_application_endpoint(applicant_id:str,payload:dict):
    if not get_application(applicant_id): raise HTTPException(404,"Application not found")
    name=payload.get("full_name"); address=payload.get("application_address")
    if name is not None and (not isinstance(name,str) or not 2<=len(name.strip())<=120): raise HTTPException(400,"Invalid full_name")
    if address is not None and (not isinstance(address,str) or not address.strip()): raise HTTPException(400,"Invalid application_address")
    update_application(applicant_id,full_name=name.strip() if name else None,application_address=address.strip() if address else None)
    add_event(applicant_id,"APPLICATION_UPDATED",{"full_name_changed":name is not None,"address_changed":address is not None})
    return {"applicant_id":applicant_id,"status":"UPDATED"}

@app.get("/applications/{applicant_id}")
def get_application_endpoint(applicant_id:str):
    x=get_application(applicant_id)
    if not x: raise HTTPException(404,"Application not found")
    return x

@app.post("/applications/{applicant_id}/documents",status_code=201)
def submit_document_endpoint(applicant_id:str,payload:DocumentSubmission):
    if not get_application(applicant_id): raise HTTPException(404,"Application not found")
    x=add_document(applicant_id,payload.document_type,payload.document_text,payload.vendor_version,payload.source_filename)
    DOCUMENTS_RECEIVED.labels(payload.document_type).inc()
    add_event(applicant_id,"DOCUMENT_RECEIVED",{"document_id":x["document_id"],"document_type":payload.document_type,"vendor_version":payload.vendor_version,"source_filename":payload.source_filename})
    return x

def _extract_uploaded_text(filename: str, data: bytes) -> str:
    ext=Path(filename).suffix.lower()
    if ext==".pdf":
        from pypdf import PdfReader
        import io
        reader=PdfReader(io.BytesIO(data)); text="\n".join(page.extract_text() or "" for page in reader.pages)
    elif ext==".docx":
        from docx import Document
        import io
        doc=Document(io.BytesIO(data)); text="\n".join(p.text for p in doc.paragraphs)
    elif ext in {".txt", ".md", ".csv"}:
        text=data.decode("utf-8",errors="replace")
    else:
        raise HTTPException(415,"Supported applicant document formats: PDF (text-based), DOCX, TXT and MD. Scanned-image OCR is not configured in this training build.")
    if len(text.strip())<10:
        raise HTTPException(422,"No readable text found. This may be a scanned document; connect an approved OCR provider or upload a text-based synthetic sample.")
    if len(data)>8*1024*1024: raise HTTPException(413,"File exceeds the 8 MB training limit")
    return text[:30000]

@app.post("/applications/{applicant_id}/documents/upload",status_code=201)
async def upload_applicant_document(applicant_id:str, document_type:str=Form(...), file:UploadFile=File(...), vendor_version:str=Form("ocr-v1")):
    if not get_application(applicant_id): raise HTTPException(404,"Application not found")
    allowed={"passport","driving_licence","national_id","proof_of_address"}
    if document_type not in allowed: raise HTTPException(400,"Unsupported document_type")
    data=await file.read()
    if len(data)>8*1024*1024: raise HTTPException(413,"File exceeds the 8 MB training limit")
    content=_extract_uploaded_text(file.filename or "upload.txt",data)
    previous_ids=supersede_documents(applicant_id,document_type)
    stored=add_document(applicant_id,document_type,content,vendor_version,file.filename)
    DOCUMENTS_RECEIVED.labels(document_type).inc()
    add_event(applicant_id,"DOCUMENT_RECEIVED",{"document_id":stored["document_id"],"document_type":document_type,"source_filename":file.filename,"vendor_version":vendor_version,"replaced_document_ids":previous_ids})
    if previous_ids: add_event(applicant_id,"DOCUMENT_REPLACED",{"document_type":document_type,"new_document_id":stored["document_id"],"superseded_document_ids":previous_ids})
    return stored

@app.get("/applications/{applicant_id}/documents")
def list_document_endpoint(applicant_id:str):
    if not get_application(applicant_id): raise HTTPException(404,"Application not found")
    return {"applicant_id":applicant_id,"documents":[{k:v for k,v in d.items() if k!="document_text"} for d in get_documents(applicant_id)]}

@app.post("/applications/{applicant_id}/document-requests")
def request_document_endpoint(applicant_id:str,payload:DocumentRequestCreate):
    if not get_application(applicant_id): raise HTTPException(404,"Application not found")
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
    add_event(applicant_id,event,{"document_type":payload.document_type,"request_id":req["request_id"],"reason":payload.reason,"previously_supplied":bool(docs)})
    return {"request":req,"sent_to_customer":True,"message":"Request recorded; this demo does not send an actual customer notification."}

@app.get("/applications/{applicant_id}/document-requests")
def document_requests_endpoint(applicant_id:str):
    if not get_application(applicant_id): raise HTTPException(404,"Application not found")
    return {"applicant_id":applicant_id,"requests":get_document_requests(applicant_id)}

@app.post("/applications/{applicant_id}/process")
def process_endpoint(applicant_id:str,payload:ProcessRequest=ProcessRequest()):
    if not get_application(applicant_id): raise HTTPException(404,"Application not found")
    try: return process_application(applicant_id,payload)
    except ValueError as exc: raise HTTPException(400,str(exc))
    except Exception as exc: raise HTTPException(502,f"Onboarding processing failed: {type(exc).__name__}")

@app.get("/applications/{applicant_id}/audit")
def audit_endpoint(applicant_id:str):
    if not get_application(applicant_id): raise HTTPException(404,"Application not found")
    return {"applicant_id":applicant_id,"events":get_events(applicant_id)}

@app.post("/guidelines/upload")
async def upload_guideline(file:UploadFile=File(...)):
    allowed={".pdf",".docx",".html",".htm",".csv",".json",".txt",".md"}
    name=Path(file.filename or "guideline.txt").name
    ext=Path(name).suffix.lower()
    if ext not in allowed: raise HTTPException(415,"Supported guideline formats: PDF, DOCX, HTML, CSV, JSON, TXT, MD")
    data=await file.read()
    if len(data)>15*1024*1024: raise HTTPException(413,"Guideline file exceeds 15 MB")
    DOCS_DIR.mkdir(parents=True,exist_ok=True)
    safe=re.sub(r"[^A-Za-z0-9._-]","_",name)
    target=DOCS_DIR/safe
    target.write_bytes(data)
    try:
        result=build_vectorstore()
        return {"status":"INDEXED","file":safe,"index":result}
    except Exception as exc:
        return {"status":"UPLOADED_NOT_INDEXED","file":safe,"error":type(exc).__name__,
                "message":"The file was saved, but indexing failed. Check OPENAI_API_KEY and the document format, then rebuild the index."}

@app.get("/guidelines")
def guidelines_endpoint():
    DOCS_DIR.mkdir(parents=True,exist_ok=True)
    return {"documents":[{"name":p.name,"size_bytes":p.stat().st_size} for p in sorted(DOCS_DIR.iterdir()) if p.is_file()]}

@app.get("/slo/summary")
def slo_summary_endpoint():
    result=get_slo_counts()
    if result["slo_attainment"] is not None: ONBOARDING_SLO.set(result["slo_attainment"])
    result["target_example"]=0.95
    result["definition"]="Applications reaching a preliminary decision without a duplicate request for a document already received or verified."
    return result

@app.post("/evaluation/run")
def evaluation_endpoint(payload:EvaluationRequest|None=None): return run_evaluation(payload.sample_ids if payload else None)
@app.get("/drift/status")
def drift_endpoint(): return drift_status()
@app.post("/demo/ocr-degradation")
def demo_degradation_endpoint():
    reset_drift(); evaluation=run_degraded_evaluation(repetitions=4)
    return {"incident":"simulated_ocr_quality_regression","evaluation":evaluation,"drift":drift_status()}
@app.get("/knowledge/search")
def knowledge_search_endpoint(q:str,top_k:int=4):
    if top_k<1 or top_k>10: raise HTTPException(400,"top_k must be between 1 and 10")
    try: return {"query":q,"results":search_knowledge(q,n_results=top_k)}
    except Exception as exc: raise HTTPException(502,f"Knowledge search failed: {type(exc).__name__}")


# Mount the single-page frontend last so API routes retain precedence.
UI_DIR=Path(__file__).resolve().parents[2]/"ui"
if UI_DIR.exists(): app.mount("/",StaticFiles(directory=str(UI_DIR),html=True),name="ui")
