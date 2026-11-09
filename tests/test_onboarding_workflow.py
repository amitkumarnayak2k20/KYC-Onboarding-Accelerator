from dataclasses import replace
from fastapi.testclient import TestClient
from kyc_agent import api
from kyc_agent.config import settings
from kyc_agent.audit import store as audit_store


def test_inventory_process_and_duplicate_request_guard(tmp_path, monkeypatch):
    db = tmp_path / "workflow.sqlite"
    monkeypatch.setattr(audit_store, "settings", replace(settings, database_path=str(db)))
    client = TestClient(api.app)

    created = client.post("/applications", json={
        "applicant_id": "workflow-001",
        "full_name": "Asha Rao",
        "application_address": "12 Sample Road, Hyderabad, Telangana, 500001"
    })
    assert created.status_code == 201

    submitted = client.post("/applications/workflow-001/documents", json={
        "document_type": "passport",
        "vendor_version": "ocr-v1",
        "document_text": (
            "Name: Asha Rao\nDate of Birth: 1990-06-15\n"
            "Document Number: P1234567\nExpiry Date: 2030-06-15\n"
            "Address: 12 Sample Road, Hyderabad, Telangana, 500001"
        )
    })
    assert submitted.status_code == 201

    inventory = client.get("/applications/workflow-001/documents").json()
    assert len(inventory["documents"]) == 1
    assert "document_text" not in inventory["documents"][0]

    processed = client.post("/applications/workflow-001/process", json={})
    assert processed.status_code == 200
    assert processed.json()["documents_checked"][0]["status"] == "VERIFIED"
    assert processed.json()["human_review_required"] is True

    request = client.post("/applications/workflow-001/document-requests", json={
        "document_type": "passport", "reason": "Passport copy requested"
    })
    assert request.status_code == 200
    assert request.json()["sent_to_customer"] is False
    assert request.json()["request"]["status"] == "BLOCKED_DUPLICATE"

    audit = client.get("/applications/workflow-001/audit").json()["events"]
    event_types = [e["event_type"] for e in audit]
    assert "DOCUMENT_RECEIVED" in event_types
    assert "DOCUMENT_CHECK_COMPLETED" in event_types
    assert "APPLICATION_DECISION_RECORDED" in event_types
    assert "DUPLICATE_DOCUMENT_REQUEST_BLOCKED" in event_types

    slo = client.get("/slo/summary").json()
    assert slo["applications_with_decision"] == 1
    assert slo["slo_attainment"] == 1.0


def test_process_requires_a_submitted_document(tmp_path, monkeypatch):
    monkeypatch.setattr(audit_store, "settings", replace(settings, database_path=str(tmp_path / "empty.sqlite")))
    client = TestClient(api.app)
    client.post("/applications", json={"applicant_id": "empty-001", "full_name": "Test User"})
    response = client.post("/applications/empty-001/process", json={})
    assert response.status_code == 400
    assert "Submit at least one document" in response.json()["detail"]


def test_identity_document_required(tmp_path, monkeypatch):
    monkeypatch.setattr(audit_store, "settings", replace(settings, database_path=str(tmp_path / "no-id.sqlite")))
    client = TestClient(api.app)
    client.post("/applications", json={"applicant_id": "no-id-001", "full_name": "Test User"})
    client.post("/applications/no-id-001/documents", json={
        "document_type": "proof_of_address",
        "document_text": "Name: Test User\nAddress: 1 Sample Road, Hyderabad"
    })
    response = client.post("/applications/no-id-001/process", json={})
    assert response.status_code == 400
    assert "identity document is required" in response.json()["detail"]
