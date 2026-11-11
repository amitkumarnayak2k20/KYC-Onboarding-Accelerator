import re, os
from .audit.store import (list_applications, get_application, get_documents, get_document_requests,
                          update_application, add_event)
from .rag.vectorstore import search_knowledge
from .orchestrator import process_application
from .schemas import ProcessRequest
from .config import settings
from .observability.metrics import LLM_TOKENS, LLM_COST
from .observability.cost import estimate_cost_usd
from .observability.tracing import span

APP_ID_RE = re.compile(r"\b(?:application|app)\s*(?:id)?\s*[:#-]?\s*([A-Za-z0-9_-]{3,64})\b", re.I)
KNOWN_ID_RE = re.compile(r"\b(APP[-_][A-Za-z0-9_-]+|KYC[-_][A-Za-z0-9_-]+)\b", re.I)


def _extract_id(message: str):
    m=KNOWN_ID_RE.search(message) or APP_ID_RE.search(message)
    return m.group(1) if m else None


def _pending_applications():
    apps=list_applications(limit=200)
    pending=[]
    for a in apps:
        status=(a.get("application_status") or "IN_PROGRESS").upper()
        # Fresh applications without a completed preliminary assessment are pending KYC.
        if not a.get("latest_result") or status in {"IN_PROGRESS","PENDING_KYC","NEEDS_MORE_INFORMATION","MANUAL_REVIEW"}:
            docs=get_documents(a["applicant_id"])
            pending.append({"applicant_id":a["applicant_id"],"full_name":a["full_name"],
                            "status":status,"documents_received":len(docs),
                            "created_at":a.get("created_at")})
    return pending



def _looks_like_policy_question(low: str, policy_terms: list[str]) -> bool:
    return any(term in low for term in policy_terms) or low.startswith(("what ", "which ", "who ", "how ", "can ", "is ", "are ", "does ", "do "))


def _prioritise_account_sources(question: str, hits: list[dict]) -> list[dict]:
    account_markers = {
        "student": "student_current_account", "classic": "classic_current_account",
        "joint": "joint_current_account", "basic": "basic_account", "savings": "savings_accounts",
    }
    preferred = next((marker for term, marker in account_markers.items() if term in question), None)
    if not preferred:
        return hits
    return sorted(hits, key=lambda h: (0 if preferred in h.get("source", "").lower() else 1,
                                       h.get("distance", 999)))


def _source_list(hits: list[dict]) -> list[dict]:
    seen = set()
    sources = []
    for hit in hits:
        key = (hit.get("source", "unknown"), hit.get("chunk_index", 0))
        if key not in seen:
            seen.add(key)
            sources.append({"source": key[0], "chunk_index": key[1]})
    return sources


def _generate_grounded_answer(question: str, evidence: list[dict]) -> tuple[str, dict]:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    from openai import OpenAI
    model = settings.openai_model
    evidence_text = "\n\n".join(
        f"[SOURCE: {item.get('source', 'unknown')} | CHUNK: {item.get('chunk_index', 0)}]\n{item.get('text', '')}"
        for item in evidence
    )
    system_prompt = (
        "You are a concise KYC policy assistant for a training application. "
        "Answer using ONLY the supplied guideline excerpts. Do not use prior knowledge or external facts. "
        "If the excerpts do not explicitly answer the question, say the uploaded guidelines do not specify it. "
        "Do not infer age limits, eligibility, mandatory documents, regulatory obligations, or bank policy. "
        "Do not claim document authenticity or sanctions/PEP/AML checks were performed. "
        "Give a direct answer in at most 120 words, using short bullets when useful. "
        "Do not include source filenames; the application displays source attribution separately. "
        "This is guidance for human review, not final account approval."
    )
    with span("llm.policy_answer", {"llm.provider": "openai", "llm.model": model,
                                    "rag.evidence_count": len(evidence)}):
        client = OpenAI(api_key=settings.openai_api_key)
        response = client.chat.completions.create(
            model=model, temperature=0, max_tokens=220,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Question: {question}\n\nRetrieved guideline excerpts:\n{evidence_text}"},
            ],
        )
    answer = (response.choices[0].message.content or "").strip()
    if not answer:
        raise RuntimeError("OpenAI returned an empty answer")
    usage = response.usage
    input_tokens = getattr(usage, "prompt_tokens", 0) or 0
    output_tokens = getattr(usage, "completion_tokens", 0) or 0
    LLM_TOKENS.labels("input", model).inc(input_tokens)
    LLM_TOKENS.labels("output", model).inc(output_tokens)
    cost = estimate_cost_usd(model, input_tokens, output_tokens)
    if cost is not None:
        LLM_COST.labels(model).inc(cost)
    return answer, {"model": model, "input_tokens": input_tokens,
                    "output_tokens": output_tokens, "estimated_cost_usd": cost}


