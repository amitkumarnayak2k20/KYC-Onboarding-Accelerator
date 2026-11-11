# Architecture — Onboarding Accelerator

```mermaid
flowchart TB
  subgraph User[User experience]
    UI[Copilot-style Web UI<br/>Chat · New application · Pending queue · Guideline upload]
  end
  subgraph API[FastAPI application layer]
    CHAT[Chat intent router / scope guard]
    APP[Application & document APIs]
    ADMIN[Guideline upload & re-index API]
    ORCH[Onboarding orchestrator]
  end
  subgraph Core[Agent capabilities]
    EXT[extract_document_fields]
    ADDR[verify_address]
    RISK[assign_risk_rating]
    RET[Policy retrieval / RAG]
  end
  subgraph Data[Persistence layer]
    SQL[(SQLite<br/>Applications · Documents · Requests · Audit)]
    CHROMA[(ChromaDB<br/>Policy chunks + embeddings)]
    FILES[Guideline source files]
  end
  subgraph Ingest[Policy ingestion pipeline]
    LOAD[Loaders: PDF / DOCX / HTML / CSV / JSON / TXT / MD]
    PII[PII pattern redaction]
    CHUNK[Chunking + overlap]
    EMB[OpenAI embeddings]
  end
  subgraph Obs[Cross-cutting observability & operations]
    OTEL[OpenTelemetry traces] --> JAEGER[Jaeger]
    MET[Prometheus metrics] --> GRAF[Grafana dashboards]
    MET --> ALERT[Alert rules / Alertmanager / Runbooks]
    EVAL[Golden-set field evaluation] --> DRIFT[OCR accuracy drift detection]
  end
  UI --> CHAT
  UI --> APP
  UI --> ADMIN
  CHAT --> SQL
  CHAT --> RET
  CHAT --> ORCH
  APP --> SQL
  APP --> ORCH
  ORCH --> EXT
  ORCH --> ADDR
  ORCH --> RISK
  ORCH --> RET
  ORCH --> SQL
  ADMIN --> FILES --> LOAD --> PII --> CHUNK --> EMB --> CHROMA
  RET <--> CHROMA
  ORCH -. telemetry .-> OTEL
  ORCH -. metrics .-> MET
  ORCH -. evaluation .-> EVAL
```

## Main runtime paths
- **Scenario 1 — pending queue:** chat asks the SQLite application store for applications with no assessment or with a review/needs-information status, then returns application IDs.
- **Scenario 2 — modification:** the user identifies an existing application ID; name/address changes are persisted with audit events. Replacement uploads supersede the previous active document of that type and preserve history.
- **Scenario 3 — fresh application:** the chat opens the intake form; the UI creates an application ID, uploads documents, registers them in SQLite and calls the orchestrator.
- **Guideline RAG:** an authorised user uploads policy files; loaders, PII pattern redaction, chunking, embeddings and ChromaDB indexing create a searchable policy collection. The chat only answers policy questions when retrieval passes the scope gate.

## Trust boundaries
The frontend/API is unauthenticated in this local training environment. Do not expose it to the internet or use real customer data. Production would require SSO/RBAC, encryption, secure object storage, malware scanning, immutable audit, retention policies, approved OCR/identity providers, human review queues and security/legal approval.
