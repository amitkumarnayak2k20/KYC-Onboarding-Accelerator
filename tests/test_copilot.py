from kyc_agent import agent


def test_new_account_intent_opens_intake_form(monkeypatch):
    monkeypatch.setattr(agent, "search_knowledge", lambda *a, **k: [])
    result = agent.chat("I want to open a new account")
    assert result["action"] == "open_new_application"
    assert "full name" in result["reply"].lower()


def test_pending_kyc_intent_returns_application_ids(monkeypatch):
    monkeypatch.setattr(agent, "list_applications", lambda **kwargs: [
        {"applicant_id": "APP-1001", "full_name": "Synthetic Applicant", "application_status": "IN_PROGRESS", "latest_result": None, "created_at": 1}
    ])
    monkeypatch.setattr(agent, "get_documents", lambda applicant_id: [{"document_id": "d1"}])
    result = agent.chat("Show me application IDs pending for KYC verification")
    assert result["action"] == "show_pending"
    assert "APP-1001" in result["reply"]


def test_out_of_scope_policy_question_is_not_invented(monkeypatch):
    monkeypatch.setattr(agent, "search_knowledge", lambda *a, **k: [])
    result = agent.chat("What is the KYC rule for a product not in our uploaded policy?")
    assert result["action"] == "out_of_scope"
    assert "couldn't find" in result["reply"].lower()


def test_name_update_is_audited(monkeypatch):
    captured = {}
    monkeypatch.setattr(agent, "get_application", lambda applicant_id: {"applicant_id": applicant_id})
    monkeypatch.setattr(agent, "update_application", lambda applicant_id, **kwargs: captured.update({"id": applicant_id, **kwargs}))
    monkeypatch.setattr(agent, "add_event", lambda applicant_id, event, payload: captured.update({"event": event}))
    result = agent.chat("Change name to Asha Rao for application APP-12345678")
    assert result["action"] == "show_application"
    assert captured["id"] == "APP-12345678"
    assert captured["full_name"] == "Asha Rao"
    assert captured["event"] == "APPLICATION_NAME_UPDATED"