def chat(message: str):
    text=message.strip()
    low=text.lower()
    if not text:
        return {"reply":"Please enter a request so I can help with account opening or KYC verification.","action":"none"}

    if any(k in low for k in ["what can you do","help","capabilities","how can you help"]):
        return {"reply":"I can help with three supported workflows: (1) start a new account-opening application and collect the required details/documents, (2) look up applications pending KYC or verify an existing application ID, and (3) update an existing applicant's name/address or replace a document. I can also answer questions grounded in the uploaded KYC guideline documents. I cannot approve an account or verify document authenticity independently.","action":"none"}

    if any(k in low for k in ["pending kyc","ids pending","pending applications","applications pending","awaiting kyc","kyc pending"]):
        items=_pending_applications()
        if not items:
            return {"reply":"There are currently no applications pending KYC verification in the application database.","action":"show_pending","applications":[]}
        lines=[f"• {x['applicant_id']} — {x['full_name']} — {x['status']} — {x['documents_received']} document(s)" for x in items]
        return {"reply":"I found these applications requiring KYC attention:\n"+"\n".join(lines),"action":"show_pending","applications":items}

    if any(k in low for k in ["open an account","open account","new account","start an application","apply for an account","fresh application"]):
        guidance=search_knowledge("new customer account opening prerequisites required identity document proof of address information")
        if guidance:
            snippets="\n\n".join(f"[{x['source']}] {x['text']}" for x in guidance[:3])
            reply="Let's start a new account-opening application. Please provide the applicant's full name, contact email, residential address, one accepted identity document (for example passport, driving licence or national ID) and proof of address if required by the applicable guideline. Upload the documents in the form that will open beside this chat.\n\nRelevant indexed guidance:\n"+snippets
        else:
            reply="Let's start a new account-opening application. For this training demo, prepare the applicant's full name, contact email, residential address, an identity document (passport, driving licence or national ID) and proof of address. The actual required documents must be confirmed against your bank-approved guidelines. Upload synthetic/sample documents only."
        return {"reply":reply,"action":"open_new_application"}

    applicant_id=_extract_id(text)
    if applicant_id and any(k in low for k in ["verify","run kyc","process kyc","check kyc","perform kyc"]):
        app=get_application(applicant_id)
        if not app:
            return {"reply":f"I couldn't find application {applicant_id}. Please check the ID or create the application first.","action":"none"}
        docs=get_documents(applicant_id)
        if not docs:
            return {"reply":f"Application {applicant_id} exists, but no documents have been submitted. Upload the required identity and address documents before running KYC verification.","action":"upload_document","application_id":applicant_id}
        try:
            result=process_application(applicant_id,ProcessRequest())
            return {"reply":f"KYC checks completed for {applicant_id}. Preliminary workflow status: {result['workflow_status']}. Preliminary risk: {result['preliminary_assessment']['preliminary_risk_band']}. Verification issues: {', '.join(x['code'] for x in result.get('verification_issues', [])) or 'None'}. Human review required for this case: {result['human_review_required']}. This is not final account approval.","action":"show_application","application_id":applicant_id,"result":result}
        except Exception as exc:
            return {"reply":f"I couldn't complete KYC processing for {applicant_id}: {type(exc).__name__}. Please inspect the application and audit events.","action":"show_application","application_id":applicant_id}

    if applicant_id and any(k in low for k in ["status","details","show application","application details","document status"]):
        app=get_application(applicant_id)
        if not app:
            return {"reply":f"Application {applicant_id} was not found.","action":"none"}
        docs=get_documents(applicant_id)
        status=app.get("application_status") or "IN_PROGRESS"
        return {"reply":f"Application {applicant_id} belongs to {app['full_name']}. Current status: {status}. Documents received: {len(docs)}. Use the application panel to inspect document inventory and audit history.","action":"show_application","application_id":applicant_id,"application":app}

    if applicant_id and any(k in low for k in ["change name","update name","modify name","rename"]):
        m=re.search(r"(?:change|update|modify)\s+(?:the\s+)?name\s+(?:to|as)\s+(.+)$",text,re.I)
        if m:
            new_name=re.sub(r"\s+(?:for|on)\s+(?:application|app)\s*(?:id\s*)?(?:[:#-]\s*)?[A-Za-z0-9_-]+$", "", m.group(1), flags=re.I).strip().strip(' .')
        else:
            new_name=""
        if not m or not new_name:
            return {"reply":f"I can update the name for {applicant_id}. Please phrase it as: 'Change name to [new full name] for application {applicant_id}'.","action":"none"}
        if len(new_name)<2 or len(new_name)>120:
            return {"reply":"Please provide a valid full name (2–120 characters).","action":"none"}
        if not get_application(applicant_id):
            return {"reply":f"Application {applicant_id} was not found.","action":"none"}
        update_application(applicant_id,full_name=new_name)
        add_event(applicant_id,"APPLICATION_NAME_UPDATED",{"new_full_name":new_name,"source":"copilot_chat"})
        docs=[d for d in get_documents(applicant_id) if d["status"]!="SUPERSEDED"]
        if docs:
            result=process_application(applicant_id,ProcessRequest())
            return {"reply":f"Updated the applicant name for {applicant_id} and automatically re-ran KYC. Result: {result['workflow_status']}. Issues: {', '.join(x['code'] for x in result.get('verification_issues', [])) or 'None'}.","action":"show_application","application_id":applicant_id,"result":result}
        return {"reply":f"Updated the applicant name for {applicant_id}. No active documents are available yet, so KYC will run automatically after document submission.","action":"show_application","application_id":applicant_id}

    if applicant_id and (any(k in low for k in ["change document","replace document","update document","upload new document","document change","replace passport","change passport","update passport","replace driving licence","replace national id","replace proof of address"]) or re.search(r"(?:replace|change|update)\s+(?:the\s+)?(?:passport|driving\s+licence|national\s+id|proof\s+of\s+address)", low)):
        if not get_application(applicant_id):
            return {"reply":f"Application {applicant_id} was not found.","action":"none"}
        return {"reply":f"Please select the replacement document type and upload the new file for {applicant_id}. The previous document and replacement event will remain auditable.","action":"upload_document","application_id":applicant_id}

    if applicant_id and any(k in low for k in ["update address","change address","modify address"]):
        m=re.search(r"(?:update|change|modify)\s+(?:the\s+)?address\s+(?:to|as)\s+(.+)$",text,re.I)
        if not m:
            return {"reply":f"Please provide the new address using: 'Update address to [new address] for application {applicant_id}'.","action":"none"}
        address=m.group(1).strip()
        if not get_application(applicant_id):return {"reply":f"Application {applicant_id} was not found.","action":"none"}
        update_application(applicant_id,application_address=address)
        add_event(applicant_id,"APPLICATION_ADDRESS_UPDATED",{"new_address":address,"source":"copilot_chat"})
        docs=[d for d in get_documents(applicant_id) if d["status"]!="SUPERSEDED"]
        if docs:
            result=process_application(applicant_id,ProcessRequest())
            return {"reply":f"Updated the address for {applicant_id} and automatically re-ran KYC. Result: {result['workflow_status']}. Issues: {', '.join(x['code'] for x in result.get('verification_issues', [])) or 'None'}.","action":"show_application","application_id":applicant_id,"result":result}
        return {"reply":f"Updated the application address for {applicant_id}. No active documents are available yet; KYC will run automatically after document submission.","action":"show_application","application_id":applicant_id}

    # Policy questions are answered only from retrieved guideline evidence.
    policy_terms = [
        "kyc", "document", "passport", "proof of address", "address verification",
        "identity", "expiry", "expired", "verification", "risk", "onboarding",
        "account", "guideline", "guidelines", "requirements", "escalation",
        "eligibility", "eligible", "minimum age", "age", "joint", "co-applicant",
        "applicant", "student", "classic", "basic", "savings", "current account",
        "accepted", "required", "open", "opening", "holder", "qualification"
    ]
    if _looks_like_policy_question(low, policy_terms):
        hits = search_knowledge(text, n_results=6)
        threshold = float(os.getenv("RAG_SCOPE_DISTANCE_THRESHOLD", "0.75"))
        relevant = [h for h in hits if h.get("distance") is not None and h["distance"] <= threshold]
        relevant = _prioritise_account_sources(low, relevant)
        if not relevant:
            return {
                "reply": "I couldn't find this information in the uploaded KYC guidelines. Please check the current approved policy or ask an authorised reviewer. I won't infer or invent a policy answer.",
                "action": "out_of_scope",
            }
        try:
            answer, usage = _generate_grounded_answer(text, relevant[:4])
        except Exception as exc:
            return {
                "reply": "I found relevant guideline material, but couldn't generate a concise answer because the language service is unavailable. Please retry shortly. The source documents are listed below.",
                "action": "policy_answer",
                "sources": _source_list(relevant[:4]),
                "generation_error": type(exc).__name__,
            }
        return {
            "reply": answer,
            "action": "policy_answer",
            "sources": _source_list(relevant[:4]),
            "llm_usage": usage,
        }

    return {"reply":"I can help with account opening, pending KYC application lookup, existing application updates, KYC verification, and questions answered from uploaded KYC guidelines. This request doesn't match a supported workflow or the indexed guideline scope. Please rephrase or choose one of those tasks.","action":"out_of_scope"}
