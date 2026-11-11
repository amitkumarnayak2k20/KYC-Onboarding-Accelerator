import json, sqlite3, time, uuid
from ..config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
 applicant_id TEXT PRIMARY KEY, full_name TEXT NOT NULL, email_redacted TEXT,
 created_at REAL NOT NULL, latest_result TEXT
);
CREATE TABLE IF NOT EXISTS audit_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, applicant_id TEXT NOT NULL,
 event_type TEXT NOT NULL, event_json TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS applicant_documents (
 document_id TEXT PRIMARY KEY, applicant_id TEXT NOT NULL, document_type TEXT NOT NULL,
 document_text TEXT NOT NULL, source_filename TEXT, vendor_version TEXT NOT NULL,
 status TEXT NOT NULL, received_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_documents_applicant ON applicant_documents(applicant_id, received_at);
CREATE TABLE IF NOT EXISTS document_requests (
 request_id TEXT PRIMARY KEY, applicant_id TEXT NOT NULL, document_type TEXT NOT NULL,
 reason TEXT NOT NULL, request_status TEXT NOT NULL, created_at REAL NOT NULL
);
"""

def connect():
    conn=sqlite3.connect(settings.database_path); conn.row_factory=sqlite3.Row; conn.executescript(SCHEMA)
    cols={r["name"] for r in conn.execute("PRAGMA table_info(applications)").fetchall()}
    if "application_address" not in cols: conn.execute("ALTER TABLE applications ADD COLUMN application_address TEXT")
    if "application_status" not in cols: conn.execute("ALTER TABLE applications ADD COLUMN application_status TEXT DEFAULT 'IN_PROGRESS'")
    return conn

def create_application(applicant_id, full_name, email_redacted, application_address=None):
    with connect() as c:
        c.execute("INSERT INTO applications(applicant_id,full_name,email_redacted,created_at,application_address,application_status) VALUES(?,?,?,?,?,?)",
                  (applicant_id,full_name,email_redacted,time.time(),application_address,"IN_PROGRESS"))

def get_application(applicant_id):
    with connect() as c:
        r=c.execute("SELECT * FROM applications WHERE applicant_id=?",(applicant_id,)).fetchone()
        if not r:return None
        d=dict(r)
        if d.get("latest_result"): d["latest_result"]=json.loads(d["latest_result"])
        return d

def save_result(applicant_id,result):
    with connect() as c:c.execute("UPDATE applications SET latest_result=?,application_status=? WHERE applicant_id=?",
                                  (json.dumps(result),result.get("workflow_status","IN_PROGRESS"),applicant_id))

def add_document(applicant_id,document_type,document_text,vendor_version="ocr-v1",source_filename=None):
    now=time.time(); did=str(uuid.uuid4())
    with connect() as c:c.execute("INSERT INTO applicant_documents VALUES(?,?,?,?,?,?,?,?,?)",
        (did,applicant_id,document_type,document_text,source_filename,vendor_version,"RECEIVED",now,now))
    return {"document_id":did,"document_type":document_type,"status":"RECEIVED","received_at":now,"vendor_version":vendor_version}

def get_documents(applicant_id):
    with connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM applicant_documents WHERE applicant_id=? ORDER BY received_at",(applicant_id,)).fetchall()]

def update_document_status(document_id,status):
    with connect() as c:c.execute("UPDATE applicant_documents SET status=?,updated_at=? WHERE document_id=?",(status,time.time(),document_id))

def create_document_request(applicant_id,document_type,reason,status):
    rid=str(uuid.uuid4()); now=time.time()
    with connect() as c:c.execute("INSERT INTO document_requests VALUES(?,?,?,?,?,?)",(rid,applicant_id,document_type,reason,status,now))
    return {"request_id":rid,"document_type":document_type,"reason":reason,"status":status,"created_at":now}

def get_document_requests(applicant_id):
    with connect() as c:return [dict(r) for r in c.execute("SELECT * FROM document_requests WHERE applicant_id=? ORDER BY created_at",(applicant_id,)).fetchall()]

def add_event(applicant_id,event_type,payload):
    with connect() as c:c.execute("INSERT INTO audit_events(applicant_id,event_type,event_json,created_at) VALUES(?,?,?,?)",(applicant_id,event_type,json.dumps(payload),time.time()))

def get_events(applicant_id):
    with connect() as c:
        rows=c.execute("SELECT event_type,event_json,created_at FROM audit_events WHERE applicant_id=? ORDER BY id",(applicant_id,)).fetchall()
        return [{"event_type":r["event_type"],"payload":json.loads(r["event_json"]),"created_at":r["created_at"]} for r in rows]

def get_slo_counts():
    with connect() as c:
        decisions=c.execute("SELECT COUNT(DISTINCT applicant_id) n FROM audit_events WHERE event_type='APPLICATION_DECISION_RECORDED'").fetchone()["n"]
        bad=c.execute("SELECT COUNT(DISTINCT applicant_id) n FROM audit_events WHERE event_type='DUPLICATE_DOCUMENT_REQUEST_SENT'").fetchone()["n"]
    good=max(0,decisions-bad)
    return {"applications_with_decision":decisions,"decisions_without_duplicate_document_request":good,
            "applications_with_duplicate_document_request":bad,"slo_attainment":good/decisions if decisions else None}


def list_applications(status: str | None = None, limit: int = 100):
    with connect() as c:
        if status:
            rows=c.execute("SELECT * FROM applications WHERE application_status=? ORDER BY created_at DESC LIMIT ?",(status,limit)).fetchall()
        else:
            rows=c.execute("SELECT * FROM applications ORDER BY created_at DESC LIMIT ?",(limit,)).fetchall()
        out=[]
        for row in rows:
            item=dict(row)
            if item.get("latest_result"):
                item["latest_result"]=json.loads(item["latest_result"])
            out.append(item)
        return out

def update_application(applicant_id: str, full_name: str | None = None, application_address: str | None = None):
    with connect() as c:
        if full_name is not None:
            c.execute("UPDATE applications SET full_name=? WHERE applicant_id=?",(full_name,applicant_id))
        if application_address is not None:
            c.execute("UPDATE applications SET application_address=? WHERE applicant_id=?",(application_address,applicant_id))
        return c.execute("SELECT changes() AS n").fetchone()["n"] > 0


def supersede_documents(applicant_id: str, document_type: str):
    with connect() as c:
        rows=c.execute("SELECT document_id FROM applicant_documents WHERE applicant_id=? AND document_type=? AND status!='SUPERSEDED'",(applicant_id,document_type)).fetchall()
        ids=[r["document_id"] for r in rows]
        if ids:
            c.executemany("UPDATE applicant_documents SET status='SUPERSEDED',updated_at=? WHERE document_id=?",
                          [(time.time(),doc_id) for doc_id in ids])
        return ids
