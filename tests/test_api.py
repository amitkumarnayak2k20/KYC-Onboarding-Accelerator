import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fastapi.testclient import TestClient
from kyc_agent.api import app

def test_health():
    client = TestClient(app)
    assert client.get("/health").status_code == 200
